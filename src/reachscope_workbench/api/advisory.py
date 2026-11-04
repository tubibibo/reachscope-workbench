"""Local opt-in consultation commands; no raw model messages or stored secrets."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment

from ..core.advisory_service import AdvisoryService
from ..core.ai_providers import infer_provider, preset, presets
from ..core.models import WorkbenchError
from ..integrations.ai_provider import diagnose_endpoint, diagnose_models, endpoint
from .contracts import AIConfiguration, AIConsultation, AIDiagnostic, AIModelDiagnostic
from .errors import idempotency_key

_ID = re.compile(r"[a-f0-9]{32}\Z")


def identifier(value: str) -> str:
    if not _ID.fullmatch(value):
        raise WorkbenchError("INVALID_ID", "研判或任务标识格式无效")
    return value


def advisory_router(service: AdvisoryService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["optional-evidence-advisory"])

    @router.get("/ai/config")
    async def configuration() -> dict[str, Any]:
        return service.config()

    @router.get("/ai/providers")
    async def providers() -> dict[str, Any]:
        return {"items": presets()}

    @router.post("/ai/diagnose")
    async def diagnose(payload: AIDiagnostic | None = None) -> dict[str, Any]:
        # Diagnose the explicit unsaved draft, never replace its URL with a
        # preset URL or send current credentials to a newly selected service.
        settings = dict(service.settings)
        if payload is not None:
            settings.update(payload.model_dump(exclude_none=True))
        if settings["provider_id"] == "openai-compatible":
            settings["provider_id"] = "openai_compatible"
        selected = preset(settings["provider_id"])
        result = await diagnose_endpoint(settings)
        return {**result, "provider_id": settings["provider_id"], "provider_label": selected["label"],
                "model_call": False, "business_data_sent": False,
                "network": result["status"], "protocol": result["message"],
                "authentication": "未发送密钥；鉴权和模型输出均未验证。",
                "model_suggestion": (selected["models"] or ["请填写服务商提供的模型标识"])[0],
                "limitations": ["连接诊断不发送业务证据、不调用模型、不验证模型输出。",
                                "使用直连且不读取系统代理；不会跟随重定向或忽略 TLS 证书错误。"]}

    @router.put("/ai/config")
    async def configure(payload: AIConfiguration) -> dict[str, Any]:
        base = endpoint(payload.base_url, payload.allow_local)
        model = payload.model.strip()
        key = payload.api_key.strip() if payload.api_key else None
        if (any(ord(char) < 33 or ord(char) > 126 for char in model)
                or key and any(ord(char) < 33 or ord(char) > 126 for char in key)
                or payload.enabled and not model or payload.clear_key and key):
            raise WorkbenchError("AI_INVALID_CONFIG", "模型名称或密钥格式无效；清除密钥时不要同时提交新密钥")
        provider_id = payload.provider_id or (str(service.settings["provider_id"])
                                              if base == service.settings["base_url"] else infer_provider(base))
        if provider_id == "openai-compatible":
            provider_id = "openai_compatible"
        if payload.reasoning_effort not in preset(provider_id)["reasoning_efforts"]:
            raise WorkbenchError("AI_INVALID_CONFIG", "所选提供商不支持该推理强度；请选择默认或目录中的选项")
        same_profile = base == service.settings["base_url"] and provider_id == service.settings["provider_id"]
        token_limit_field = payload.token_limit_field or (service.settings.get("token_limit_field") if same_profile else None)
        token_limit_field = token_limit_field or preset(provider_id)["token_limit_field"]
        if provider_id == "deepseek" and token_limit_field != "max_tokens":
            raise WorkbenchError("AI_INVALID_CONFIG", "DeepSeek 接口使用 max_tokens 输出预算字段")
        return await service.configure({"enabled": payload.enabled, "provider_id": provider_id,
                                        "base_url": base, "model": model,
                                        "reasoning_effort": payload.reasoning_effort,
                                        "token_limit_field": token_limit_field,
                                        "allow_local": payload.allow_local}, key=key, clear_key=payload.clear_key)

    @router.post("/ai/diagnose/models")
    async def models_diagnostic(payload: AIModelDiagnostic) -> dict[str, Any]:
        settings, secret = await service.model_diagnostic_snapshot(payload.configuration_sha256, payload.consent)
        result = await diagnose_models(settings, secret)
        return {**result, "kind": "saved_models", "provider_id": settings["provider_id"],
                "provider_label": preset(settings["provider_id"])["label"],
                "model": settings["model"], "model_call": False, "business_data_sent": False, "inference_verified": False,
                "limitations": ["仅向已确认的保存基址发送一次带凭据的 GET /models；不发送业务摘要或模型推理请求。",
                                "模型目录可见不证明推理权限、参数兼容性、额度或输出质量；不会自动重试。",
                                "模型目录和原始错误文本不会返回、保存或记录。"]}

    @router.get("/jobs/{job_id}/advisory/preview")
    async def preview(job_id: str) -> dict[str, Any]:
        return await service.preview(identifier(job_id))

    @router.post("/jobs/{job_id}/advisory", status_code=202)
    async def submit(job_id: str, payload: AIConsultation, request: Request) -> dict[str, Any]:
        key = idempotency_key(request)
        if key is None:
            raise WorkbenchError("AI_OPERATION_KEY_REQUIRED", "研判请求必须携带操作标识，防止响应丢失造成重复调用")
        return await service.submit(identifier(job_id), payload.context_sha256, payload.consent, payload.authorization_note, key)

    @router.get("/jobs/{job_id}/advisories")
    async def reports(job_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await asyncio.to_thread(service.records.list, identifier(job_id), limit, offset)

    @router.get("/jobs/{job_id}/controls")
    async def job_controls(job_id: str) -> dict[str, Any]:
        return await service.job_controls(identifier(job_id))

    @router.get("/jobs/{job_id}/controls/{control_id}/guide")
    async def job_guide(job_id: str, control_id: str, environment: Literal["generic", "nginx"] = "generic") -> dict[str, Any]:
        return await service.job_control_guide(identifier(job_id), control_id, environment)

    @router.get("/advisories/{report_id}")
    async def detail(report_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(service.records.get, identifier(report_id))

    @router.get("/advisories/{report_id}/controls/{control_id}/guide")
    async def guide(report_id: str, control_id: str, environment: Literal["generic", "nginx"] = "generic") -> dict[str, Any]:
        return await service.control_guide(identifier(report_id), control_id, environment)

    @router.get("/advisories/{report_id}/export")
    async def export(report_id: str, format: Literal["json", "html"] = "json") -> Response:
        report = await asyncio.to_thread(service.records.get, identifier(report_id))
        headers = {"Content-Disposition": f'attachment; filename="reachscope-advisory-{report_id}.{format}"'}
        if format == "json":
            return Response(json.dumps(report, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
        html = Environment(autoescape=True).from_string(_REPORT).render(report=report)
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return HTMLResponse(html, headers=headers)

    return router


_REPORT = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>ReachScope AI 研判</title>
<style>body{font:15px/1.7 system-ui;background:#f5f3ec;color:#262a25;max-width:1000px;margin:32px auto;padding:24px}article{border-top:1px solid #aaa;margin-top:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#62695c}</style>
<h1>Web AI 研判 · 待人工复核</h1><p>状态：{{ report.status }} / {{ report.provider.model }} / {{ report.created_at }}</p>
{% if report.provider.model.startswith('protocol-fixture-') %}<p>本机协议模拟：不代表真实模型质量或服务商验收。</p>{% endif %}
<p>任务：{{ report.job_id }}　记录：{{ report.id }}</p><p>摘要 SHA-256：{{ report.context_sha256 }}</p>
{% if report.error %}<p>{{ report.error.code }}：{{ report.error.message }}</p>{% endif %}
{% for perspective,label in [('red','红队 · 授权核查方向'),('blue','蓝队 · 配置与流程补强')] %}<h2>{{ label }}</h2>
{% for item in report[perspective] %}<article><h3>{{ item.title }}</h3><small>{{ item.priority }} / {{ item.applicability }} / {{ item.basis }}</small>
<ul>{% for text in item.actions %}<li>{{ text }}</li>{% endfor %}</ul><h4>人工验证</h4><ul>{% for text in item.verification %}<li>{{ text }}</li>{% endfor %}</ul>
<p>证据：{{ item.evidence_ids|join(', ') }}</p><ul>{% for text in item.limitations %}<li>{{ text }}</li>{% endfor %}</ul>
<p>{% for reference in item.references %}{{ reference.title }}：{{ reference.url }}<br>{% endfor %}</p></article>{% endfor %}{% endfor %}
<h2>发送的最小化摘要</h2><pre>{{ report.context|tojson(indent=2) }}</pre><h2>范围和限制</h2>
<ul>{% for text in report.limitations %}<li>{{ text }}</li>{% endfor %}</ul></html>"""
