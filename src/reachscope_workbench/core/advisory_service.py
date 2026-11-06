"""Optional model consultation lifecycle over minimized saved evidence.

Paid provider calls are opt-in, bounded and never replayed automatically. Model
output is an advisory selection, not an executable plan or a case state mutation.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from uuid import uuid4

from .advisory_context import ContextRegistry, HttpGuideEvidenceAdapter, canonical, digest
from .advisory_repository import AdvisoryRepository
from .ai_contracts import AdvisoryProvider, validate_selection
from .ai_providers import infer_provider, preset, presets
from .defense_catalog import catalog, implementation_guide
from .models import WorkbenchError
from .repository import JobRepository

logger = logging.getLogger(__name__)
_LIMITATIONS = [
    "AI 仅从公开归因的控制目录中选择与排序，不能证明漏洞、执行测试或修改整改状态。",
    "红队输出是授权人工核查方向；蓝队输出是人工配置与流程建议，需要结合真实环境复核。",
    "网页内容、导入文件和模型响应都是数据，不具备指挥工具、扩大范围或更改权限的效力。",
    "当前仅有网站真实 URL 观察的证据适配；Android 和云模块尚未接入 AI 研判。",
    "模型服务可能计费或保留数据；请求不自动重试，未完成记录不代表服务商未计费。",
]
_DISCLOSURE = {"fields": ["任务与证据标识", "URL 源站（不含路径）", "HTTP 状态与可达性", "检查 ID/状态与采集完整性", "控制目录 ID/适用性"],
               "excluded": ["URL 路径/查询/片段", "页面正文/标题/脚本", "Cookie/Authorization 及响应头原始值", "表单值/上传文件/源码", "API 密钥与人工授权说明"]}


class AdvisoryService:
    def __init__(self, jobs: JobRepository, provider: AdvisoryProvider, contexts: ContextRegistry | None = None) -> None:
        self.jobs, self.provider = jobs, provider
        self.records = AdvisoryRepository(jobs)
        self.contexts = contexts or ContextRegistry()
        self.settings = self.records.settings() or {"enabled": False, "provider_id": "openai_compatible",
                                                    "base_url": "https://api.openai.com/v1", "model": "",
                                                    "reasoning_effort": "default", "allow_local": False, "revision": uuid4().hex}
        self.settings.setdefault("provider_id", infer_provider(str(self.settings.get("base_url", ""))))
        self.settings.setdefault("reasoning_effort", "default")
        self.settings.setdefault("token_limit_field", preset(str(self.settings["provider_id"]))["token_limit_field"])
        self.environment_key = os.environ.get("REACHSCOPE_AI_API_KEY", "")
        self.environment_scope = self._credential_scope(self.settings)
        blocked = self.settings.get("_environment_blocked_scopes", [])
        self.environment_blocked_scopes: set[tuple[str, str]] = {
            (str(item[0]), str(item[1])) for item in blocked
            if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(part, str) for part in item)
        } if isinstance(blocked, list) else set()
        self.session_key = ""
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.lock = asyncio.Lock()
        self.started = False

    async def start(self) -> None:
        async with self.lock:
            if not self.started:
                await asyncio.to_thread(self.records.recover)
                self.started = True

    async def stop(self) -> None:
        # Wait for any durable acceptance/configuration before taking the task
        # snapshot, so shutdown cannot miss a just-accepted model operation.
        async with self.lock:
            self.started = False
            pending = list(self.tasks.values())
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self.tasks.clear()
            await asyncio.to_thread(self.records.recover)
            self.session_key = ""

    @staticmethod
    def _credential_scope(settings: dict[str, Any]) -> tuple[str, str]:
        return str(settings["provider_id"]), str(settings["base_url"])

    def credential(self) -> tuple[str, str]:
        if self.session_key:
            return self.session_key, "session"
        current_scope = self._credential_scope(self.settings)
        value = self.environment_key if (
            self.environment_scope == current_scope and current_scope not in self.environment_blocked_scopes
        ) else ""
        return (value, "environment") if value else ("", "missing")

    def config(self) -> dict[str, Any]:
        key, origin = self.credential()
        provider_id = str(self.settings.get("provider_id") or infer_provider(str(self.settings.get("base_url", ""))))
        label = next((item["label"] for item in presets() if item["id"] == provider_id), "自定义兼容接口")
        current_scope = self._credential_scope(self.settings)
        environment_blocked = bool(self.environment_key) and (
            self.environment_scope != current_scope or current_scope in self.environment_blocked_scopes
        )
        blocked_reason = None
        if environment_blocked:
            blocked_reason = ("环境凭据已对当前服务配置禁用" if current_scope in self.environment_blocked_scopes
                              else "环境凭据仅适用于原服务地址")
        return {**{key: value for key, value in self.settings.items() if not key.startswith("_") and key != "revision"},
                "provider_id": provider_id, "provider_label": label, "configuration_sha256": digest(self.settings),
                "has_key": bool(key), "credential_source": origin, "environment_blocked": environment_blocked,
                "environment_blocked_reason": blocked_reason, "timeout": 45,
                "capabilities": {"web": True, "android": False, "cloud": False, "host": False}, "limitations": list(_LIMITATIONS)}

    async def configure(self, settings: dict[str, Any], *, key: str | None = None, clear_key: bool = False) -> dict[str, Any]:
        # Endpoint syntax/network policy is validated by the HTTP adapter before
        # this provider-neutral use case. No secret can enter durable settings.
        async with self.lock:
            provider_id = str(settings.get("provider_id") or infer_provider(str(settings["base_url"])))
            preset(provider_id)
            clean = {name: settings[name] for name in ("enabled", "base_url", "model", "reasoning_effort", "allow_local")}
            clean["provider_id"] = provider_id
            clean["token_limit_field"] = settings.get("token_limit_field") or preset(provider_id)["token_limit_field"]
            clean["revision"] = uuid4().hex
            changed_scope = self._credential_scope(clean) != self._credential_scope(self.settings)
            new_scope = self._credential_scope(clean)
            next_blocked_scopes = set(self.environment_blocked_scopes)
            if clear_key or (changed_scope and new_scope != self.environment_scope):
                next_blocked_scopes.add(new_scope)
            clean["_environment_blocked_scopes"] = [list(scope) for scope in sorted(next_blocked_scopes)]
            operation = asyncio.create_task(asyncio.to_thread(self.records.save_settings, clean))
            cancelled = False
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                cancelled = True
            self.settings = clean
            if clear_key or changed_scope:
                self.session_key = ""
            self.environment_blocked_scopes = next_blocked_scopes
            if key and not clear_key:
                self.session_key = key
            if cancelled:
                raise asyncio.CancelledError
        return self.config()

    def provider_presets(self) -> list[dict[str, Any]]:
        return presets()

    async def model_diagnostic_snapshot(self, configuration_sha256: str, consent: bool) -> tuple[dict[str, Any], str]:
        """Bind explicit credential use to the exact saved non-secret revision."""
        if not consent:
            raise WorkbenchError("AI_CONSENT_REQUIRED", "请确认仅向已保存服务商发送凭据并读取模型目录；不会调用模型")
        async with self.lock:
            if configuration_sha256 != digest(self.settings):
                raise WorkbenchError("AI_PREVIEW_STALE", "已保存设置已经变化，请刷新配置后重新确认诊断")
            secret, _origin = self.credential()
            if not secret:
                raise WorkbenchError("AI_NOT_CONFIGURED", "当前已保存服务商没有可用凭据；请先保存对应密钥")
            return dict(self.settings), secret

    async def control_guide(self, report_id: str, control_id: str, environment: str) -> dict[str, Any]:
        report = await asyncio.to_thread(self.records.get, report_id)
        if report["status"] != "completed":
            raise WorkbenchError("AI_GUIDE_UNAVAILABLE", "仅已完成研判中的已选控制项可关联人工实施指南")
        selected = [row for perspective in ("red", "blue") for row in report.get(perspective, [])
                    if isinstance(row, dict) and row.get("control_id") == control_id]
        control = next((row for row in catalog() if row["id"] == control_id), None)
        if not selected or control is None:
            raise WorkbenchError("AI_CONTROL_NOT_FOUND", "当前报告没有该控制项")
        guide = implementation_guide(control_id, environment)
        context = report["context"]
        known = set(context["evidence_ids"])
        evidence_ids = sorted({item for row in selected for item in row["evidence_ids"] if item in known})
        statuses = [{"check_id": check["id"], "status": check["status"],
                     "evidence_ids": [item for item in check["evidence_ids"] if item in evidence_ids]}
                    for target in context["targets"] for check in target["checks"]
                    if check["id"] in control["signals"] and set(check["evidence_ids"]) & set(evidence_ids)]
        return {**guide, "report_id": report_id, "job_id": report["job_id"], "origin": context.get("origin", "probe"),
                "source_kind": "ai_report", "evidence_ids": evidence_ids, "signal_statuses": statuses}

    async def job_controls(self, job_id: str) -> dict[str, Any]:
        job = await asyncio.to_thread(self.jobs.get, job_id)
        try:
            context = HttpGuideEvidenceAdapter().build(job)
        except WorkbenchError as exc:
            raise WorkbenchError("GUIDE_INPUT_UNSUPPORTED", "实施指南需要成功采集且有已知证据的已保存网站或云服务 HTTP(S) 检查；样例、导入和离线云配置不适用") from exc
        executed = {row["id"] for row in context["execution"] if row["status"] == "completed"}
        items = []
        for control in catalog():
            if control["applicability"] != "web_config":
                continue
            statuses = [{"check_id": check["id"], "status": check["status"], "evidence_ids": list(check["evidence_ids"])}
                        for target in context["targets"] if target["reachable"] for check in target["checks"]
                        if check["id"] in control["signals"] and check["evidence_ids"]
                        and ("page" if check["id"] in {"password_forms", "mixed_content"} else "headers") in executed]
            if statuses:
                items.append({"control_id": control["id"], "title": control["title"], "category": control["category"],
                              "states": sorted({row["status"] for row in statuses}),
                              "evidence_ids": sorted({item for row in statuses for item in row["evidence_ids"]}),
                              "signal_statuses": statuses})
        return {"job_id": job_id, "origin": context["origin"], "source_kind": "deterministic_saved_evidence", "ai_required": False,
                "items": items, "limitations": ["只列出已执行规则且有已知证据的配置控制；不是新增发现，也不需要 AI。",
                                                  "通过表示保留验证，未知表示补充采集；未执行、未知或采集失败不能说明问题或整改完成。",
                                                  *(["云服务记录仅包含外部 HTTP(S) 观察，不代表云账号配置、IAM 权限或整体公网暴露面已评估。"]
                                                    if context["origin"] == "cloud_service_probe" else [])]}

    async def job_control_guide(self, job_id: str, control_id: str, environment: str) -> dict[str, Any]:
        available = await self.job_controls(job_id)
        control = next((row for row in available["items"] if row["control_id"] == control_id), None)
        if control is None:
            raise WorkbenchError("GUIDE_CONTROL_NOT_FOUND", "当前任务没有该控制项的已执行规则和已知证据")
        guide = implementation_guide(control_id, environment)
        return {**guide, "job_id": job_id, "origin": available["origin"], "source_kind": available["source_kind"],
                "states": control["states"], "evidence_ids": control["evidence_ids"], "signal_statuses": control["signal_statuses"],
                "preconditions": guide["preconditions"] + ["先区分关联检查状态：通过时保持并验证；review 需业务复核；未知时先补采集，不直接变更配置。"],
                "limitations": guide["limitations"] + available["limitations"]}

    async def preview(self, job_id: str) -> dict[str, Any]:
        job = await asyncio.to_thread(self.jobs.get, job_id)
        controls = catalog()
        provider = self.config()
        context: dict[str, Any] = {}
        reason, eligible = "", True
        try:
            context = self.contexts.build(job)
        except WorkbenchError as exc:
            reason, eligible = exc.message, False
        envelope = {"context": context, "provider": {key: self.settings[key] for key in ("provider_id", "base_url", "model", "reasoning_effort", "token_limit_field", "allow_local", "revision")},
                    "catalog_sha256": digest(controls)}
        return {"job_id": job_id, "module": job["module"], "eligible": eligible, "reason": reason,
                "context": context, "context_sha256": digest(envelope), "provider": provider, "controls": controls,
                "disclosure": {**_DISCLOSURE, "bytes": len(canonical(context).encode("utf-8"))},
                "reports": (await asyncio.to_thread(self.records.list, job_id))["items"], "limitations": list(_LIMITATIONS)}

    async def submit(self, job_id: str, context_sha256: str, consent: bool, authorization_note: str, key: str) -> dict[str, Any]:
        if not consent or not authorization_note.strip():
            raise WorkbenchError("AI_CONSENT_REQUIRED", "请确认向指定服务商发送预览摘要，并填写授权核查范围")
        fingerprint = digest({"job_id": job_id, "context_sha256": context_sha256, "authorization_note": authorization_note.strip()})
        async with self.lock:
            replay = await asyncio.to_thread(self.records.replay, key, fingerprint)
            if replay is not None:
                return replay
            if not self.started:
                raise WorkbenchError("AI_UNAVAILABLE", "研判服务尚未启动或正在关闭")
            preview = await self.preview(job_id)
            if not preview["eligible"]:
                raise WorkbenchError("AI_INPUT_UNSUPPORTED", preview["reason"])
            if preview["context_sha256"] != context_sha256:
                raise WorkbenchError("AI_PREVIEW_STALE", "输入或模型设置已变化，请重新查看摘要并确认")
            secret, _origin = self.credential()
            if not self.settings["enabled"] or not self.settings["model"] or not secret:
                raise WorkbenchError("AI_NOT_CONFIGURED", "请先启用并填写模型、API 基址与密钥；不会使用演示结果代替真实调用")
            if len(self.tasks) >= 2:
                raise WorkbenchError("AI_BUSY", "同时最多两个研判请求；请等待现有任务结束")
            report = {"module": "web", "mode": "ai_api", "provider": {name: self.settings[name] for name in ("provider_id", "base_url", "model", "reasoning_effort", "token_limit_field")},
                      "context_sha256": context_sha256, "context": preview["context"], "disclosure": preview["disclosure"],
                      "authorization_note": authorization_note.strip(), "red": [], "blue": [], "usage": {}, "error": None,
                      "limitations": list(_LIMITATIONS)}
            # Shield durable acceptance from client disconnects. If cancellation
            # races this write, finish acceptance and launch exactly one task.
            reservation = asyncio.create_task(asyncio.to_thread(self.records.reserve, job_id, key, fingerprint, report))
            cancelled = False
            try:
                accepted = await asyncio.shield(reservation)
            except asyncio.CancelledError:
                accepted = await reservation
                cancelled = True
            if accepted["status"] == "running" and accepted["id"] not in self.tasks:
                task = asyncio.create_task(self._run(accepted["id"], dict(self.settings), secret, preview["context"], preview["controls"]))
                self.tasks[accepted["id"]] = task
                task.add_done_callback(self._forget_task)
            if cancelled:
                raise asyncio.CancelledError
            return accepted

    def _forget_task(self, task: asyncio.Task[None]) -> None:
        for identifier, current in list(self.tasks.items()):
            if current is task:
                self.tasks.pop(identifier, None)
                break

    async def _run(self, identifier: str, settings: dict[str, Any], secret: str, context: dict[str, Any], controls: list[dict[str, Any]]) -> None:
        try:
            response = await self.provider.consult(settings, secret, context, controls)
            selections = validate_selection(response["selection"], controls, context)
            await asyncio.to_thread(self.records.finish, identifier, "completed", {**selections, "usage": response.get("usage", {})})
        except asyncio.CancelledError:
            await asyncio.to_thread(self.records.finish, identifier, "interrupted", {
                "error": {"code": "AI_INTERRUPTED", "message": "本地服务关闭；无法确认服务商处理状态，不会自动重试"}})
            raise
        except WorkbenchError as exc:
            await asyncio.to_thread(self.records.finish, identifier, "failed", {"error": {"code": exc.code, "message": exc.message}})
        except Exception as exc:  # noqa: BLE001 -- final durable task boundary; keep raw provider errors private.
            # Never log an exception's repr: a provider exception could carry a
            # credential or target body. Preserve only the type for diagnosis.
            logger.error("advisory_failed report_id=%s type=%s", identifier, type(exc).__name__)
            await asyncio.to_thread(self.records.finish, identifier, "failed", {"error": {
                "code": "AI_FAILED", "message": "研判处理失败；原始模型文本未显示，不会自动重复调用"}})
