"""Schema 6 adds origin metadata without rewriting or reclassifying history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.locking import WorkspaceLock
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.integrations.local_lab import LocalLab

ASSET_ID = "a" * 32
JOB_ID = "b" * 32
CREATED = "2026-10-31T10:00:00.000+00:00"
FINISHED = "2026-10-31T10:01:00.000+00:00"
SOURCE = {"profile_id": "website-probe", "mode": "probe", "targets": ["http://127.0.0.1:12345/"], "allow_private": True}
PROVENANCE = {"kind": "local_training", "label": "Managed local teaching session", "session_id": "c" * 32}


def legacy_v5(path: Path) -> dict[str, Any]:
    """Build an actual six-column assets table, not just relabel a new DB."""
    source = json.dumps(SOURCE, ensure_ascii=False, indent=2)
    snapshot = json.dumps({"id": ASSET_ID, "kind": "website", "name": "本地教学 / User label alone is not provenance", "source": SOURCE},
                          ensure_ascii=False, indent=2)
    config = json.dumps({key: value for key, value in SOURCE.items() if key != "profile_id"}, indent=2)
    result = json.dumps({"module": "web", "target": SOURCE["targets"][0], "summary": {"mode": "probe"},
                         "evidence": [], "details": {}, "limitations": ["Legacy saved fixture; no HTTP request executed"]}, indent=2)
    asset_row = (ASSET_ID, "website", "本地教学 / User label alone is not provenance", source, CREATED, CREATED)
    job_row = (JOB_ID, "web", "Legacy saved job", config, "completed", 100, "Legacy complete", CREATED, FINISHED, None, result)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE schema_meta(version INTEGER NOT NULL);
            INSERT INTO schema_meta VALUES(5);
            CREATE TABLE assets(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,
                source TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,module TEXT NOT NULL,name TEXT NOT NULL,config TEXT NOT NULL,
                status TEXT NOT NULL,progress INTEGER NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,error TEXT,result TEXT);
            CREATE TABLE job_assets(job_id TEXT PRIMARY KEY REFERENCES jobs(id),asset_id TEXT NOT NULL REFERENCES assets(id),snapshot TEXT NOT NULL);
            CREATE TABLE job_requests(key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES jobs(id));
            CREATE TABLE uploads(id TEXT PRIMARY KEY,filename TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(id),
                created_at TEXT NOT NULL,level TEXT NOT NULL,message TEXT NOT NULL,progress INTEGER NOT NULL);
        """)
        connection.execute("INSERT INTO assets VALUES(?,?,?,?,?,?)", asset_row)
        connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)", job_row)
        connection.execute("INSERT INTO job_assets VALUES(?,?,?)", (JOB_ID, ASSET_ID, snapshot))
        connection.execute("INSERT INTO job_requests VALUES(?,?,?)", ("legacy-request", "legacy-fingerprint", JOB_ID))
        connection.execute("INSERT INTO uploads VALUES(?,?,?,?,?)", ("d" * 32, "legacy-input.json", 2, hashlib.sha256(b"{}").hexdigest(), CREATED))
        connection.execute("INSERT INTO events(job_id,created_at,level,message,progress) VALUES(?,?,?,?,?)",
                           (JOB_ID, FINISHED, "info", "Legacy complete", 100))
        assert len(connection.execute("PRAGMA table_info(assets)").fetchall()) == 6
    return {"asset": asset_row, "job": job_row, "snapshot": snapshot}


def test_actual_v5_assets_and_job_snapshot_survive_additive_schema7(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    before = legacy_v5(path)
    repository = JobRepository(path)
    with repository.connection() as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 7
        assert tuple(connection.execute("SELECT * FROM assets WHERE id=?", (ASSET_ID,)).fetchone()) == (*before["asset"], None)
        assert tuple(connection.execute("SELECT * FROM jobs WHERE id=?", (JOB_ID,)).fetchone()) == before["job"]
        assert connection.execute("SELECT snapshot FROM job_assets WHERE job_id=?", (JOB_ID,)).fetchone()[0] == before["snapshot"]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    asset = AssetRepository(repository).get(ASSET_ID)
    assert asset["source"] == SOURCE and asset["provenance"] is None and asset["job_count"] == 1
    job = repository.get(JOB_ID)
    assert "provenance" not in job["asset_snapshot"], "Migration must not fabricate origin for old snapshots"
    assert job["asset_snapshot"] == json.loads(before["snapshot"])
    assert repository.request_job("legacy-request", "legacy-fingerprint")["id"] == JOB_ID  # type: ignore[index]
    assert repository.events(JOB_ID)["items"][0]["message"] == "Legacy complete"
    assert repository.get_upload("d" * 32)["filename"] == "legacy-input.json"
    reopened = JobRepository(path)
    assert AssetRepository(reopened).get(ASSET_ID)["provenance"] is None
    assert reopened.get(JOB_ID)["asset_snapshot"] == json.loads(before["snapshot"])


def test_new_trusted_origin_is_snapshotted_and_never_rewritten_by_replay(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "state.sqlite3")
    assets = AssetRepository(repository)
    original = assets.create("website", "Local teaching", SOURCE, idempotency_key="same-asset", provenance=PROVENANCE)
    job, created = repository.create_idempotent("web", "Teaching baseline", {"mode": "probe"}, asset=original,
                                              request_key="same-job", request_fingerprint="immutable-job-request")
    assert created and original["provenance"] == PROVENANCE and job["asset_snapshot"]["provenance"] == PROVENANCE
    after_job = assets.get(original["id"])
    changed = {**PROVENANCE, "session_id": "e" * 32, "label": "A later runtime session"}
    for incoming in (None, changed):
        replay = assets.create("website", "Local teaching", SOURCE, idempotency_key="same-asset", provenance=incoming)
        assert replay == after_job, "Server runtime origin is not a client request fingerprint or an update command"
        replay_job, created = repository.create_idempotent("web", "Teaching baseline", {"mode": "probe"},
            asset={**original, "provenance": incoming}, request_key="same-job", request_fingerprint="immutable-job-request")
        assert not created and replay_job == job
    assert assets.list()["total"] == repository.list()["total"] == 1
    with repository.connection() as connection:
        assert json.loads(connection.execute("SELECT provenance FROM assets").fetchone()[0]) == PROVENANCE
    reopened = JobRepository(repository.path)
    assert AssetRepository(reopened).get(original["id"])["provenance"] == PROVENANCE
    assert reopened.get(job["id"])["asset_snapshot"]["provenance"] == PROVENANCE


def test_asset_saved_without_origin_stays_unlabelled_when_replayed_in_lab_session(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "state.sqlite3")
    assets = AssetRepository(repository)
    original = assets.create("website", "An earlier ordinary input", SOURCE, idempotency_key="ordinary")
    replayed = assets.create("website", "An earlier ordinary input", SOURCE, idempotency_key="ordinary", provenance=PROVENANCE)
    assert replayed["id"] == original["id"] and replayed["provenance"] is None


def test_future_schema8_rejection_leaves_file_and_journal_mode_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE schema_meta(version INTEGER NOT NULL);
            INSERT INTO schema_meta VALUES(8);
            CREATE TABLE future_values(name TEXT,value BLOB);
            INSERT INTO future_values VALUES('future data',X'00017FFF');
        """)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    original_bytes = path.read_bytes()
    with pytest.raises(WorkbenchError) as failure:
        JobRepository(path)
    assert failure.value.code == "SCHEMA_UNSUPPORTED" and path.read_bytes() == original_bytes
    assert not Path(str(path) + "-wal").exists() and not Path(str(path) + "-shm").exists()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 8
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"schema_meta", "future_values"}


def test_api_replay_preserves_registered_origin_after_lab_stops(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path), headers={"X-ReachScope-Client": "workbench"}) as client:
        started = client.post("/api/lab/start").json()
        headers = {"Idempotency-Key": "registered-once"}
        initial = client.post("/api/assets", json=started["asset_template"], headers=headers)
        assert initial.status_code == 201 and initial.json()["provenance"]["session_id"] == started["session_id"]
        assert client.post("/api/lab/stop").json()["status"] == "stopped"
        replayed = client.post("/api/assets", json=started["asset_template"], headers=headers)
        assert replayed.status_code == 201 and replayed.json() == initial.json()


def test_concurrent_lab_lifecycle_retains_coherent_origins_and_terminates() -> None:
    lab = LocalLab()
    try:
        def mutate(index: int) -> dict[str, Any]:
            return lab.start() if index % 3 else lab.stop()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(mutate, range(36)))
        for item in results:
            assert item["status"] in {"running", "stopped"}
            if item["status"] == "running":
                assert item["session_id"] and item["asset_template"]["source"]["targets"] == [item["url"]]
            else:
                assert item["session_id"] is None and item["url"] is None and item["asset_template"] is None
    finally:
        stopped = lab.stop()
    assert stopped["status"] == "stopped" and lab._server is None and lab._thread is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_component", ["advisory", "runner", "lab"])
async def test_app_shutdown_error_still_stops_lab_and_releases_workspace(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch,
                                                                      failing_component: str) -> None:
    app = create_app(tmp_path)
    component = getattr(app.state, failing_component)
    original_stop = component.stop

    if failing_component == "lab":
        def fail_after_sync_cleanup() -> dict[str, Any]:
            original_stop()
            raise RuntimeError("simulated shutdown failure")

        replacement: Any = fail_after_sync_cleanup
    else:
        async def fail_after_async_cleanup() -> None:
            await original_stop()
            raise RuntimeError("simulated shutdown failure")

        replacement = fail_after_async_cleanup

    with pytest.raises(RuntimeError, match="simulated shutdown failure"):
        async with app.router.lifespan_context(app):
            app.state.lab.start()
            monkeypatch.setattr(component, "stop", replacement)
    assert app.state.lab.status()["status"] == "stopped"
    assert not app.state.runner.workers and not app.state.runner.active
    lease = WorkspaceLock(tmp_path)
    lease.acquire()
    lease.release()
