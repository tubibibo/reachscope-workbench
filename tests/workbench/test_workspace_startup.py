"""Schema is rechecked under the lease; WAL refusal is diagnostic only."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.locking import WorkspaceLock
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository


def test_schema_recheck_rejects_changed_or_missing_database(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "workbench.sqlite3")
    assert repo.check_schema_version() == 7
    with repo.connection() as db:
        db.execute("UPDATE schema_meta SET version=8")
    with pytest.raises(WorkbenchError, match="unsupported") as caught:
        repo.check_schema_version()
    assert caught.value.code == "SCHEMA_UNSUPPORTED"
    repo.path.unlink()
    with pytest.raises(WorkbenchError) as caught:
        repo.check_schema_version()
    assert caught.value.code == "SCHEMA_UNSUPPORTED"
    assert not repo.path.exists()


def test_lifespan_rechecks_schema_and_releases_lease(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with sqlite3.connect(tmp_path / "workbench.sqlite3") as db:
        db.execute("UPDATE schema_meta SET version=8")
    with pytest.raises(WorkbenchError) as caught, TestClient(app):
        pytest.fail("future schema must prevent startup")
    assert caught.value.code == "SCHEMA_UNSUPPORTED"
    lease = WorkspaceLock(tmp_path)
    lease.acquire()
    lease.release()
    with sqlite3.connect(tmp_path / "workbench.sqlite3") as db:
        db.execute("UPDATE schema_meta SET version=7")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/modules").status_code == 200


def test_wal_refusal_logs_actual_mode(caplog: pytest.LogCaptureFixture) -> None:
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = ("delete",)
    JobRepository._enable_wal(db)
    assert "delete" in caplog.text and "WAL" in caplog.text


def test_normal_database_uses_wal(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "state.sqlite3")
    with repo.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
