"""Scoped red/blue work views and auditable case decisions, using saved evidence."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment

from ..core.case_service import CaseService
from ..core.models import WorkbenchError
from ..core.repository import JobRepository
from .contracts import CaseCreate, CasePatch, CaseRetest, CaseRetestInput, EngagementCreate
from .errors import idempotency_key

_ID = re.compile(r"[a-f0-9]{32}\Z")


def _identifier(value: str) -> str:
    if not _ID.fullmatch(value):
        raise WorkbenchError("INVALID_ID", "记录标识格式无效")
    return value


def collaboration_router(repository: JobRepository) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["evidence-workflows"])
    service = CaseService(repository)
    records = service.collaboration

    @router.get("/engagements")
    async def engagements(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await asyncio.to_thread(records.list_engagements, limit=limit, offset=offset)

    @router.post("/engagements", status_code=201)
    async def create_engagement(payload: EngagementCreate, request: Request) -> dict[str, Any]:
        if not payload.authorization_note.strip():
            raise WorkbenchError("INVALID_ENGAGEMENT", "请填写本次检查的授权与范围说明")
        asset_ids = [_identifier(identifier) for identifier in payload.asset_ids]
        return await asyncio.to_thread(records.create_engagement, payload.name, payload.objective,
                                       payload.authorization_note, asset_ids, idempotency_key=idempotency_key(request))

    @router.get("/engagements/{engagement_id}")
    async def engagement(engagement_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(records.get_engagement, _identifier(engagement_id))

    @router.get("/engagements/{engagement_id}/candidates")
    async def candidate_list(engagement_id: str, job_id: str = Query(min_length=32, max_length=32)) -> dict[str, Any]:
        return await asyncio.to_thread(service.candidate_list, _identifier(engagement_id), _identifier(job_id))

    @router.get("/engagements/{engagement_id}/cases")
    async def cases(engagement_id: str, status: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        identifier = _identifier(engagement_id)
        await asyncio.to_thread(records.get_engagement, identifier)
        return await asyncio.to_thread(records.list_cases, engagement_id=identifier, status=status, limit=limit, offset=offset)

    @router.post("/engagements/{engagement_id}/cases", status_code=201)
    async def create_case(engagement_id: str, payload: CaseCreate, request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(service.create_case, _identifier(engagement_id), _identifier(payload.job_id),
                                       payload.source_kind, payload.source_ref, idempotency_key=idempotency_key(request))

    @router.get("/cases/{case_id}")
    async def detail(case_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(service.detail, _identifier(case_id))

    @router.get("/cases/{case_id}/events")
    async def events(case_id: str, after: int = 0, limit: int = 100) -> dict[str, Any]:
        return await asyncio.to_thread(records.get_events, _identifier(case_id), after=after, limit=limit)

    @router.patch("/cases/{case_id}")
    async def update(case_id: str, payload: CasePatch) -> dict[str, Any]:
        patch = payload.model_dump(exclude_unset=True, exclude={"expected_version", "retest_job_id"})
        return await asyncio.to_thread(service.update, _identifier(case_id), payload.expected_version, patch,
                                       retest_job_id=_identifier(payload.retest_job_id) if payload.retest_job_id else None)

    @router.get("/cases/{case_id}/retest")
    async def assess(case_id: str, job_id: str = Query(min_length=32, max_length=32)) -> dict[str, Any]:
        return await asyncio.to_thread(service.assessment, _identifier(case_id), _identifier(job_id))

    @router.post("/cases/{case_id}/retests")
    async def record(case_id: str, payload: CaseRetest) -> dict[str, Any]:
        return await asyncio.to_thread(service.record_retest, _identifier(case_id), payload.expected_version,
                                       _identifier(payload.job_id), payload.note)

    @router.get("/cases/{case_id}/retest-inputs")
    async def retest_inputs(case_id: str) -> dict[str, Any]:
        identifier = _identifier(case_id)
        await asyncio.to_thread(records.get_case, identifier)
        return {"items": await asyncio.to_thread(records.get_retest_inputs, identifier)}

    @router.post("/cases/{case_id}/retest-inputs")
    async def link_input(case_id: str, payload: CaseRetestInput) -> dict[str, Any]:
        return await asyncio.to_thread(service.link_revised_input, _identifier(case_id), payload.expected_version,
                                       _identifier(payload.asset_id), payload.note)

    @router.get("/cases/{case_id}/retest-jobs")
    async def retest_jobs(case_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return await asyncio.to_thread(service.retest_jobs, _identifier(case_id), limit=limit, offset=offset)

    @router.get("/engagements/{engagement_id}/export")
    async def export(engagement_id: str, format: Literal["json", "html"] = "json") -> Response:
        identifier = _identifier(engagement_id)
        report = await asyncio.to_thread(service.export, identifier)
        filename = f"reachscope-workflow-{identifier}.{format}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if format == "json":
            return Response(json.dumps(report, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
        html = Environment(autoescape=True).from_string(_TEMPLATE).render(report=report)
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return HTMLResponse(html, headers=headers)

    return router


_TEMPLATE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>ReachScope · {{ report.engagement.name }}</title>
<style>body{font:15px/1.7 system-ui;color:#262a25;background:#f5f3ec;max-width:1100px;margin:40px auto;padding:24px}article{border-top:1px solid #bbb;margin:24px 0;padding:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eae8df;padding:16px}small{color:#62695c}h1,h2{font-weight:500}</style>
<h1>{{ report.engagement.name }}</h1><p>{{ report.engagement.objective }}</p>
<h2>范围与记录依据</h2><p>{{ report.engagement.authorization_note }}</p>
<ul>{% for asset in report.engagement.assets %}<li>{{ asset.name }} / {{ asset.kind }} / {{ asset.id }}</li>{% endfor %}</ul>
<p>红队视角：范围、线索、证据及人工验证记录。蓝队视角：负责人、处理决定、复测与历史。</p>
<pre>{{ report.export_scope|tojson(indent=2) }}</pre>
{% for case in report.cases %}<article><h2>{{ case.title }}</h2>
<small>{{ case.asset_name }} / {{ case.confidence }} / {{ case.severity }} / {{ case.status }} / v{{ case.version }}</small>
<p>{{ case.source.description }}</p><p>{{ case.source.recommendation }}</p>
<p>负责人：{{ case.owner }}　截止日期：{{ case.due_date }}</p><p>{{ case.note }}</p>
<h3>原始证据</h3>{% for evidence in case.evidence %}<p>{{ evidence.source }} / {{ evidence.id }}</p><pre>{{ evidence.data|tojson(indent=2) }}</pre>{% endfor %}
<h3>处理与复测历史</h3><p>当前显示最早 {{ case.events|length }} 条（上限 100）。续读游标：{{ case.event_pagination.next_cursor }}；接口 /api/cases/{{ case.id }}/events?after={{ case.event_pagination.next_cursor }}</p><pre>{{ case.events|tojson(indent=2) }}</pre></article>{% endfor %}
<h2>范围与限制</h2><ul>{% for item in report.limitations %}<li>{{ item }}</li>{% endfor %}</ul>
<p>这是证据和处理记录，不自动证明漏洞可利用、整改完备或整体安全。</p></html>"""
