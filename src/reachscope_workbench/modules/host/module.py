"""Host adapter over local, bounded exports; no remote execution or remediation."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from ...core.models import (
    Evidence,
    ModuleResult,
    ModuleSpec,
    Observation,
    RunContext,
    WorkbenchError,
)
from ...core.uploads import read_upload
from .demo import access_bytes, auth_bytes, baseline_bytes

MAX_BYTES = 2 * 1024 * 1024
GROUPS = {"ssh": "SSH 配置基线", "nginx": "Nginx 配置基线", "web_logs": "Web 访问日志", "auth_logs": "SSH 认证日志"}
MODE_CHECKS = {"baseline": ("ssh", "nginx"), "access_log": ("web_logs",), "auth_log": ("auth_logs",), "demo": tuple(GROUPS)}
_UPLOAD = re.compile(r"[a-f0-9]{32}\Z")


def _host_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise WorkbenchError("INVALID_CONFIG", "主机标识须为 1–128 个无控制字符的稳定名称，不能包含首尾空格")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise WorkbenchError("INVALID_CONFIG", "主机标识包含无效 Unicode 字符") from exc
    return value


def _input(uploads: Path, upload_id: str) -> bytes:
    path = uploads / upload_id
    if path.is_symlink() or not path.is_file() or path.resolve().parent != uploads.resolve():
        raise WorkbenchError("UPLOAD_NOT_FOUND", "主机输入不存在或路径无效，请重新上传")
    return read_upload(path, max_bytes=MAX_BYTES,
                       missing_message="无法读取主机输入文件",
                       limit_code="HOST_INPUT_LIMIT",
                       limit_message="主机资料须为非空且不超过 2 MiB 的文件", require_nonempty=True)


class HostModule:
    spec = ModuleSpec(id="host", name="主机防御", description="离线配置基线与有限日志线索，保留未知项和证据",
                      capabilities=["host_baseline", "bounded_log_review", "field_evidence", "manual_remediation", "selective_checks"],
                      input_modes=list(MODE_CHECKS))

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = config.get("mode", "demo")
        if not isinstance(mode, str) or mode not in MODE_CHECKS:
            raise WorkbenchError("INVALID_CONFIG", "请选择主机配置、Web 日志、SSH 日志或合成样例")
        if config.keys() - {"mode", "checks", "host_id", "upload_id", "filename"}:
            raise WorkbenchError("INVALID_CONFIG", "主机检查包含不支持的设置")
        selected = config.get("checks", list(MODE_CHECKS[mode]))
        if (not isinstance(selected, list) or not 1 <= len(selected) <= len(GROUPS)
                or any(not isinstance(item, str) or item not in MODE_CHECKS[mode] for item in selected)):
            raise WorkbenchError("INVALID_CONFIG", "检查项目与所选主机资料不匹配")
        host_id = _host_id(config.get("host_id", "demo-host-01" if mode == "demo" else None))
        clean: dict[str, Any] = {"mode": mode, "host_id": host_id, "checks": [item for item in GROUPS if item in selected]}
        if mode != "demo":
            upload_id, filename = config.get("upload_id"), config.get("filename")
            if not isinstance(upload_id, str) or not _UPLOAD.fullmatch(upload_id):
                raise WorkbenchError("INVALID_CONFIG", "主机资料需要有效的上传文件 ID")
            extensions = {".json"} if mode == "baseline" else {".log", ".txt"}
            if not isinstance(filename, str) or len(filename) > 255 or Path(filename).suffix.lower() not in extensions:
                raise WorkbenchError("INVALID_CONFIG", "配置使用 .json 文件，日志使用 .log 或 .txt 文件")
            clean.update(upload_id=upload_id, filename=Path(filename.replace("\\", "/")).name)
        return clean

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        clean = self.validate(config)
        context.progress(10, "读取本地主机资料；不连接目标或修改配置")
        raw = None if clean["mode"] == "demo" else await asyncio.to_thread(_input, context.uploads, clean["upload_id"])
        result = await asyncio.to_thread(self._analyze, clean, raw)
        context.progress(100, "主机防御复核完成；线索仍需人工确认")
        return result

    def preview(self, config: dict[str, Any], uploads: Path) -> dict[str, Any]:
        """Parse local input only; never run checks or create task evidence."""
        from .input import parse_baseline, preview_baseline
        from .logs import preview_logs

        clean = self.validate(config)
        mode, host_id = clean["mode"], clean["host_id"]
        collection_metadata: dict[str, Any] = {}
        if mode == "demo":
            raw = baseline_bytes(host_id)
            coverage = {"source": "synthetic_demo", "selected_groups": clean["checks"], "baseline": True, "logs": True}
        else:
            raw = _input(uploads, clean["upload_id"])
            if mode == "baseline":
                parsed = parse_baseline(raw, host_id)
                preview = preview_baseline(parsed, clean["checks"])
                coverage = {"components": preview["components"], "collection_state": preview["collection_state"],
                            "collected_at": parsed["collected_at"]}
                if "collection_metadata" in parsed:
                    collection_metadata = parsed["collection_metadata"]
            else:
                coverage = preview_logs(raw, mode, host_id)["coverage"]
        return {"version": 1, "module": "host", "host_id": host_id, "input_kind": mode,
                "sha256": hashlib.sha256(raw).hexdigest(), "coverage": coverage,
                "analysis_executed": False, "network_requests": False,
                **({"collection_metadata": collection_metadata} if collection_metadata else {}),
                "limitations": ["这是本地资料解析预览，未执行检查、创建证据或验证主机当前状态。", "上传原文件仍保存在本机；结果脱敏不能替代对原文件的访问保护。"]}

    @staticmethod
    def _analyze(config: dict[str, Any], raw: bytes | None) -> ModuleResult:
        from .baseline import assess_baseline
        from .input import parse_baseline
        from .logs import assess_logs

        mode, host_id, selected = config["mode"], config["host_id"], config["checks"]
        parts: list[dict[str, Any]] = []
        if mode in {"demo", "baseline"} and any(group in selected for group in ("ssh", "nginx")):
            data = parse_baseline(baseline_bytes(host_id) if mode == "demo" else raw or b"", host_id)
            if mode == "demo":
                data["source_kind"] = "synthetic_demo"
            parts.append(assess_baseline(data, [group for group in selected if group in {"ssh", "nginx"}]))
        for kind, group, fixture in (("access_log", "web_logs", access_bytes), ("auth_log", "auth_logs", auth_bytes)):
            if mode in {"demo", kind} and group in selected:
                parts.append(assess_logs(fixture() if mode == "demo" else raw or b"", kind, host_id,
                                         source_kind="synthetic_demo" if mode == "demo" else "operator_supplied_log"))
        checks = [check for part in parts for check in part.get("checks", [])]
        evidence = [Evidence(**item) for part in parts for item in part.get("evidence", [])]
        known = {item.id for item in evidence}
        if any(not set(check.get("evidence_ids", [])).issubset(known) for check in checks):
            raise WorkbenchError("HOST_EVIDENCE_INVALID", "主机检查缺少对应的保存证据")
        observations = [Observation(id="host-review:" + str(index), title=check["title"], severity=check.get("severity", "info"),
                                    category="host_configuration" if str(check["id"]).startswith(("host.ssh.", "host.nginx.")) else "host_log_indicator",
                                    description=check["description"], evidence_ids=check["evidence_ids"],
                                    confidence="static_config" if str(check["id"]).startswith(("host.ssh.", "host.nginx.")) else "log_indicator",
                                    recommendation=check["recommendation"])
                        for index, check in enumerate(checks) if check.get("status") == "review"]
        origin = "synthetic_demo" if mode == "demo" else "operator_supplied_export" if mode == "baseline" else "operator_supplied_log"
        collection_metadata = next((part["coverage"]["collection_metadata"] for part in parts
                                    if "collection_metadata" in part.get("coverage", {})), None)
        return ModuleResult(module="host", target=host_id,
                            summary={"host_id": host_id, "checks": len(checks), "review_checks": sum(c["status"] == "review" for c in checks),
                                     "unknown_checks": sum(c["status"] == "unknown" for c in checks), "log_events": sum(len(p.get("log_events", [])) for p in parts)},
                            evidence=evidence, observations=observations,
                            details={"review_version": 1, "host_id": host_id, "input_kind": mode, "origin": origin,
                                     **({"collection_metadata": collection_metadata} if collection_metadata is not None else {}),
                                     "checks": checks, "coverage": [part.get("coverage", {}) for part in parts],
                                     "collection": next(({"collected_at": part["coverage"].get("collected_at"),
                                                          "collection_state": part["coverage"].get("collection_state")}
                                                         for part in parts if "collection_state" in part.get("coverage", {})), {}),
                                     "log_events": [event for part in parts for event in part.get("log_events", [])],
                                     "rule_parameters": [part.get("rule_parameters", {}) for part in parts if part.get("rule_parameters")],
                                     "execution": [{"id": key, "label": label, "status": "completed" if key in selected else "skipped",
                                                    "reason": "已复核提供的离线资料；未知项仍保留" if key in selected else "本次未选择，未执行该组检查"} for key, label in GROUPS.items()],
                                     "live_state_verified": False},
                            limitations=["仅处理操作员提供的离线资料，不证明配置已部署、主机被入侵或运行时防护有效。",
                                         "有限日志中的规则命中是复核线索，未命中不能证明整改成功或没有攻击。",
                                         "输入文件可能含敏感内容并保存在本地；结果仅保存规则所需的脱敏字段。",
                                         *dict.fromkeys(text for part in parts for text in part.get("limitations", []))])
