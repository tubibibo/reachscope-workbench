"""Durable asset inventory and immutable job association; no network operations."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from .models import WorkbenchError
from .pagination import validate_page
from .repository import JobRepository, timestamp


class AssetRepository:
    def __init__(self, jobs: JobRepository) -> None:
        self.jobs = jobs

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["source"] = json.loads(item["source"])
        item["provenance"] = json.loads(item["provenance"]) if item.get("provenance") else None
        return item

    def create(self, kind: str, name: str, source: dict[str, Any],
               *, idempotency_key: str | None = None, provenance: dict[str, str] | None = None) -> dict[str, Any]:
        now, identifier = timestamp(), uuid4().hex
        name = name.strip()
        fingerprint = hashlib.sha256(json.dumps(
            {"kind": kind, "name": name, "source": source}, ensure_ascii=False,
            allow_nan=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        with self.jobs.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT fingerprint,asset_id FROM asset_requests WHERE key=?",
                                  (idempotency_key,)).fetchone() if idempotency_key is not None else None
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise WorkbenchError("IDEMPOTENCY_CONFLICT", "这个请求标识已用于不同的资产，请使用新的标识")
                identifier = existing["asset_id"]
            else:
                count = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
                if count >= 5000:
                    raise WorkbenchError("ASSET_LIMIT", "当前工作区资产数量达到 5000 上限")
                db.execute("INSERT INTO assets(id,kind,name,source,created_at,updated_at,provenance) VALUES(?,?,?,?,?,?,?)",
                           (identifier, kind, name, json.dumps(source, ensure_ascii=False, allow_nan=False), now, now,
                            json.dumps(provenance, ensure_ascii=False, allow_nan=False) if provenance else None))
                if idempotency_key is not None:
                    db.execute("INSERT INTO asset_requests VALUES(?,?,?)", (idempotency_key, fingerprint, identifier))
        return self.get(identifier)

    def get(self, identifier: str) -> dict[str, Any]:
        with self.jobs.connection() as db:
            row = db.execute("SELECT a.*,COUNT(ja.job_id) AS job_count,MAX(j.created_at) AS last_checked_at "
                             "FROM assets a LEFT JOIN job_assets ja ON ja.asset_id=a.id "
                             "LEFT JOIN jobs j ON j.id=ja.job_id WHERE a.id=? GROUP BY a.id", (identifier,)).fetchone()
        if row is None:
            raise WorkbenchError("ASSET_NOT_FOUND", "找不到这个资产")
        return self._decode(row)

    def list(self, *, kind: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        validate_page(limit, offset)
        if kind is not None and kind not in {"android", "website", "cloud", "host"}:
            raise WorkbenchError("INVALID_ASSET", "未知的资产类别")
        where, values = ("WHERE a.kind=?", (kind,)) if kind else ("", ())
        with self.jobs.connection() as db:
            db.execute("BEGIN")
            total = db.execute(f"SELECT COUNT(*) FROM assets a {where}", values).fetchone()[0]
            rows = db.execute(
                "SELECT a.*,COUNT(ja.job_id) AS job_count,MAX(j.created_at) AS last_checked_at "
                "FROM assets a LEFT JOIN job_assets ja ON ja.asset_id=a.id LEFT JOIN jobs j ON j.id=ja.job_id "
                f"{where} GROUP BY a.id ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        return {"items": [self._decode(row) for row in rows], "total": total, "limit": limit, "offset": offset}
