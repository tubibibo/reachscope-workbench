"""Scoped evidence cases and append-only decisions for local red/blue workflows.

The repository enforces scope, immutable source identity, versioned decisions and
atomic history. A higher-level use case must validate source references and any
retest/resolution claims against saved result evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date
from typing import Any
from uuid import uuid4

from .models import WorkbenchError
from .pagination import validate_page
from .repository import JobRepository, timestamp

CASE_STATUSES = ("open", "in_progress", "ready_for_retest", "resolved", "accepted_risk", "false_positive")
_DECISIONS = {"resolved", "accepted_risk", "false_positive"}
_SEVERITIES = {"info", "low", "medium", "high", "critical"}
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVENT = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")


def _text(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise WorkbenchError("INVALID_COLLABORATION", f"{field} 必须是文本")
    normalized: str = value.strip()
    if (required and not normalized) or len(normalized) > limit or any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in normalized):
        raise WorkbenchError("INVALID_COLLABORATION", f"{field} 为空、含非法字符或超过长度限制")
    try:
        normalized.encode("utf-8")
    except UnicodeError as exc:
        raise WorkbenchError("INVALID_COLLABORATION", f"{field} 包含无效 Unicode") from exc
    return normalized


def _page(limit: int, offset: int) -> None:
    validate_page(limit, offset)


def _json_data(value: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        raise WorkbenchError("INVALID_CASE_EVENT", "事件数据必须为对象")
    pending: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 2000 or depth > 20:
            raise WorkbenchError("INVALID_CASE_EVENT", "事件数据超过结构预算")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise WorkbenchError("INVALID_CASE_EVENT", "事件字段必须是文本")
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16384:
            raise WorkbenchError("INVALID_CASE_EVENT", "事件数据不得超过 16 KiB")
        return encoded
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise WorkbenchError("INVALID_CASE_EVENT", "事件数据不是有效的有限 JSON") from exc


class CollaborationRepository:
    def __init__(self, jobs: JobRepository) -> None:
        self.jobs = jobs

    @staticmethod
    def _case(db: sqlite3.Connection, identifier: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT c.*,a.name AS asset_name,a.kind AS asset_kind,j.name AS job_name "
            "FROM cases c JOIN assets a ON a.id=c.asset_id JOIN jobs j ON j.id=c.job_id WHERE c.id=?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise WorkbenchError("CASE_NOT_FOUND", "找不到这条协作记录")
        return dict(row)

    @staticmethod
    def _engagement(db: sqlite3.Connection, identifier: str, *, include_assets: bool = True) -> dict[str, Any]:
        row = db.execute("SELECT * FROM engagements WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise WorkbenchError("ENGAGEMENT_NOT_FOUND", "找不到这个检查项目")
        item = dict(row)
        assets = db.execute(
            "SELECT a.id,a.name,a.kind FROM engagement_assets ea JOIN assets a ON a.id=ea.asset_id "
            "WHERE ea.engagement_id=? ORDER BY a.name,a.id", (identifier,),
        ).fetchall()
        item["asset_ids"] = [asset["id"] for asset in assets]
        item["asset_count"] = len(assets)
        if include_assets:
            item["assets"] = [dict(asset) for asset in assets]
        counts = dict.fromkeys(CASE_STATUSES, 0)
        for count in db.execute("SELECT status,COUNT(*) AS total FROM cases WHERE engagement_id=? GROUP BY status", (identifier,)):
            if count["status"] in counts:
                counts[count["status"]] = count["total"]
        item["case_counts"] = counts
        item["case_count"] = sum(counts.values())
        return item

    def create_engagement(self, name: str, objective: str, authorization_note: str,
                          asset_ids: list[str], *, idempotency_key: str | None = None) -> dict[str, Any]:
        name = _text(name, "项目名称", 120)
        objective = _text(objective, "目标", 1000, required=False)
        authorization_note = _text(authorization_note, "范围说明", 2000, required=False)
        if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 100 or any(not isinstance(value, str) or not value for value in asset_ids):
            raise WorkbenchError("INVALID_ENGAGEMENT", "请选择 1–100 个已保存资产")
        identifiers = list(dict.fromkeys(asset_ids))
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key)):
            raise WorkbenchError("INVALID_IDEMPOTENCY_KEY", "操作标识格式无效")
        fingerprint = hashlib.sha256(_json_data({"name": name, "objective": objective,
            "authorization_note": authorization_note, "asset_ids": sorted(identifiers)}).encode()).hexdigest()
        identifier, now = uuid4().hex, timestamp()
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = db.execute("SELECT fingerprint,engagement_id FROM engagement_requests WHERE key=?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if existing["fingerprint"] != fingerprint:
                        raise WorkbenchError("IDEMPOTENCY_CONFLICT", "操作标识已用于另一个检查项目")
                    return self._engagement(db, existing["engagement_id"])
            for asset_id in identifiers:
                if db.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
                    raise WorkbenchError("ASSET_NOT_FOUND", "范围中存在未知资产")
            db.execute("INSERT INTO engagements VALUES(?,?,?,?,?,?)", (identifier, name, objective, authorization_note, now, now))
            db.executemany("INSERT INTO engagement_assets VALUES(?,?)", [(identifier, asset_id) for asset_id in identifiers])
            if idempotency_key is not None:
                db.execute("INSERT INTO engagement_requests VALUES(?,?,?)", (idempotency_key, fingerprint, identifier))
            return self._engagement(db, identifier)

    def get_engagement(self, identifier: str) -> dict[str, Any]:
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            return self._engagement(db, identifier)

    def list_engagements(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        _page(limit, offset)
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM engagements").fetchone()[0]
            ids = db.execute("SELECT id FROM engagements ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            items = [self._engagement(db, row["id"], include_assets=False) for row in ids]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def create_case(
        self, engagement_id: str, asset_id: str, job_id: str, source_ref: str,
        source_kind: str, title: str, severity: str, confidence: str,
        *, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        source_ref = _text(source_ref, "来源引用", 2000)
        source_kind = _text(source_kind, "来源类型", 40)
        title = _text(title, "记录标题", 300)
        confidence = _text(confidence, "确定程度", 80)
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            raise WorkbenchError("INVALID_CASE", "严重程度无效")
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key)):
            raise WorkbenchError("INVALID_IDEMPOTENCY_KEY", "操作标识格式无效")
        fingerprint = hashlib.sha256(_json_data({"engagement_id": engagement_id, "asset_id": asset_id,
            "job_id": job_id, "source_ref": source_ref, "source_kind": source_kind,
            "title": title, "severity": severity, "confidence": confidence}).encode()).hexdigest()
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = db.execute("SELECT fingerprint,case_id FROM case_requests WHERE key=?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if existing["fingerprint"] != fingerprint:
                        raise WorkbenchError("IDEMPOTENCY_CONFLICT", "操作标识已用于另一条协作记录")
                    return self._case(db, existing["case_id"])
            self._engagement(db, engagement_id, include_assets=False)
            if db.execute("SELECT 1 FROM engagement_assets WHERE engagement_id=? AND asset_id=?", (engagement_id, asset_id)).fetchone() is None:
                raise WorkbenchError("OUT_OF_SCOPE", "该资产不在此项目的范围内")
            job = db.execute("SELECT j.status,ja.asset_id FROM jobs j LEFT JOIN job_assets ja ON ja.job_id=j.id WHERE j.id=?", (job_id,)).fetchone()
            if job is None:
                raise WorkbenchError("JOB_NOT_FOUND", "找不到来源任务")
            if job["status"] != "completed":
                raise WorkbenchError("RESULT_UNAVAILABLE", "只有已完成任务可以形成协作记录")
            if job["asset_id"] != asset_id:
                raise WorkbenchError("ASSET_MISMATCH", "来源任务不属于选定资产")
            natural = db.execute("SELECT id FROM cases WHERE engagement_id=? AND job_id=? AND source_kind=? AND source_ref=?",
                                 (engagement_id, job_id, source_kind, source_ref)).fetchone()
            if natural is not None:
                identifier = natural["id"]
            else:
                identifier, now = uuid4().hex, timestamp()
                db.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    identifier, engagement_id, asset_id, job_id, source_ref, source_kind, title, severity,
                    confidence, "open", "", "", "", 1, now, now,
                ))
                self._event(db, identifier, "created", {"job_id": job_id, "source_ref": source_ref,
                                                      "source_kind": source_kind, "confidence": confidence})
                db.execute("UPDATE engagements SET updated_at=? WHERE id=?", (now, engagement_id))
            if idempotency_key is not None:
                db.execute("INSERT INTO case_requests VALUES(?,?,?)", (idempotency_key, fingerprint, identifier))
            return self._case(db, identifier)

    def get_case(self, identifier: str) -> dict[str, Any]:
        with self.jobs.connection() as db:
            return self._case(db, identifier)

    def list_cases(self, engagement_id: str | None = None, status: str | None = None,
                   *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        _page(limit, offset)
        if status is not None and status not in CASE_STATUSES:
            raise WorkbenchError("INVALID_CASE", "协作状态无效")
        clauses, parameters = [], []
        if engagement_id is not None:
            clauses.append("c.engagement_id=?")
            parameters.append(engagement_id)
        if status is not None:
            clauses.append("c.status=?")
            parameters.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            if engagement_id is not None:
                self._engagement(db, engagement_id, include_assets=False)
            total = db.execute(f"SELECT COUNT(*) FROM cases c {where}", parameters).fetchone()[0]
            ids = db.execute(f"SELECT c.id FROM cases c {where} ORDER BY c.updated_at DESC,c.id DESC LIMIT ? OFFSET ?",
                             (*parameters, limit, offset)).fetchall()
            items = [self._case(db, row["id"]) for row in ids]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def update_case(self, identifier: str, expected_version: int, patch: dict[str, Any],
                    *, event_type: str = "updated", event_data: dict[str, Any] | None = None) -> dict[str, Any]:
        if type(expected_version) is not int or expected_version < 1:
            raise WorkbenchError("INVALID_CASE", "请提供当前记录版本")
        if not isinstance(patch, dict) or patch.keys() - {"status", "owner", "due_date", "note"}:
            raise WorkbenchError("INVALID_CASE", "协作更新字段无效")
        if not patch and event_data is None:
            raise WorkbenchError("INVALID_CASE", "没有需要更新或记录的内容")
        if not isinstance(event_type, str) or not _EVENT.fullmatch(event_type):
            raise WorkbenchError("INVALID_CASE_EVENT", "事件类型格式无效")
        values: dict[str, Any] = {}
        if "status" in patch:
            if patch["status"] not in CASE_STATUSES:
                raise WorkbenchError("INVALID_CASE", "协作状态无效")
            values["status"] = patch["status"]
        for field, limit in (("owner", 80), ("note", 4000)):
            if field in patch:
                values[field] = _text(patch[field], field, limit, required=False)
        if values.get("status") in _DECISIONS and not values.get("note"):
            raise WorkbenchError("DECISION_NOTE_REQUIRED", "关闭、接受风险或误报判断需要本次说明")
        if "due_date" in patch:
            raw = patch["due_date"]
            if raw is not None and not isinstance(raw, str):
                raise WorkbenchError("INVALID_CASE", "截止日期须为 YYYY-MM-DD")
            value = raw or ""
            if not isinstance(value, str) or value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise WorkbenchError("INVALID_CASE", "截止日期须为 YYYY-MM-DD")
            if value:
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError("not an ISO calendar date")
                except ValueError as exc:
                    raise WorkbenchError("INVALID_CASE", "截止日期无效") from exc
            values["due_date"] = value
        extra = {} if event_data is None else event_data
        _json_data(extra)
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._case(db, identifier)
            if current["version"] != expected_version:
                raise WorkbenchError("CASE_CONFLICT", "记录已被更新，请重新读取后再提交")
            updated = {**current, **values}
            now = timestamp()
            db.execute("UPDATE cases SET status=?,owner=?,due_date=?,note=?,version=version+1,updated_at=? WHERE id=? AND version=?", (
                updated["status"], updated["owner"], updated["due_date"], updated["note"], now, identifier, expected_version,
            ))
            self._event(db, identifier, event_type, {**extra, "before_version": expected_version, "version": expected_version + 1,
                                                   "changes": values})
            db.execute("UPDATE engagements SET updated_at=? WHERE id=?", (now, current["engagement_id"]))
            return self._case(db, identifier)

    @staticmethod
    def _event(db: sqlite3.Connection, case_id: str, event_type: str, data: dict[str, Any]) -> None:
        encoded = _json_data(data)
        db.execute("INSERT INTO case_events(case_id,created_at,event_type,data) VALUES(?,?,?,?)", (case_id, timestamp(), event_type, encoded))

    def get_events(self, identifier: str, *, after: int = 0, limit: int = 100) -> dict[str, Any]:
        validate_page(limit, after)
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            self._case(db, identifier)
            rows = db.execute("SELECT * FROM case_events WHERE case_id=? AND id>? ORDER BY id LIMIT ?", (identifier, after, limit)).fetchall()
        items = [{**dict(row), "data": json.loads(row["data"])} for row in rows]
        return {"items": items, "next_cursor": items[-1]["id"] if items else after}

    def add_retest_input(self, identifier: str, expected_version: int, asset_id: str, note: str) -> dict[str, Any]:
        if type(expected_version) is not int or expected_version < 1:
            raise WorkbenchError("INVALID_CASE", "请提供当前记录版本")
        note = _text(note, "修订输入说明", 4000)
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._case(db, identifier)
            if current["version"] != expected_version:
                raise WorkbenchError("CASE_CONFLICT", "记录已被更新，请重新读取后再提交")
            if db.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
                raise WorkbenchError("ASSET_NOT_FOUND", "找不到这个复测输入资产")
            if db.execute("SELECT 1 FROM case_retest_inputs WHERE case_id=? AND asset_id=?", (identifier, asset_id)).fetchone():
                return current
            now = timestamp()
            db.execute("INSERT INTO case_retest_inputs VALUES(?,?,?)", (identifier, asset_id, now))
            db.execute("UPDATE cases SET version=version+1,updated_at=? WHERE id=? AND version=?", (now, identifier, expected_version))
            self._event(db, identifier, "retest_input", {"asset_id": asset_id, "note": note,
                                                       "before_version": expected_version, "version": expected_version + 1})
            db.execute("UPDATE engagements SET updated_at=? WHERE id=?", (now, current["engagement_id"]))
            return self._case(db, identifier)

    def get_retest_inputs(self, identifier: str) -> list[dict[str, Any]]:
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            self._case(db, identifier)
            rows = db.execute("SELECT a.*,r.created_at AS linked_at FROM case_retest_inputs r JOIN assets a ON a.id=r.asset_id "
                              "WHERE r.case_id=? ORDER BY r.created_at,r.asset_id", (identifier,)).fetchall()
        return [{**dict(row), "source": json.loads(row["source"])} for row in rows]
