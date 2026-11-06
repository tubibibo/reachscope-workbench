"""Durable consultation requests; reports and failures survive response loss."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .advisory_context import canonical
from .models import WorkbenchError
from .pagination import validate_page
from .repository import JobRepository, timestamp


def _object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise WorkbenchError("AI_STORAGE_INVALID", "研判记录存储结构无效")
    return parsed


class AdvisoryRepository:
    def __init__(self, jobs: JobRepository) -> None:
        self.jobs = jobs

    def settings(self) -> dict[str, Any] | None:
        with self.jobs.connection() as db:
            row = db.execute("SELECT data FROM ai_settings WHERE id=1").fetchone()
        return _object(row[0]) if row else None

    def save_settings(self, value: dict[str, Any]) -> None:
        if set(value) - {"enabled", "provider_id", "base_url", "model", "reasoning_effort", "token_limit_field", "allow_local", "revision", "_environment_blocked_scopes"}:
            raise WorkbenchError("AI_INVALID_CONFIG", "设置包含不允许保存的字段")
        with self.jobs.connection() as db:
            db.execute("INSERT INTO ai_settings(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (canonical(value),))

    def replay(self, key: str, fingerprint: str) -> dict[str, Any] | None:
        with self.jobs.connection() as db:
            row = db.execute("SELECT fingerprint,data FROM ai_reports WHERE request_key=?", (key,)).fetchone()
        if not row:
            return None
        if row["fingerprint"] != fingerprint:
            raise WorkbenchError("IDEMPOTENCY_CONFLICT", "操作标识已用于其他研判输入，请重新预览后开始新一轮")
        return _object(row["data"])

    def reserve(self, job_id: str, key: str, fingerprint: str, report: dict[str, Any]) -> dict[str, Any]:
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT fingerprint,data FROM ai_reports WHERE request_key=?", (key,)).fetchone()
            if row and row["fingerprint"] != fingerprint:
                raise WorkbenchError("IDEMPOTENCY_CONFLICT", "操作标识已用于其他研判输入")
            if row:
                return _object(row["data"])
            item = {**report, "id": uuid4().hex, "job_id": job_id, "status": "running", "created_at": timestamp()}
            db.execute("INSERT INTO ai_reports VALUES(?,?,?,?,?,?)", (item["id"], job_id, key, fingerprint, "running", canonical(item)))
        return item

    def finish(self, identifier: str, status: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data,status FROM ai_reports WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise WorkbenchError("AI_REPORT_NOT_FOUND", "找不到研判记录")
            current = _object(row["data"])
            if row["status"] != "running":
                return current
            updated = {**current, **patch, "status": status, "finished_at": timestamp()}
            db.execute("UPDATE ai_reports SET status=?,data=? WHERE id=? AND status='running'", (status, canonical(updated), identifier))
        return updated

    def recover(self) -> None:
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,data FROM ai_reports WHERE status='running'").fetchall():
                value = {**_object(row["data"]), "status": "interrupted", "finished_at": timestamp(),
                         "error": {"code": "AI_INTERRUPTED", "message": "服务重启或关闭；无法确认服务商是否已处理，不会自动重复调用"}}
                db.execute("UPDATE ai_reports SET status='interrupted',data=? WHERE id=?", (canonical(value), row["id"]))

    def get(self, identifier: str) -> dict[str, Any]:
        with self.jobs.connection() as db:
            row = db.execute("SELECT data FROM ai_reports WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise WorkbenchError("AI_REPORT_NOT_FOUND", "找不到研判记录")
        return _object(row["data"])

    def list(self, job_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        validate_page(limit, offset)
        self.jobs.get(job_id)
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM ai_reports WHERE job_id=?", (job_id,)).fetchone()[0]
            rows = db.execute("SELECT data FROM ai_reports WHERE job_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?", (job_id, limit, offset)).fetchall()
        return {"items": [_object(row["data"]) for row in rows], "total": total, "limit": limit, "offset": offset}
