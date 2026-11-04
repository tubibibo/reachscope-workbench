"""Consistent public failures with bounded correlation IDs and no input echo."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.models import WorkbenchError

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def idempotency_key(request: Request) -> str | None:
    value = request.headers.get("idempotency-key")
    if value is not None and not _KEY.fullmatch(value):
        raise WorkbenchError("INVALID_IDEMPOTENCY_KEY", "操作标识格式无效；请使用 1–128 个字母、数字或 ._:-")
    return value


def failure(request: Request, code: str, message: str, status: int,
            *, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id,
                             "retryable": status in {429, 503}}
    if details is not None:
        error["details"] = details[:30]
    return JSONResponse({"error": error}, status_code=status,
                        headers={"X-Request-ID": request_id, "Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})


def domain_status(code: str) -> int:
    if code.endswith("NOT_FOUND"):
        return 404
    if code in {"JOB_TERMINAL", "JOB_ACTIVE", "WORKSPACE_BUSY", "RESULT_UNAVAILABLE", "IDEMPOTENCY_CONFLICT", "PREFLIGHT_BLOCKED",
                "CASE_CONFLICT", "RETEST_REQUIRED", "RETEST_NOT_CLEARED", "AI_PREVIEW_STALE", "AI_NOT_CONFIGURED",
                "LAB_CONFLICT", "LAB_NOT_RUNNING"}:
        return 409
    if code in {"QUEUE_FULL", "ASSET_LIMIT", "AI_BUSY", "AI_REPORT_LIMIT"}:
        return 429
    if code in {"REQUEST_LIMIT"}:
        return 413
    if code in {"AI_UNAVAILABLE", "LAB_UNAVAILABLE"}:
        return 503
    return 400
