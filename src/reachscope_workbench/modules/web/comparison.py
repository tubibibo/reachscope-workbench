"""Compare saved Web observations without making network requests or safety claims."""

from __future__ import annotations

import json
from typing import Any

from ...core.models import WorkbenchError
from .scope import normalize_url

# These headers have been captured since Workbench 0.5. New collectors must not
# interpret an older collector's missing fields as a server configuration change.
_HEADERS = (
    "server", "content-type", "content-length", "location", "strict-transport-security",
    "content-security-policy", "x-content-type-options", "x-frame-options",
    "referrer-policy", "permissions-policy", "cache-control", "x-powered-by",
)
_SCALARS = ("reachable", "status_code", "title", "server", "ip", "content_type", "final_url")


def _inventory(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if job.get("status") != "completed" or not isinstance(job.get("result"), dict):
        raise WorkbenchError("RESULT_UNAVAILABLE", "比较需要两个已完成的任务")
    result = job["result"]
    if job.get("module") != "web" or result.get("module") != "web":
        raise WorkbenchError("MODULE_MISMATCH", "历史对比只适用于 Web 任务")
    if result.get("summary", {}).get("mode") != "probe":
        raise WorkbenchError("COMPARE_MODE_UNSUPPORTED", "只能比较实际 URL 探测；导入或离线样例不代表本次站点状态")
    assets = result.get("details", {}).get("assets")
    if not isinstance(assets, list) or len(assets) > 20:
        raise WorkbenchError("INVALID_RESULT", "已保存的 Web 探测资产结构不符合比较合同")
    inventory: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("url"), str):
            raise WorkbenchError("INVALID_RESULT", "已保存的资产缺少 URL")
        url = normalize_url(asset["url"])
        if url in inventory:
            raise WorkbenchError("INVALID_RESULT", "已保存的探测包含重复 URL，无法唯一对齐")
        inventory[url] = asset
    return inventory


def _ids(asset: dict[str, Any] | None) -> list[str]:
    return [value for value in (asset or {}).get("evidence_ids", []) if isinstance(value, str)]


def _check_statuses(asset: dict[str, Any]) -> dict[str, str]:
    return {item["id"]: item["status"] for item in asset.get("checks", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("status"), str)}


def _cookie_view(asset: dict[str, Any]) -> list[dict[str, Any]]:
    # Deliberate allowlist: neither future raw headers nor cookie values belong
    # in a configuration diff. Ordering alone is not a configuration change.
    fields = ("name", "domain", "path", "secure", "http_only", "same_site", "partitioned", "prefix")
    rows = [{key: item[key] for key in fields if key in item}
            for item in asset.get("cookies", []) if isinstance(item, dict)]
    return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True))


def _changes(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    changes: list[dict[str, Any]] = []
    notes: list[str] = []

    def add(field: str, old: Any, new: Any) -> None:
        if old != new:
            changes.append({"field": field, "before": old, "after": new})

    old_scope = set(before.get("selected_checks", ["http", "headers", "page", "fingerprints"]))
    new_scope = set(after.get("selected_checks", ["http", "headers", "page", "fingerprints"]))
    if old_scope != new_scope:
        notes.append("两轮选择的检查项不同；只比较共同执行的采集字段。")
    for field in _SCALARS:
        if field == "title" and (not old_scope & {"page", "fingerprints"} or not new_scope & {"page", "fingerprints"}):
            continue
        if field in before and field in after:
            add(field, before[field], after[field])
    if not before.get("reachable") or not after.get("reachable"):
        notes.append("至少一轮未取得响应；连接状态变化不能用于判断配置改善或漏洞修复。")
        return changes, notes
    clipped_headers = set(before.get("headers_truncated", [])) | set(after.get("headers_truncated", []))
    for asset in (before, after):
        if asset.get("capture_schema") != "web-response/2":
            clipped_headers.update(name for name, value in asset.get("headers", {}).items() if len(value) >= 4096)
    for header in _HEADERS:
        if header not in {"server", "content-type", "content-length", "location"} and not {"headers"} <= old_scope & new_scope:
            continue
        if header not in clipped_headers:
            add("headers." + header, before.get("headers", {}).get(header), after.get("headers", {}).get(header))
    if clipped_headers:
        notes.append("响应头达到采集上限；这些字段未比较：" + ", ".join(sorted(clipped_headers)))
    old_redirects = [{key: row.get(key) for key in ("from", "to", "status_code")}
                     for row in before.get("redirects", [])]
    new_redirects = [{key: row.get(key) for key in ("from", "to", "status_code")}
                     for row in after.get("redirects", [])]
    add("redirects", old_redirects, new_redirects)
    comparable_body = (
        before.get("body_sha256") and after.get("body_sha256")
        and before.get("hash_scope") == after.get("hash_scope") == "captured_body"
        and not before.get("body_truncated") and not after.get("body_truncated")
        and before.get("content_encoding", "identity") == after.get("content_encoding", "identity")
    )
    if comparable_body:
        add("body_sha256", before["body_sha256"], after["body_sha256"])
    else:
        notes.append("正文未完整采集、编码不同或缺少摘要，未比较正文哈希。")
    if "tls" in before and "tls" in after:
        for key in ("version", "cipher", "not_after", "subject_alt_names"):
            old, new = (before.get("tls") or {}).get(key), (after.get("tls") or {}).get(key)
            if key == "subject_alt_names":
                old, new = sorted(old or []), sorted(new or [])
            add("tls." + key, old, new)
    if "checks" in before and "checks" in after:
        old_checks, new_checks = _check_statuses(before), _check_statuses(after)
        for key in sorted(old_checks.keys() & new_checks.keys()):
            add("checks." + key, old_checks[key], new_checks[key])
        if old_checks.keys() != new_checks.keys():
            notes.append("两轮检查规则集合不同；只比较共同规则，未把新增规则当成站点变化。")
    else:
        notes.append("旧记录未提供结构化检查；该部分未比较。")
    if "cookies" in before and "cookies" in after:
        if before.get("cookies_truncated") or after.get("cookies_truncated"):
            notes.append("Cookie 属性采集不完整；未比较 Cookie 清单。")
        else:
            add("cookies", _cookie_view(before), _cookie_view(after))
    else:
        notes.append("旧记录未提供无值 Cookie 元数据；该部分未比较。")
    old_page, new_page = before.get("page", {}), after.get("page", {})
    if old_page.get("analyzed") and new_page.get("analyzed"):
        for key in ("language", "description", "canonical"):
            if key in old_page and key in new_page:
                add("page." + key, old_page[key], new_page[key])
        if not old_page.get("truncated") and not new_page.get("truncated"):
            if "counts" in old_page and "counts" in new_page:
                add("page.counts", old_page["counts"], new_page["counts"])
            if "forms" in old_page and "forms" in new_page:
                def forms(page: dict[str, Any]) -> list[dict[str, Any]]:
                    fields = ("action", "method", "password_fields", "input_names")
                    return [{field: row.get(field) for field in fields} for row in page["forms"]]
                add("page.forms", forms(old_page), forms(new_page))
        for key in ("scripts", "stylesheets", "links", "images"):
            if key in old_page and key in new_page and not old_page.get("truncated") and not new_page.get("truncated"):
                add("page." + key, sorted(str(row.get("url", "")) for row in old_page[key]),
                    sorted(str(row.get("url", "")) for row in new_page[key]))
        if old_page.get("truncated") or new_page.get("truncated"):
            notes.append("页面采集或清单达到上限；资源清单未按完整集合比较。")
    else:
        notes.append("至少一轮未解析 HTML 页面画像；该部分未比较。")
    return changes, notes


def compare_jobs(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Align exact normalized input URLs. This function never modifies either job."""
    if baseline.get("id") == current.get("id"):
        raise WorkbenchError("INVALID_COMPARISON", "请选择另一个已完成任务作为基线")
    before, after = _inventory(baseline), _inventory(current)
    summary = dict.fromkeys(("added", "removed", "changed", "unchanged", "not_comparable"), 0)
    rows = []
    for url in sorted(before.keys() | after.keys()):
        old, new = before.get(url), after.get(url)
        changes, notes = _changes(old, new) if old is not None and new is not None else ([], [])
        status = (
            "added" if old is None else "removed" if new is None
            else "not_comparable" if not old.get("reachable") or not new.get("reachable")
            else "changed" if changes else "unchanged"
        )
        summary[status] += 1
        rows.append({"url": url, "status": status, "changes": changes, "notes": notes,
                     "before_evidence_ids": _ids(old), "after_evidence_ids": _ids(new)})
    metadata = ("id", "name", "created_at")
    return {
        "baseline_job_id": baseline["id"], "current_job_id": current["id"],
        "baseline": {key: baseline.get(key) for key in metadata},
        "current": {key: current.get(key) for key in metadata},
        "summary": summary, "assets": rows,
        "limitations": [
            "对比只读取保存的结果，不发送新请求；响应变化也可能来自动态内容、负载均衡或采集时间。",
            "新增/移除表示两个任务的输入 URL 集合变化，不表示站点上线或下线。",
            "未变化只表示共同采集字段未变化；新旧采集版本不一致或字段被截断时可能有未比较部分。",
            "配置检查的状态变化不是整体安全性或漏洞修复结论。",
        ],
    }
