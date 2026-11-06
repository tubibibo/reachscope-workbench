"""Transactional job/event persistence using short-lived SQLite connections."""

from __future__ import annotations

import builtins
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import WorkbenchError
from .pagination import validate_page

TERMINAL = frozenset({"completed", "failed", "cancelled"})
logger = logging.getLogger(__name__)


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class JobRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            # Reject a future/corrupt schema before changing journal mode or DDL.
            # executescript() implicitly commits, so issue our fixed statements
            # individually inside one explicit migration transaction instead.
            self._schema_version(db)
            db.execute("BEGIN IMMEDIATE")
            self._schema_version(db)
            schema = """
                CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL);
                INSERT INTO schema_meta SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_meta);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, module TEXT NOT NULL, name TEXT NOT NULL,
                    config TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL,
                    message TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    error TEXT, result TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, level TEXT NOT NULL,
                    message TEXT NOT NULL, progress INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id,id);
                CREATE TABLE IF NOT EXISTS uploads(
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,
                    source TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    provenance TEXT
                );
                CREATE INDEX IF NOT EXISTS assets_created ON assets(created_at DESC);
                CREATE TABLE IF NOT EXISTS job_assets(
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id),snapshot TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_assets_asset ON job_assets(asset_id);
                CREATE TABLE IF NOT EXISTS job_requests(
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS asset_requests(
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS engagements(
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,objective TEXT NOT NULL,
                    authorization_note TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS engagement_assets(
                    engagement_id TEXT NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id),
                    PRIMARY KEY(engagement_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS cases(
                    id TEXT PRIMARY KEY,engagement_id TEXT NOT NULL REFERENCES engagements(id),
                    asset_id TEXT NOT NULL REFERENCES assets(id),job_id TEXT NOT NULL REFERENCES jobs(id),
                    source_ref TEXT NOT NULL,source_kind TEXT NOT NULL,title TEXT NOT NULL,
                    severity TEXT NOT NULL,confidence TEXT NOT NULL,status TEXT NOT NULL,
                    owner TEXT NOT NULL,due_date TEXT NOT NULL,note TEXT NOT NULL,version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    UNIQUE(engagement_id,job_id,source_kind,source_ref)
                );
                CREATE INDEX IF NOT EXISTS cases_engagement ON cases(engagement_id,updated_at DESC);
                CREATE INDEX IF NOT EXISTS cases_status ON cases(status,updated_at DESC);
                CREATE TABLE IF NOT EXISTS case_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,event_type TEXT NOT NULL,data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS case_events_case ON case_events(case_id,id);
                CREATE TABLE IF NOT EXISTS case_requests(
                    key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS engagement_requests(
                    key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,
                    engagement_id TEXT NOT NULL REFERENCES engagements(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS case_retest_inputs(
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id),created_at TEXT NOT NULL,
                    PRIMARY KEY(case_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS ai_settings(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_reports(
                    id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
                    request_key TEXT NOT NULL UNIQUE,fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ai_reports_job ON ai_reports(job_id);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            # Additive migration retains all jobs, inputs and associations.
            columns = {row[1] for row in db.execute("PRAGMA table_info(assets)")}
            if "provenance" not in columns:
                db.execute("ALTER TABLE assets ADD COLUMN provenance TEXT")
            # Version 7 gates the new host asset/result semantics. Older
            # releases must reject this workspace before interpreting them.
            db.execute("UPDATE schema_meta SET version=7")
            db.commit()
            self._enable_wal(db)

    @staticmethod
    def _enable_wal(db: sqlite3.Connection) -> None:
        mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            logger.warning("WAL unavailable; actual journal mode: %s", mode)

    def check_schema_version(self) -> int:
        """Validate again under the workspace lease without creating a missing DB."""
        try:
            db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True, timeout=10)
            try:
                version = self._schema_version(db)
            finally:
                db.close()
        except (sqlite3.DatabaseError, OSError) as exc:
            raise WorkbenchError("SCHEMA_UNSUPPORTED", "Workspace database cannot be opened") from exc
        if version != 7:
            raise WorkbenchError("SCHEMA_UNSUPPORTED", "Workspace database version is unsupported")
        return version

    @staticmethod
    def _schema_version(db: sqlite3.Connection) -> int | None:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "schema_meta" not in tables:
            if tables - {"sqlite_sequence"}:
                raise WorkbenchError("SCHEMA_UNSUPPORTED", "Workspace database has no supported schema metadata")
            return None
        try:
            rows = db.execute("SELECT version FROM schema_meta").fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkbenchError("SCHEMA_UNSUPPORTED", "Workspace schema metadata is invalid") from exc
        if len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] not in {1, 2, 3, 4, 5, 6, 7}:
            raise WorkbenchError("SCHEMA_UNSUPPORTED", "Workspace database version is unsupported")
        return int(rows[0][0])

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, module: str, name: str, config: dict[str, Any],
               *, asset: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connection() as db:
            job_id = self._insert(db, module, name, config, asset)
        return self.get(job_id)

    def _insert(self, db: sqlite3.Connection, module: str, name: str, config: dict[str, Any],
                asset: dict[str, Any] | None) -> str:
        job_id, now = uuid4().hex, timestamp()
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, module, name, _json(config), "queued", 0, "等待执行", now, now, None, None),
        )
        self._event(db, job_id, "info", "任务已创建", 0)
        if asset is not None:
            snapshot = {field: asset[field] for field in ("id", "kind", "name", "source")}
            if asset.get("provenance"):
                snapshot["provenance"] = asset["provenance"]
            db.execute("INSERT INTO job_assets VALUES(?,?,?)", (job_id, asset["id"], _json(snapshot)))
        return job_id

    @staticmethod
    def _request_id(db: sqlite3.Connection, key: str, fingerprint: str) -> str | None:
        row = db.execute("SELECT fingerprint,job_id FROM job_requests WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise WorkbenchError("IDEMPOTENCY_CONFLICT", "这个请求标识已用于不同的检查，请使用新的标识")
        return str(row["job_id"])

    def request_job(self, key: str, fingerprint: str) -> dict[str, Any] | None:
        with self.connection() as db:
            db.execute("BEGIN")
            job_id = self._request_id(db, key, fingerprint)
            return self._get(db, job_id) if job_id is not None else None

    def create_idempotent(
        self, module: str, name: str, config: dict[str, Any], *, request_key: str,
        request_fingerprint: str, asset: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self._request_id(db, request_key, request_fingerprint)
            if existing is not None:
                return self._get(db, existing), False
            job_id = self._insert(db, module, name, config, asset)
            db.execute("INSERT INTO job_requests VALUES(?,?,?)", (request_key, request_fingerprint, job_id))
            return self._get(db, job_id), True

    @staticmethod
    def _decode(row: sqlite3.Row, *, include_result: bool = True) -> dict[str, Any]:
        job = dict(row)
        for field in ("config", "error", "result"):
            raw = job.get(field)
            job[field] = json.loads(raw) if raw else None
        if not include_result:
            job.pop("result", None)
        snapshot = job.pop("asset_snapshot_json", None)
        job["asset_snapshot"] = json.loads(snapshot) if snapshot else None
        job.setdefault("asset_id", None)
        return job

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connection() as db:
            return self._get(db, job_id)

    @classmethod
    def _get(cls, db: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        row = db.execute("SELECT j.*,ja.asset_id,ja.snapshot AS asset_snapshot_json "
                         "FROM jobs j LEFT JOIN job_assets ja ON ja.job_id=j.id WHERE j.id=?", (job_id,)).fetchone()
        if row is None:
            raise WorkbenchError("JOB_NOT_FOUND", "找不到该任务")
        return cls._decode(row)

    def list(self, module: str | None = None, *, limit: int = 50, offset: int = 0,
             asset_id: str | None = None) -> dict[str, Any]:
        validate_page(limit, offset)
        clauses, args = [], []
        if module:
            clauses.append("j.module=?")
            args.append(module)
        if asset_id:
            clauses.append("ja.asset_id=?")
            args.append(asset_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        tables = "jobs j LEFT JOIN job_assets ja ON ja.job_id=j.id"
        with self.connection() as db:
            db.execute("BEGIN")
            count = db.execute(f"SELECT COUNT(*) FROM {tables} {where}", args).fetchone()[0]
            rows = db.execute(
                f"SELECT j.id,j.module,j.name,j.config,j.status,j.progress,j.message,j.created_at,j.updated_at,j.error,"
                f"ja.asset_id,ja.snapshot AS asset_snapshot_json "
                f"FROM {tables} {where} ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {"items": [self._decode(row, include_result=False) for row in rows], "total": count,
                "limit": limit, "offset": offset}

    @staticmethod
    def _event(db: sqlite3.Connection, job_id: str, level: str, message: str, progress: int) -> None:
        db.execute("INSERT INTO events(job_id,created_at,level,message,progress) VALUES(?,?,?,?,?)",
                   (job_id, timestamp(), level, message[:2000], progress))

    def transition(
        self, job_id: str, expected: set[str], status: str, message: str,
        *, error: dict[str, str] | None = None, result: dict[str, Any] | None = None,
    ) -> bool:
        with self.connection() as db:
            placeholders = ",".join("?" for _ in expected)
            progress = 100 if status == "completed" else None
            cursor = db.execute(
                f"UPDATE jobs SET status=?,message=?,updated_at=?,error=?,result=?,"
                f"progress=COALESCE(?,progress) WHERE id=? AND status IN ({placeholders})",
                (status, message, timestamp(), _json(error) if error else None,
                 _json(result) if result is not None else None, progress, job_id, *sorted(expected)),
            )
            if cursor.rowcount:
                row = db.execute("SELECT progress FROM jobs WHERE id=?", (job_id,)).fetchone()
                self._event(db, job_id, "error" if status == "failed" else "info", message, row[0])
                return True
        return False

    def progress(self, job_id: str, percent: int, message: str) -> None:
        percent = max(0, min(99, percent))
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE jobs SET progress=MAX(progress,?),message=?,updated_at=? WHERE id=? AND status='running'",
                (percent, message[:2000], timestamp(), job_id),
            )
            if cursor.rowcount:
                row = db.execute("SELECT progress FROM jobs WHERE id=?", (job_id,)).fetchone()
                self._event(db, job_id, "info", message, row[0])

    def events(self, job_id: str, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
        self.get(job_id)
        validate_page(limit, after, maximum=500)
        with self.connection() as db:
            rows = db.execute("SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
                              (job_id, after, limit)).fetchall()
        return {"items": [dict(row) for row in rows], "next_cursor": rows[-1]["id"] if rows else after}

    def recover(self) -> builtins.list[dict[str, Any]]:
        with self.connection() as db:
            running = db.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
        for row in running:
            self.transition(row["id"], {"running"}, "failed", "服务中断，任务未完成；可重新执行",
                            error={"code": "INTERRUPTED", "message": "上次运行被中断，结果未被认定为完成"})
        with self.connection() as db:
            queued = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id").fetchall()
        return [self._decode(row) for row in queued]

    def add_upload(self, upload_id: str, filename: str, size: int, sha256: str) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("INSERT INTO uploads VALUES(?,?,?,?,?)", (upload_id, filename, size, sha256, timestamp()))
        return {"id": upload_id, "filename": filename, "size": size, "sha256": sha256}

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if row is None:
            raise WorkbenchError("UPLOAD_NOT_FOUND", "上传文件不存在或已清理")
        return dict(row)
