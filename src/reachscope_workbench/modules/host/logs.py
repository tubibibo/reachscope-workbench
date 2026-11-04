"""Bounded offline log indicators over redacted, operator-supplied evidence.

This deliberately implements three documented counters, not a SIEM, Sigma
runtime or incident verdict. Only explicitly zoned timestamps participate in
fixed UTC five-minute bins. Original request/user data never enters the result.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from ...core.models import WorkbenchError

MAX_BYTES = 2 * 1024 * 1024
MAX_LINES = 10_000
MAX_EVENTS = 5_000
MAX_LINE_LENGTH = 16_384
MAX_ALERTS = 100
MAX_WINDOW_LINES = 200
WINDOW_SECONDS = 300
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_WINDOW = timedelta(seconds=WINDOW_SECONDS)
_KINDS = {"access_log", "auth_log"}
_SOURCES = {"operator_supplied_log", "synthetic_demo"}
_MONTHS = {month: index for index, month in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"}
_SSH_METHODS = {"password", "publickey", "keyboard-interactive", "hostbased", "gssapi-with-mic", "none"}
_QUOTED = r'"(?:[^"\\\r\n]|\\.)*"'
_ACCESS = re.compile(
    r'(?P<client>\S{1,128}) \S{1,128} \S{1,512} '
    r'\[(?P<timestamp>[^\]\r\n]{1,50})\] '
    r'"(?P<request>(?:[^"\\\r\n]|\\.)*)" (?P<status>[0-9]{3}) (?:[0-9]{1,20}|-)'
    rf'(?: {_QUOTED} {_QUOTED})?\Z'
)
_CLF_TIME = re.compile(r'([0-9]{2})/([A-Za-z]{3})/([0-9]{4}):([0-9]{2}):([0-9]{2}):([0-9]{2}) ([+-])([0-9]{2})([0-9]{2})\Z')
_ISO_TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z')
_AUTH = re.compile(r'(?P<prefix>.+?)\s+sshd(?:\[[0-9]{1,10}\])?: (?P<message>.+)\Z')
_AUTH_EVENT = re.compile(
    r'(?P<action>Failed|Accepted) (?P<method>[A-Za-z][A-Za-z0-9-]{0,40})(?:/pam)? for '
    r'(?:invalid user )?\S{1,512} from (?P<client>\S{1,128}) port [0-9]{1,5}(?: ssh[12])?(?:[ :].*)?\Z'
)
_SYSLOG_TIME = re.compile(r'[A-Z][a-z]{2} +[0-9]{1,2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\s+\S+)?\Z')
_REFERENCES = [
    {"title": "NGINX 日志格式", "url": "https://nginx.org/en/docs/http/ngx_http_log_module.html"},
    {"title": "OpenSSH 服务与日志边界", "url": "https://man.openbsd.org/sshd"},
    {"title": "Sigma 日志来源与字段要求（仅参考，不执行 Sigma）", "url": "https://sigmahq.io/docs/basics/log-sources.html"},
]
RULE_PARAMETERS = {
    "window_seconds": WINDOW_SECONDS, "window_alignment": "fixed_UTC_epoch_bins", "window_is_sliding": False,
    "http_auth_threshold": 10, "http_auth_statuses": [401, 403], "http_5xx_threshold": 5,
    "ssh_failure_threshold": 5, "duplicate_lines": "counted_as_supplied_with_ambiguity_disclosed",
}
_LIMITATIONS = [
    "只分析用户提供的有限日志片段，未实时采集、联系主机、验证日志完整性或确认安全事件。",
    "计数使用按 Unix 时间对齐的固定 UTC 五分钟窗口，不是滑动窗口；跨窗口的活动可能未达到阈值。",
    "401/403 重复、5xx 和 SSH 认证失败都是人工调查线索；合法重试、服务故障或重复采集也可能触发。",
    "RFC3164 日志没有年份和时区，不猜测当前年份；未知时间、无效客户端和未识别行不参加时间窗口计数。",
    "客户端使用文件内哈希别名；别名仅供片段内关联，不保证不可逆匿名，也不用于跨文件身份匹配。",
    "不保存用户名、原始请求路径/查询、Referer、User-Agent、认证材料或原始日志行；上传原文件仍保存在本地。",
    "未命中阈值不表示安全、攻击不存在或整改完成；日志结果永不作为配置案例已修复的自动证明。",
]


def _text(raw: bytes, kind: str, host_id: str) -> str:
    if not isinstance(kind, str) or kind not in _KINDS:
        raise WorkbenchError("INVALID_HOST_LOG_KIND", "请选择受支持的 Nginx 访问日志或 OpenSSH 认证日志格式")
    if not isinstance(host_id, str) or not host_id.strip() or len(host_id) > 128 or not host_id.isprintable():
        raise WorkbenchError("INVALID_HOST_ID", "主机标识须为 1–128 个可显示字符")
    if not isinstance(raw, bytes):
        raise WorkbenchError("INVALID_HOST_LOG", "日志必须是上传的 UTF-8 文件字节")
    if not raw or len(raw) > MAX_BYTES:
        raise WorkbenchError("HOST_LOG_LIMIT", "日志须为非空且不超过 2 MiB 的 UTF-8 文本")
    try:
        result = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WorkbenchError("INVALID_HOST_LOG", "日志必须是 UTF-8 文本；无法读取的内容不会作为证据") from exc
    if "\x00" in result:
        raise WorkbenchError("INVALID_HOST_LOG", "日志包含不支持的二进制字符")
    return result


def _clf_timestamp(value: str) -> datetime | None:
    match = _CLF_TIME.fullmatch(value)
    if match is None:
        return None
    day, month, year, hour, minute, second, sign, offset_hour, offset_minute = match.groups()
    try:
        if int(offset_hour) > 23 or int(offset_minute) > 59:
            return None
        offset = timedelta(hours=int(offset_hour), minutes=int(offset_minute)) * (-1 if sign == "-" else 1)
        moment = datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute), int(second),
                          tzinfo=timezone(offset)).astimezone(UTC)
        return moment if moment <= datetime.max.replace(tzinfo=UTC) - _WINDOW else None
    except (ValueError, KeyError, OverflowError):
        return None


def _auth_timestamp(prefix: str) -> datetime | None:
    token = prefix.split()[0]
    if _ISO_TIME.fullmatch(token) is None:
        # RFC3164's month/day has no year or timezone. Do not invent either.
        return None
    try:
        value = datetime.fromisoformat(token).astimezone(UTC)
        return value if value <= datetime.max.replace(tzinfo=UTC) - _WINDOW else None
    except (ValueError, OverflowError):
        return None


def _alias(client: str, host_id: str, input_sha: str) -> str | None:
    try:
        if "%" in client:
            return None
        normalized = str(ipaddress.ip_address(client))
    except ValueError:
        return None
    value = (host_id + "\x00" + input_sha + "\x00" + normalized).encode("utf-8")
    return "client-" + hashlib.sha256(value).hexdigest()[:16]


def _event(line: str, number: int, kind: str, host_id: str, digest: str, source_kind: str) -> dict[str, Any] | None:
    timestamp: datetime | None
    if kind == "access_log":
        parsed = _ACCESS.fullmatch(line)
        if parsed is None or not 100 <= int(parsed["status"]) <= 599:
            return None
        timestamp = _clf_timestamp(parsed["timestamp"])
        actor = _alias(parsed["client"], host_id, digest)
        request = parsed["request"].split(" ", 2)
        method = request[0] if request[0] in _METHODS else "OTHER"
        target = request[1] if len(request) == 3 else ""
        category = "root" if target.partition("?")[0] == "/" else "other" if target else "unknown"
        event_class, status = "http_access", int(parsed["status"])
    else:
        message = _AUTH.fullmatch(line)
        if message is None:
            return None
        auth = _AUTH_EVENT.fullmatch(message["message"])
        if auth is None:
            return None
        timestamp = _auth_timestamp(message["prefix"])
        actor = _alias(auth["client"], host_id, digest)
        method = auth["method"] if auth["method"] in _SSH_METHODS else "OTHER"
        category = "unknown"
        event_class = "ssh_auth_failure" if auth["action"] == "Failed" else "ssh_auth_success"
        status = None
    return {"id": f"{kind}:event:{number}", "line_number": number, "input_kind": kind, "source_kind": source_kind,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z") if timestamp is not None else None,
            "timestamp_status": "known" if timestamp is not None else "unknown",
            "actor_alias": actor, "event_class": event_class, "status_code": status,
            "method": method, "path_category": category, "rule_eligible": timestamp is not None and actor is not None}


def _parse(raw: bytes, kind: str, host_id: str, source_kind: str = "operator_supplied_log") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text = _text(raw, kind, host_id)
    # Input pointers are LF/CRLF file lines, not Unicode separator characters
    # that might occur inside a literal logged request.
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    lines = [line.removesuffix("\r") for line in lines]
    digest = hashlib.sha256(raw).hexdigest()
    coverage: dict[str, Any] = {
        "input_bytes": len(raw), "input_sha256": digest, "source_kind": source_kind, "input_kind": kind,
        "line_definition": "LF_or_CRLF", "total_lines": len(lines), "examined_lines": 0,
        "parsed_events": 0, "returned_events": 0, "empty_lines": 0, "unparsed_lines": 0,
        "unsupported_lines": 0, "timestamp_unknown_events": 0, "invalid_ip_lines": 0,
        "overlong_lines": 0, "duplicate_events": 0, "line_budget_exhausted": len(lines) > MAX_LINES,
        "event_budget_exhausted": False,
    }
    events: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for number, line in enumerate(lines[:MAX_LINES], 1):
        coverage["examined_lines"] += 1
        if not line.strip():
            coverage["empty_lines"] += 1
            continue
        if len(line) > MAX_LINE_LENGTH:
            coverage["overlong_lines"] += 1
            continue
        row = _event(line, number, kind, host_id, digest, source_kind)
        if row is None:
            coverage["unparsed_lines"] += 1
            if kind == "auth_log" and ("sshd" in line or _SYSLOG_TIME.match(line)):
                coverage["unsupported_lines"] += 1
            continue
        coverage["parsed_events"] += 1
        if row["timestamp"] is None:
            coverage["timestamp_unknown_events"] += 1
        if row["actor_alias"] is None:
            coverage["invalid_ip_lines"] += 1
        signature = hashlib.sha256(line.encode("utf-8")).digest()
        if signature in seen:
            coverage["duplicate_events"] += 1
        seen.add(signature)
        if len(events) >= MAX_EVENTS:
            coverage["event_budget_exhausted"] = True
            continue
        events.append(row)
    coverage["returned_events"] = len(events)
    coverage["truncated"] = bool(coverage["line_budget_exhausted"] or coverage["event_budget_exhausted"] or coverage["overlong_lines"])
    coverage["complete"] = bool(events) and not any(coverage[key] for key in (
        "truncated", "unparsed_lines", "timestamp_unknown_events", "invalid_ip_lines", "duplicate_events"))
    return events, coverage


def preview_logs(raw: bytes, kind: str, host_id: str) -> dict[str, Any]:
    """Parse counts only, with no security rules, evidence, events or raw values."""
    _events, coverage = _parse(raw, kind, host_id)
    return {"version": 1, "module": "host", "host_id": host_id, "input_kind": kind,
            "sha256": coverage["input_sha256"], "coverage": coverage,
            "analysis_executed": False, "network_requests": False,
            "limits": {"bytes": MAX_BYTES, "lines": MAX_LINES, "events": MAX_EVENTS, "line_characters": MAX_LINE_LENGTH},
            "limitations": ["预览仅检查文本格式和有限字段覆盖；没有执行检测规则、创建任务或建立证据。", *_LIMITATIONS]}


def _guidance(rule: str) -> dict[str, Any]:
    http_auth = rule == "host.logs.http_auth_burst"
    failure = rule == "host.logs.http_5xx_burst"
    blue = (["结合服务错误日志、最近变更、资源容量和依赖状态排查 5xx；优先恢复业务可用性，不把服务错误直接认定为攻击。"] if failure else
            ["核对身份验证策略、合法自动化与重试行为；依据实际业务评估限速、告警或访问控制调整，先保留管理回退通道。"])
    return {"prerequisites": ["确认日志来源主机、采集范围、时间/时区与业务维护窗口；客户端别名可能对应代理或共享出口。",
                              "原日志仅由有权人员在本机复核；不得把认证材料或完整请求参数复制到模型或工单。"],
            "red_review": ["对照保存行号、固定窗口与阈值核实计数，并排除重复采集和正常业务重试；不进行自动攻击或登录尝试。"],
            "blue_steps": blue,
            "verification": ["由维护者核实同一时间范围的原始数据、业务记录和相关日志，保留调查结论。",
                             "新的日志片段只能提供新的调查资料；未再命中不能证明原问题已修复或入侵不存在。"],
            "rollback": ["任何实际防护变更先记录原策略与影响范围；误伤合法业务时按既有发布/应急流程回退，工具不会执行变更。"],
            "limitations": ["401/403 也可能来自过期会话、应用鉴权或代理策略。" if http_auth else
                            "5xx 是服务失败线索，不等于恶意活动。" if failure else "SSH 认证失败可由用户输错、扫描、服务账户配置或攻击造成，未核实真实原因。",
                            "固定窗口和片段完整性限制必须保留；没有自动封禁、账号处置或安全事件确认。"],
            "references": [dict(item) for item in _REFERENCES], "ai_required": False, "executed": False}


def _windows(events: list[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if not event["rule_eligible"]:
            continue
        matches = (event["status_code"] in {401, 403} if rule == "host.logs.http_auth_burst" else
                   event["status_code"] is not None and 500 <= event["status_code"] <= 599 if rule == "host.logs.http_5xx_burst" else
                   event["event_class"] == "ssh_auth_failure")
        if not matches:
            continue
        timestamp = datetime.fromisoformat(event["timestamp"])
        bucket = (timestamp - _EPOCH) // _WINDOW
        actor = "host-total" if rule == "host.logs.http_5xx_burst" else event["actor_alias"]
        groups[(bucket, actor)].append(event)
    threshold = 10 if rule == "host.logs.http_auth_burst" else 5
    windows = []
    for (bucket, actor), rows in sorted(groups.items()):
        if len(rows) < threshold:
            continue
        start = _EPOCH + bucket * _WINDOW
        windows.append({"window_start": start.isoformat().replace("+00:00", "Z"),
                        "window_end": (start + timedelta(seconds=WINDOW_SECONDS)).isoformat().replace("+00:00", "Z"),
                        "actor_alias": actor if actor != "host-total" else None, "count": len(rows), "threshold": threshold,
                        "line_numbers": sorted(row["line_number"] for row in rows)[:MAX_WINDOW_LINES],
                        "line_numbers_truncated": len(rows) > MAX_WINDOW_LINES})
    return windows


def assess_logs(raw: bytes, kind: str, host_id: str, *, source_kind: str = "operator_supplied_log") -> dict[str, Any]:
    """Return immutable JSON-ready, evidence-bound indicators, never a fix verdict."""
    if not isinstance(source_kind, str) or source_kind not in _SOURCES:
        raise WorkbenchError("INVALID_HOST_LOG_SOURCE", "日志来源须为操作员提供的日志或明确标记的合成样例")
    events, coverage = _parse(raw, kind, host_id, source_kind)
    rules = ["host.logs.http_auth_burst", "host.logs.http_5xx_burst"] if kind == "access_log" else ["host.logs.ssh_failure_burst"]
    titles = {"host.logs.http_auth_burst": "同一客户端集中出现 401/403", "host.logs.http_5xx_burst": "服务集中出现 5xx 响应",
              "host.logs.ssh_failure_burst": "同一客户端集中出现 SSH 认证失败"}
    checks, evidence = [], []
    remaining = MAX_ALERTS
    windows_total = 0
    for rule in rules:
        windows = _windows(events, rule)
        windows_total += len(windows)
        returned = windows[:remaining]
        remaining -= len(returned)
        complete = coverage["complete"] and len(returned) == len(windows) and not any(row["line_numbers_truncated"] for row in windows)
        state = "review" if windows else "info" if complete else "unknown"
        summary_id = "host-log-summary:" + rule
        ids = [summary_id]
        for index, window in enumerate(returned):
            eid = f"host-log-window:{rule}:{index}"
            ids.append(eid)
            evidence.append({"id": eid, "kind": "host_log_indicator", "title": titles[rule], "source": kind,
                             "sha256": coverage["input_sha256"],
                             "data": {"host_id": host_id, "rule_id": rule, "source_kind": source_kind, "input_kind": kind, "window": window,
                                      "confirmed_incident": False, "runtime_verified": False}})
        values = {"windows_total": len(windows), "windows_returned": len(returned), "windows_truncated": len(returned) != len(windows),
                  "rule_parameters": copy.deepcopy(RULE_PARAMETERS), "coverage": dict(coverage), "confirmed_incident": False}
        evidence.append({"id": summary_id, "kind": "host_log_summary", "title": titles[rule] + " / 规则范围", "source": kind,
                         "sha256": coverage["input_sha256"], "data": {"host_id": host_id, "rule_id": rule, "values": values,
                                "source_kind": source_kind, "input_kind": kind, "line_numbers_are_input_lines": True}})
        description = (f"输入片段有 {len(windows)} 个固定 UTC 五分钟窗口达到计数阈值；只形成待人工复核线索。" if windows else
                       "已解析片段未命中本规则阈值；不表示主机安全、攻击不存在或整改成功。" if complete else
                       "时间、格式、客户端或预算存在覆盖缺口，当前片段无法形成完整的规则计数结论。")
        checks.append({"id": rule, "resource_id": host_id, "status": state, "complete": bool(complete),
                       "severity": "low" if state == "review" else "info", "title": titles[rule], "description": description,
                       "recommendation": "先复核原始行号、业务与重复采集情况，再决定人工处置。", "evidence_ids": ids,
                       "evidence": {"pointer": "/log_events", "values": values}, "guidance": _guidance(rule),
                       "source_kind": source_kind, "input_kind": kind, "retest_can_prove_fix": False})
    coverage["alert_windows_total"] = windows_total
    coverage["alert_windows_returned"] = MAX_ALERTS - remaining
    coverage["alert_budget_exhausted"] = windows_total > MAX_ALERTS - remaining
    if coverage["alert_budget_exhausted"]:
        coverage.update(complete=False, truncated=True)
    return {"checks": checks, "evidence": evidence, "coverage": coverage, "log_events": events,
            "source_kind": source_kind, "input_kind": kind, "rule_parameters": copy.deepcopy(RULE_PARAMETERS),
            "limitations": (["这是固定合成教学日志，未采集真实主机日志或验证生产事件。"] if source_kind == "synthetic_demo" else []) + list(_LIMITATIONS),
            "redaction": {"raw_lines_saved_in_result": False, "usernames_saved": False, "raw_urls_saved": False,
                          "actor_scope": "per_host_and_input_digest", "original_upload_retained_locally": source_kind == "operator_supplied_log"}}
