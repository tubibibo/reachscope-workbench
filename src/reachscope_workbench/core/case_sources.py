"""Evidence-bound case candidates and conservative, read-only retest semantics.

Only persisted result data is consumed. This module performs no probing, cloud
access, claim verification, state mutation or permission/effective-access analysis.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import WorkbenchError

_PAGE_CHECKS = {"password_forms", "mixed_content"}


def _scope_key_without_projection(value: str) -> str:
    """Return the semantic key without a projected /2 collector namespace."""
    return re.sub(r"^projected:[^:]+:", "", value)
_HEADER_CHECKS = {"csp", "frame_protection", "nosniff", "referrer_policy", "hsts", "cors",
                  "cookie_secure", "cookie_http_only", "cookie_same_site", "tls_expiry"}
_CLOUD_GROUPS = {"network": "network", "iam": "iam", "storage": "storage"}
_CLOUD_CLEAR_INFO = {"iam.broad_allow", "iam.trust_principal", "storage.bucket_policy_principal"}
_ANDROID_CHECKS = {"android.debuggable", "android.test_only", "android.backup", "android.cleartext",
                   "android.trust_anchors", "android.debug_overrides", "android.exported_components", "android.deeplinks"}
_HOST_BASELINE = {"host.ssh.root_login": "ssh", "host.ssh.password_auth": "ssh", "host.ssh.empty_passwords": "ssh",
                  "host.ssh.max_auth_tries": "ssh", "host.nginx.autoindex": "nginx", "host.nginx.server_tokens": "nginx",
                  "host.nginx.tls_protocols": "nginx"}
_HOST_LOGS = {"host.logs.http_auth_burst", "host.logs.http_5xx_burst", "host.logs.ssh_failure_burst"}
_NOISE = {"fingerprint", "body_limit", "redirect_scope", "cookie_capture", "header_capture"}
_LIMITATIONS = [
    "复测只读取保存结果，不发送请求、不执行验证、不自动关闭案例。",
    "未再次观察到仅针对相同资产和已执行规则；不证明漏洞不可利用、云权限最小化或整体安全。",
    "缺少资源、失败请求、未知/截断字段、未执行检查和不支持表达式不会被当成整改成功。",
    "人工记录和外部扫描报告保持其来源与不确定性；导入报告不自动成为已验证发现。",
]


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _details(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("details")
    return value if isinstance(value, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _android_review(result: dict[str, Any]) -> dict[str, Any]:
    review = _mapping(_details(result).get("security_review"))
    if type(review.get("version")) is not int or review["version"] != 1:
        return {}
    package = review.get("package")
    if not isinstance(package, str) or not package.strip() or len(package) > 500:
        return {}
    return review


def _host_review(result: dict[str, Any]) -> dict[str, Any]:
    details = _details(result)
    if type(details.get("review_version")) is not int or details["review_version"] != 1:
        return {}
    host_id = details.get("host_id")
    return details if isinstance(host_id, str) and host_id.strip() and len(host_id) <= 128 else {}


def _host_collection_time(details: dict[str, Any]) -> datetime | None:
    collection = _mapping(details.get("collection"))
    value = collection.get("collected_at")
    if collection.get("collection_state") != "provided_not_verified" or not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _url(value: Any) -> str:
    """Canonical identity of saved input URLs, not a network-scope validator."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(char) < 33 for char in value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        hostname = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if not hostname:
            return ""
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port is not None:
            authority += f":{parts.port}"
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))
    except (UnicodeError, ValueError):
        return ""


def _job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "completed" or not isinstance(job.get("result"), dict):
        raise WorkbenchError("RESULT_UNAVAILABLE", "只能从已完成的分析结果中选择案例来源")
    if not isinstance(job.get("asset_id"), str) or not job["asset_id"]:
        raise WorkbenchError("ASSET_REQUIRED", "该旧记录没有绑定资产；请从保存资产执行检查后再建立案例")
    result: dict[str, Any] = job["result"]
    if not isinstance(job.get("id"), str) or not job["id"]:
        raise WorkbenchError("INVALID_RESULT", "案例来源缺少有效任务标识")
    if not isinstance(job.get("module"), str) or job["module"] not in {"android", "web", "cloud", "host"} or result.get("module") != job.get("module"):
        raise WorkbenchError("INVALID_RESULT", "案例来源模块或结果结构无效")
    return result


def _evidence_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _rows(result.get("evidence")) if isinstance(row.get("id"), str)}


def _ids(row: dict[str, Any], known: dict[str, dict[str, Any]]) -> list[str]:
    raw = row.get("evidence_ids")
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(item for item in raw if isinstance(item, str) and item in known))


def _reference(module: str, locator: dict[str, Any]) -> str:
    identity = json.dumps({"module": module, "locator": locator}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "src-" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:32]


def _candidate(
    job: dict[str, Any], row: dict[str, Any], kind: str, locator: dict[str, Any],
    known: dict[str, dict[str, Any]], *, confidence: str, category: str,
) -> dict[str, Any] | None:
    evidence_ids = _ids(row, known)
    if not evidence_ids:
        return None
    severity = row.get("severity")
    return {
        "source_ref": _reference(job["module"], locator), "source_kind": kind,
        "title": (_text(row.get("title")) or "待复核观察")[:500],
        "severity": severity if isinstance(severity, str) and severity in {"info", "low", "medium", "high", "critical"} else "info",
        "confidence": confidence, "asset_id": job["asset_id"], "job_id": job["id"],
        "evidence_ids": evidence_ids, "description": _text(row.get("description"))[:8000],
        "recommendation": _text(row.get("recommendation"))[:4000], "category": category,
        "locator": locator,
    }


def candidates(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Return actionable, evidence-backed source choices without inventing findings."""
    result = _job(job)
    known = _evidence_map(result)
    details = _details(result)
    output: list[dict[str, Any]] = []
    represented: set[tuple[str, tuple[str, ...]]] = set()
    if job["module"] == "cloud":
        for check in _rows(details.get("checks")):
            if check.get("status") not in ("review", "unknown") or not isinstance(check.get("id"), str) or not isinstance(check.get("resource_id"), str):
                continue
            locator = {"type": "cloud_check", "resource_id": check["resource_id"], "check_id": check["id"]}
            candidate = _candidate(job, check, "check", locator, known, confidence="static_config", category=_text(check["id"]))
            if candidate is not None:
                candidate["status"] = check["status"]
                output.append(candidate)
    elif job["module"] == "host":
        review = _host_review(result)
        for check in _rows(review.get("checks")):
            identifier = check.get("id")
            if (not isinstance(identifier, str) or identifier not in {*_HOST_BASELINE, *_HOST_LOGS}
                    or check.get("status") not in ("review", "unknown") or not _text(check.get("resource_id"))):
                continue
            locator = {"type": "host_check", "host_id": review["host_id"], "resource_id": check["resource_id"],
                       "check_id": identifier, "review_version": 1}
            candidate = _candidate(job, check, "check", locator, known,
                                   confidence="static_config" if identifier in _HOST_BASELINE else "log_indicator", category=identifier)
            if candidate is not None:
                candidate["status"] = check["status"]
                output.append(candidate)
    elif job["module"] == "android":
        review = _android_review(result)
        for check in _rows(review.get("checks")):
            if check.get("status") not in ("review", "unknown") or not isinstance(check.get("id"), str) or check["id"] not in _ANDROID_CHECKS:
                continue
            if not isinstance(check.get("resource_id"), str) or not check["resource_id"]:
                continue
            locator = {"type": "android_check", "package": review["package"],
                       "resource_id": check["resource_id"], "check_id": check["id"], "review_version": 1}
            candidate = _candidate(job, check, "check", locator, known,
                                   confidence="static_config", category=check["id"])
            if candidate is not None:
                candidate["status"] = check["status"]
                output.append(candidate)
                represented.add((check["id"], tuple(sorted(candidate["evidence_ids"]))))
    elif job["module"] == "web":
        for asset in _rows(details.get("assets")):
            url = _url(asset.get("url"))
            if not url:
                continue
            for check in _rows(asset.get("checks")):
                if check.get("status") != "review" or not isinstance(check.get("id"), str):
                    continue
                locator = {"type": "web_check", "url": url, "check_id": check["id"]}
                enriched = {**check, "evidence_ids": check.get("evidence_ids", asset.get("evidence_ids", []))}
                candidate = _candidate(job, enriched, "check", locator, known,
                                       confidence="observed_config", category=check["id"])
                if candidate is not None:
                    candidate["status"] = check["status"]
                    output.append(candidate)
                    observation_category = "security_headers" if check["id"] in {"csp", "frame_protection", "nosniff", "referrer_policy"} else check["id"]
                    represented.add((observation_category, tuple(sorted(candidate["evidence_ids"]))))

    for observation in _rows(result.get("observations")):
        category = _text(observation.get("category"))
        if category in _NOISE or not isinstance(observation.get("id"), str):
            continue
        if job["module"] == "android" and observation["id"].startswith("android-config:") and _android_review(result):
            # Structured configuration checks own their cases; derived summary
            # observations must not create a second, non-comparable case.
            continue
        evidence_ids = _ids(observation, known)
        if not evidence_ids or (category, tuple(sorted(evidence_ids))) in represented:
            continue
        # Cloud module observations are derived from its structured checks. A
        # second case for the same resource would duplicate review/unknown work.
        if job["module"] in {"cloud", "host"} and _rows(details.get("checks")):
            continue
        exported = _mapping(result.get("summary")).get("exported")
        android_entry = (job["module"] == "android" and category == "android_attack_surface"
                         and type(exported) is int and exported > 0)
        # An observed exported entry is a useful manual review task, not a
        # vulnerability. Zero exported entries and other info remain context.
        if observation.get("severity") == "info" and category not in {"probe_error", "imported_finding"} and not android_entry:
            continue
        locator = {"type": "observation", "id": observation["id"], "category": category}
        urls = {_url(known[identifier].get("source")) for identifier in evidence_ids}
        urls.discard("")
        if len(urls) == 1:
            locator["url"] = urls.pop()
        observed_confidence = _text(observation.get("confidence"))
        confidence = "imported_unverified" if category == "imported_finding" else observed_confidence if observed_confidence in {"observed", "heuristic", "static_candidate", "static_inference", "static_config", "unknown"} else "heuristic"
        candidate = _candidate(job, observation, "observation", locator, known, confidence=confidence, category=category)
        if candidate is not None:
            output.append(candidate)
    references = [item["source_ref"] for item in output]
    if len(set(references)) != len(references):
        raise WorkbenchError("CASE_SOURCE_AMBIGUOUS", "保存结果存在重复的来源定位，无法唯一绑定案例")
    if len(output) > 5000:
        raise WorkbenchError("CASE_SOURCE_LIMIT", "案例来源超过单次 5000 条预算")
    return copy.deepcopy(output)


def source(job: dict[str, Any], kind: str, ref: str) -> dict[str, Any]:
    if not isinstance(kind, str) or kind not in {"check", "observation"} or not isinstance(ref, str) or len(ref) > 100:
        raise WorkbenchError("INVALID_CASE_SOURCE", "案例来源类型或标识无效")
    selected = next((row for row in candidates(job) if row["source_kind"] == kind and row["source_ref"] == ref), None)
    if selected is None:
        raise WorkbenchError("CASE_SOURCE_NOT_FOUND", "该任务没有这条可建立案例的证据来源")
    return selected


def _completed_group(job: dict[str, Any], group: str) -> bool:
    details = _details(job["result"])
    execution = _rows(details.get("execution"))
    return any(row.get("id") == group and row.get("status") == "completed" for row in execution)


def _proof(result: dict[str, Any], identifiers: list[str]) -> list[dict[str, Any]]:
    known = _evidence_map(result)
    return [copy.deepcopy(known[identifier]) for identifier in identifiers if identifier in known]


def _web_asset(job: dict[str, Any], url: str) -> dict[str, Any] | None:
    rows = [asset for asset in _rows(_details(job["result"]).get("assets")) if _url(asset.get("url")) == url]
    return rows[0] if len(rows) == 1 else None


def _compare_android(
    original: dict[str, Any], selected: dict[str, Any], retest: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    """Compare a known declaration, never infer a fix from missing APK content."""
    locator = selected["locator"]
    if not _completed_group(original, "manifest") or not _completed_group(retest, "manifest"):
        return "not_comparable", "至少一轮未完成 Android 清单配置检查。", [], []
    baseline = _android_review(original["result"])
    current = _android_review(retest["result"])
    if not current or current.get("package") != baseline.get("package") or current.get("package") != locator["package"]:
        return "not_comparable", "复测缺少相同版本的清单审查或应用包名不一致；关联修订文件不替代身份核对。", [], []
    rows = [row for row in _rows(current.get("checks"))
            if row.get("id") == locator["check_id"] and row.get("resource_id") == locator["resource_id"]]
    before = [row for row in _rows(baseline.get("checks"))
              if row.get("id") == locator["check_id"] and row.get("resource_id") == locator["resource_id"]]
    if len(rows) != 1 or len(before) != 1:
        return "not_comparable", "没有唯一的同包名、同资源、同规则清单结果。", rows, []
    check = rows[0]
    identifiers = _ids(check, _evidence_map(retest["result"]))
    if not identifiers:
        return "not_comparable", "复测配置检查没有可回查的保存证据。", rows, []
    if check.get("status") == "review":
        return "still_observed", "相同应用和配置规则仍观察到待复核声明；实际影响仍需人工验证。", rows, identifiers
    if check.get("status") != "pass":
        return "not_comparable", "未知、不适用或缺少资源不能作为 Android 配置已整改的依据。", rows, identifiers
    if (before[0].get("complete") is not True or check.get("complete") is not True
            or before[0].get("facts_truncated") or check.get("facts_truncated") or before[0].get("status") != "review"):
        return "not_comparable", "至少一轮规则证据不完整或基线仅为未知，不能从信息缺口判定原条件已消失。", rows, identifiers
    return ("not_observed_in_scope", "同包名、同规则的完整声明证据满足检查条件；不证明 APK 运行时安全、签名身份或漏洞已被利用。",
            rows, identifiers)


def _compare_host(
    original: dict[str, Any], selected: dict[str, Any], retest: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    locator = selected["locator"]
    identifier = locator["check_id"]
    if identifier not in _HOST_BASELINE:
        return "not_comparable", "有限日志未再次命中不证明防护生效；日志线索需要人工调查，不能作为自动整改清除依据。", [], []
    group = _HOST_BASELINE[identifier]
    if not _completed_group(original, group) or not _completed_group(retest, group):
        return "not_comparable", "至少一轮未完成对应的主机配置基线检查。", [], []
    baseline = _host_review(original["result"])
    current = _host_review(retest["result"])
    if not current or current.get("host_id") != locator["host_id"] or current.get("host_id") != baseline.get("host_id"):
        return "not_comparable", "资料版本或稳定主机标识不一致，不能仅凭相似文件名判定整改。", [], []
    before = [row for row in _rows(baseline.get("checks")) if row.get("id") == identifier and row.get("resource_id") == locator["resource_id"]]
    rows = [row for row in _rows(current.get("checks")) if row.get("id") == identifier and row.get("resource_id") == locator["resource_id"]]
    if len(before) != 1 or len(rows) != 1:
        return "not_comparable", "没有唯一的相同主机、资源和规则结果。", rows, []
    check = rows[0]
    identifiers = _ids(check, _evidence_map(retest["result"]))
    if not identifiers:
        return "not_comparable", "复测缺少可回查配置证据。", rows, []
    if check.get("status") == "review":
        return "still_observed", "同一配置规则仍观察到待复核条件，实际业务影响尚需人工确认。", rows, identifiers
    if (before[0].get("status") != "review" or check.get("status") != "pass"
            or before[0].get("complete") is not True or check.get("complete") is not True
            or before[0].get("facts_truncated") or check.get("facts_truncated")):
        return "not_comparable", "未知、不适用、跳过或不完整资料不能作为主机配置已整改的依据。", rows, identifiers
    identities = [_mapping(row.get("comparison_identity")) for row in (before[0], check)]
    for identity in identities:
        keys = identity.get("scope_keys")
        if (identity.get("complete") is not True or identity.get("component") != group or not isinstance(keys, list)
                or not keys or len(keys) > 200 or any(not isinstance(key, str) or not key for key in keys)
                or len(set(keys)) != len(keys)):
            return "not_comparable", "配置上下文身份不完整，不能把上下文消失或解析缺口当作整改。", rows, identifiers
    before_keys = identities[0]["scope_keys"]
    after_keys = identities[1]["scope_keys"]
    if sorted(before_keys) != sorted(after_keys):
        if sorted(map(_scope_key_without_projection, before_keys)) == sorted(map(_scope_key_without_projection, after_keys)):
            return "not_comparable", "采集格式命名空间不同（/1 与 /2），需人工确认语义等价后复核。", rows, identifiers
        return "not_comparable", "配置上下文集合发生变化，需要补充对应关系后人工复核。", rows, identifiers
    before_time, after_time = _host_collection_time(baseline), _host_collection_time(current)
    if before_time is None or after_time is None or after_time < before_time:
        return "not_comparable", "配置采集时间未知或复测资料早于基线；新建任务不能替代资料时效核对。", rows, identifiers
    return ("not_observed_in_scope", "相同主机、规则与完整配置上下文满足静态检查条件；仍需人工核对配置加载及真实业务回归。",
            rows, identifiers)


def compare_retest(
    original_job: dict[str, Any], source_kind: str, source_ref: str, retest_job: dict[str, Any],
    *, related_asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Conservative rule observation comparison, never an automatic resolution."""
    selected = source(original_job, source_kind, source_ref)
    result: dict[str, Any] = {
        "outcome": "not_comparable", "reason": "该来源需要人工复核，当前没有自动复测判定。",
        "source_job_id": original_job["id"], "retest_job_id": retest_job.get("id"),
        "matching": [], "evidence": [], "limitations": list(_LIMITATIONS), "input_revision": False,
    }

    def report(outcome: str, reason: str, rows: list[dict[str, Any]] | None = None,
               identifiers: list[str] | None = None, *, namespace_only_difference: bool = False) -> dict[str, Any]:
        result.update(outcome=outcome, reason=reason, matching=copy.deepcopy(rows or []))
        if namespace_only_difference:
            result["namespace_only_difference"] = True
        result["evidence"] = _proof(retest_job["result"], identifiers or []) if isinstance(retest_job.get("result"), dict) else []
        return result

    if original_job.get("id") == retest_job.get("id"):
        return report("not_comparable", "请选择另一条完成的检查记录，不能用来源任务复测自身。")
    if retest_job.get("status") != "completed" or not isinstance(retest_job.get("result"), dict):
        return report("not_comparable", "复测任务尚未完成或没有完整结果。")
    if retest_job.get("asset_id") != original_job["asset_id"]:
        linked = related_asset_ids is not None and isinstance(retest_job.get("asset_id"), str) and retest_job["asset_id"] in related_asset_ids
        if not linked or original_job["module"] not in {"android", "cloud", "host"}:
            return report("not_comparable", "复测必须属于同一个保存资产或已显式关联的本地修订文件；地址相似不能替代资产绑定。")
        result["input_revision"] = True
        result["limitations"].append("本次使用显式关联的修订文件，仍需核对相同实际资源身份；关联本身不是身份或部署状态证明。")
    if retest_job.get("module") != original_job["module"] or retest_job["result"].get("module") != original_job["module"]:
        return report("not_comparable", "复测执行模块与来源任务不同。")
    locator = selected["locator"]
    if locator["type"] == "host_check":
        outcome, reason, rows, identifiers = _compare_host(original_job, selected, retest_job)
        return report(outcome, reason, rows, identifiers,
                      namespace_only_difference=reason.startswith("采集格式命名空间不同"))
    if locator["type"] == "android_check":
        return report(*_compare_android(original_job, selected, retest_job))
    if locator["type"] == "cloud_check":
        check_id, resource_id = locator["check_id"], locator["resource_id"]
        group = _CLOUD_GROUPS.get(check_id.partition(".")[0], "")
        if not group or not _completed_group(original_job, group) or not _completed_group(retest_job, group):
            return report("not_comparable", "至少一轮未完成这个云配置规则组。")
        if selected.get("status") == "unknown":
            return report("not_comparable", "来源记录是信息不足，并非已观察到的规则命中；补充资料不能自动解释为已整改。")
        resources = [row for row in _rows(_details(retest_job["result"]).get("resources")) if row.get("id") == resource_id]
        if len(resources) != 1 or resources[0].get("supported") is not True:
            return report("not_comparable", "相同资源缺席或类型未受支持；不能把缺少资源当成已整改。")
        original_resources = [row for row in _rows(_details(original_job["result"]).get("resources")) if row.get("id") == resource_id]
        if len(original_resources) != 1 or not _text(original_resources[0].get("type")) or original_resources[0].get("type") != resources[0].get("type"):
            return report("not_comparable", "资源类型发生变化或缺少原始类型证据，不能仅按同名资源判定整改。")
        matches = [check for check in _rows(_details(retest_job["result"]).get("checks"))
                   if check.get("id") == check_id and check.get("resource_id") == resource_id]
        if len(matches) != 1:
            return report("not_comparable", "没有唯一的同资源同规则检查结果。")
        check = matches[0]
        identifiers = _ids(check, _evidence_map(retest_job["result"]))
        if not identifiers:
            return report("not_comparable", "复测规则缺少可回查证据。")
        if check.get("status") == "review":
            return report("still_observed", "同一资源和规则仍观察到待复核条件。", matches, identifiers)
        proof = _mapping(check.get("evidence"))
        unknown_indexes = proof.get("values", {})
        if isinstance(unknown_indexes, dict) and any(unknown_indexes.get(key) for key in ("unknown_rule_indexes", "unknown_statement_indexes", "unknown")):
            return report("not_comparable", "相同规则仍含未知字段或未支持表达式。", matches, identifiers)
        if check.get("status") == "pass" or check.get("status") == "info" and check_id in _CLOUD_CLEAR_INFO:
            reason = "该次同资源同规则未再次观察到原条件；静态配置变化仍需人工确认。"
            if result["input_revision"]:
                reason += "使用显式关联的修订文件，仍需核对相同实际资源身份。"
            return report("not_observed_in_scope", reason, matches, identifiers)
        return report("not_comparable", "规则状态为未知、不适用或仅一般信息，不能判定原条件已消失。", matches, identifiers)
    if locator["type"] == "web_check":
        check_id, url = locator["check_id"], locator["url"]
        group = "page" if check_id in _PAGE_CHECKS else "headers" if check_id in _HEADER_CHECKS else ""
        if not group or not _completed_group(original_job, group) or not _completed_group(retest_job, group):
            return report("not_comparable", "至少一轮未完成对应的页面或响应配置检查。")
        asset = _web_asset(retest_job, url)
        if asset is None or asset.get("reachable") is not True:
            return report("not_comparable", "原始精确 URL 没有唯一的成功响应，连接失败不代表已整改。")
        matches = [check for check in _rows(asset.get("checks")) if check.get("id") == check_id]
        if len(matches) != 1:
            return report("not_comparable", "没有唯一的相同规则结果，旧版或未采集字段不能作消失判定。")
        check = matches[0]
        identifiers = _ids(check, _evidence_map(retest_job["result"])) or _ids(asset, _evidence_map(retest_job["result"]))
        if not identifiers:
            return report("not_comparable", "复测响应缺少可回查证据。")
        if check.get("status") == "review":
            return report("still_observed", "相同 URL 和规则仍观察到待复核条件。", matches, identifiers)
        original_asset = _web_asset(original_job, url)
        if original_asset is None or original_asset.get("reachable") is not True:
            return report("not_comparable", "原始精确 URL 的成功采集依据不足，不能建立前后整改对应。", matches, identifiers)
        if group == "headers" and original_asset.get("headers_truncated"):
            return report("not_comparable", "原始响应头采集不完整，不能把两轮变化直接解释为整改。", matches, identifiers)
        if check_id.startswith("cookie_") and original_asset.get("cookies_truncated"):
            return report("not_comparable", "原始 Cookie 属性清单不完整，需取得完整对应资料后复核。", matches, identifiers)
        if group == "page" and (not original_asset.get("page", {}).get("analyzed") or original_asset.get("page", {}).get("truncated") or original_asset.get("body_truncated")):
            return report("not_comparable", "原始页面清单不完整，不能把缺口当作确定的整改基线。", matches, identifiers)
        proof = _mapping(check.get("evidence"))
        if asset.get("headers_truncated") and group == "headers" or proof.get("truncated_headers"):
            return report("not_comparable", "复测相关响应头采集不完整。", matches, identifiers)
        if check_id.startswith("cookie_") and asset.get("cookies_truncated"):
            return report("not_comparable", "复测 Cookie 属性清单不完整。", matches, identifiers)
        if group == "page" and (not asset.get("page", {}).get("analyzed") or asset.get("page", {}).get("truncated") or asset.get("body_truncated")):
            return report("not_comparable", "复测页面未解析完整，不能从不完整清单认定条件消失。", matches, identifiers)
        if check.get("status") == "pass":
            return report("not_observed_in_scope", "本次相同 URL 的该项规则满足检查条件；不是整体安全或可利用性结论。", matches, identifiers)
        return report("not_comparable", "复测规则为信息、不适用或未知状态，没有足够依据判断原条件已消失。", matches, identifiers)
    if selected["category"] == "cleartext_http" and locator.get("url"):
        if not _completed_group(original_job, "http") or not _completed_group(retest_job, "http"):
            return report("not_comparable", "至少一轮未完成 HTTP 响应检查。")
        asset = _web_asset(retest_job, locator["url"])
        if asset is None or asset.get("reachable") is not True or asset.get("redirect_stopped"):
            return report("not_comparable", "未取得同一精确 URL 的完整范围内响应。")
        identifiers = _ids(asset, _evidence_map(retest_job["result"]))
        final = _url(asset.get("final_url"))
        if identifiers and final.startswith("https://"):
            return report("not_observed_in_scope", "同一输入 URL 的本次响应已升级到 HTTPS；其他传输与应用条件仍需复核。", [asset], identifiers)
        if identifiers and final.startswith("http://"):
            return report("still_observed", "同一输入 URL 的最终响应仍使用 HTTP。", [asset], identifiers)
    return report("not_comparable", "该观察仅保留人工或外部报告依据，当前未实现可靠的自动对应判定。")
