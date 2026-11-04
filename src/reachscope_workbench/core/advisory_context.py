"""Minimized, deterministic evidence envelopes for optional model consultation.

Adapters consume saved domain data, never target HTML, credentials or instructions.
The registry is shared infrastructure; only website probes are implemented now.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .models import WorkbenchError

WEB_CHECKS = frozenset({"csp", "frame_protection", "nosniff", "referrer_policy", "hsts", "cors",
                        "cookie_secure", "cookie_http_only", "cookie_same_site", "tls_expiry",
                        "password_forms", "mixed_content"})
_STATES = {"pass", "review", "info", "not_applicable", "unknown"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class EvidenceAdapter(Protocol):
    module: str

    def build(self, job: dict[str, Any]) -> dict[str, Any]: ...


class WebEvidenceAdapter:
    module = "web"

    def build(self, job: dict[str, Any]) -> dict[str, Any]:
        snapshot = _mapping(job.get("asset_snapshot"))
        if (job.get("module") != "web" or job.get("status") != "completed" or not isinstance(job.get("result"), dict)
                or not job.get("asset_id") or snapshot.get("kind") != "website"
                or _mapping(job.get("config")).get("mode") != "probe"):
            raise WorkbenchError("AI_INPUT_UNSUPPORTED", "AI 试点需要已保存网站资产的真实 URL 检查；样例、导入和云服务归档不适用")
        return self._build_context(job)

    def _build_context(self, job: dict[str, Any]) -> dict[str, Any]:
        """Shared saved HTTP facts; callers enforce their distinct input policies."""
        snapshot = _mapping(job.get("asset_snapshot"))
        result = job["result"]
        if result.get("module", "web") != "web":
            raise WorkbenchError("AI_INPUT_UNSUPPORTED", "保存结果的模块身份与 HTTP 观察不一致")
        details = _mapping(result.get("details"))
        known = {row["id"] for row in _rows(result.get("evidence")) if isinstance(row.get("id"), str)}
        targets: list[dict[str, Any]] = []
        for index, row in enumerate(_rows(details.get("assets"))[:20], 1):
            try:
                parsed = urlsplit(row.get("url", ""))
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    continue
                # Even paths can contain reset tokens; send origin only. Local
                # report evidence keeps the exact URL for the operator.
                origin = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
            except (TypeError, ValueError):
                continue
            raw_ids = row.get("evidence_ids")
            ids = [value for value in raw_ids if isinstance(value, str) and value in known][:10] if isinstance(raw_ids, list) else []
            checks = [{"id": check["id"], "status": check["status"], "evidence_ids": ids}
                      for check in _rows(row.get("checks")) if isinstance(check.get("id"), str)
                      and isinstance(check.get("status"), str) and check["id"] in WEB_CHECKS and check["status"] in _STATES][:20]
            status = row.get("status_code")
            targets.append({"id": f"target-{index}", "url": origin, "reachable": row.get("reachable") is True,
                            "status_code": status if type(status) is int and 100 <= status <= 599 else None,
                            "evidence_ids": ids, "checks": checks,
                            "capture_complete": not bool(row.get("headers_truncated") or row.get("body_truncated")
                                                         or row.get("cookies_truncated"))})
        if not targets or not any(row["reachable"] and row["evidence_ids"] for row in targets):
            raise WorkbenchError("AI_EVIDENCE_REQUIRED", "至少需要一个成功采集且有证据的网站响应；请求失败不能代替安全结论")
        execution = [{"id": row["id"], "status": row["status"]}
                     for row in _rows(details.get("execution")) if isinstance(row.get("id"), str)
                     and isinstance(row.get("status"), str) and row["id"] in {"http", "headers", "page", "fingerprints"}
                     and row.get("status") in {"completed", "skipped"}]
        provenance = _mapping(snapshot.get("provenance"))
        origin_kind = "local_training" if provenance.get("kind") == "local_training" else "probe"
        context = {"schema_version": "ai-evidence/1", "module": "web", "origin": origin_kind,
                   "job_id": job["id"], "asset_id": job["asset_id"], "targets": targets,
                   "evidence_ids": sorted({value for row in targets for value in row["evidence_ids"]}),
                   "execution": execution,
                   "limitations": ["Only saved configuration observations; no exploit, business authorization or runtime access-control test.",
                                   "Only origins are shared. Paths, query strings, page content and credentials are excluded.",
                                   "Unexecuted or incomplete checks remain unknown; missing headers are not confirmed vulnerabilities."]}
        if len(canonical(context).encode("utf-8")) > 64 * 1024:
            raise WorkbenchError("AI_CONTEXT_LIMIT", "研判摘要超过 64 KiB 预算")
        return context


class HttpGuideEvidenceAdapter(WebEvidenceAdapter):
    """Local deterministic guides only; never registered as a paid AI adapter."""

    def build(self, job: dict[str, Any]) -> dict[str, Any]:
        snapshot = _mapping(job.get("asset_snapshot"))
        source = _mapping(snapshot.get("source"))
        cloud_service = snapshot.get("kind") == "cloud" and source.get("profile_id") == "cloud-external"
        if (job.get("module") != "web" or job.get("status") != "completed"
                or not isinstance(job.get("result"), dict) or not job.get("asset_id")
                or _mapping(job.get("config")).get("mode") != "probe"
                or not (snapshot.get("kind") == "website" or cloud_service)):
            raise WorkbenchError("GUIDE_INPUT_UNSUPPORTED", "指南需要保存的网站或云服务 HTTP(S) 实际观察；离线配置、样例与导入不适用")
        context = self._build_context(job)
        if cloud_service:
            context["origin"] = "cloud_service_probe"
            context["limitations"].append("云服务指南仅针对该 HTTP(S) 响应；未连接云账号、判断安全组生效或求值 IAM 权限。")
        return context


class ContextRegistry:
    def __init__(self, adapters: list[EvidenceAdapter] | None = None) -> None:
        self.adapters = {adapter.module: adapter for adapter in adapters or [WebEvidenceAdapter()]}

    def build(self, job: dict[str, Any]) -> dict[str, Any]:
        adapter = self.adapters.get(job.get("module", ""))
        if adapter is None:
            raise WorkbenchError("AI_INPUT_UNSUPPORTED", "该模块尚未实现证据最小化适配；当前仅开放网站 URL 试点")
        return adapter.build(job)
