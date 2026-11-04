"""Lost responses, restarts and contention preserve one durable inspection request."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.locking import WorkspaceLock
from reachscope_workbench.core.models import ModuleResult, ModuleSpec, RunContext, WorkbenchError
from reachscope_workbench.core.registry import ModuleRegistry
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.core.runner import JobRunner


class Module:
    spec = ModuleSpec("test", "Fixture", "Real lifecycle fixture", [], ["demo"])

    def __init__(self) -> None:
        self.runs = 0

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"mode": "demo", "value": config.get("value", 1)}

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        self.runs += 1
        return ModuleResult("test", "fixture", {"value": config["value"]})


def runner_at(path: Path, capacity: int = 100) -> tuple[JobRepository, JobRunner, Module]:
    repository, module = JobRepository(path / "state.sqlite3"), Module()
    return repository, JobRunner(repository, ModuleRegistry([module]), path, capacity=capacity), module


def test_lost_response_replay_survives_reopen_and_full_queue(tmp_path: Path) -> None:
    repository, runner, _ = runner_at(tmp_path, capacity=1)
    original = runner.submit("test", "Inspection", {}, idempotency_key="request-1")
    assert runner.queue.full()
    replay = runner.submit("test", "Inspection", {"value": 1}, idempotency_key="request-1")
    assert replay["id"] == original["id"] and runner.queue.qsize() == 1
    reopened, restarted, _ = runner_at(tmp_path, capacity=1)
    assert restarted.submit("test", "Inspection", {}, idempotency_key="request-1")["id"] == original["id"]
    assert restarted.queue.qsize() == 0
    assert repository.list()["total"] == reopened.list()["total"] == 1


@pytest.mark.parametrize("name,config", [("Different", {}), ("Inspection", {"value": 2})])
def test_request_key_conflict_never_creates_extra_job(tmp_path: Path, name: str, config: dict[str, Any]) -> None:
    repository, runner, _ = runner_at(tmp_path)
    runner.submit("test", "Inspection", {}, idempotency_key="shared")
    with pytest.raises(WorkbenchError) as failure:
        runner.submit("test", name, config, idempotency_key="shared")
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"
    assert repository.list()["total"] == runner.queue.qsize() == 1


@pytest.mark.asyncio
async def test_runner_restarts_without_duplicate_recovery_and_keeps_new_work_available(tmp_path: Path) -> None:
    repository, runner, module = runner_at(tmp_path, capacity=1)
    first = runner.submit("test", "Before start", {})
    await asyncio.wait_for(runner.start(), 3)
    with pytest.raises(WorkbenchError) as failure:
        await runner.start()
    assert failure.value.code == "RUNNER_ACTIVE"
    await asyncio.wait_for(runner.queue.join(), 3)
    assert module.runs == 1 and repository.get(first["id"])["status"] == "completed"
    await runner.stop()
    await runner.start()
    second = runner.submit("test", "After restart", {})
    await asyncio.wait_for(runner.queue.join(), 3)
    await runner.stop()
    assert module.runs == 2 and repository.get(second["id"])["status"] == "completed"


def test_runner_lifespan_can_restart_on_a_new_event_loop(tmp_path: Path) -> None:
    repository, runner, module = runner_at(tmp_path)

    async def lifespan(name: str) -> str:
        await runner.start()
        run = runner.submit("test", name, {})
        await asyncio.wait_for(runner.queue.join(), 3)
        # Let an idle worker bind its next queue read to this lifespan's loop.
        await asyncio.sleep(0)
        await runner.stop()
        return str(run["id"])

    first = asyncio.run(lifespan("First lifespan"))
    second = asyncio.run(lifespan("Second lifespan"))
    assert module.runs == 2 and first != second
    assert repository.get(second)["status"] == "completed"


@pytest.mark.asyncio
async def test_retry_request_is_durable_but_distinct_from_original_submission(tmp_path: Path) -> None:
    repository, runner, module = runner_at(tmp_path)
    await runner.start()
    try:
        original = runner.submit("test", "Work", {}, idempotency_key="original")
        await asyncio.wait_for(runner.queue.join(), 3)
        retry = runner.retry(original["id"], idempotency_key="retry-1")
        assert retry["id"] != original["id"]
        assert runner.retry(original["id"], idempotency_key="retry-1")["id"] == retry["id"]
        with pytest.raises(WorkbenchError) as failure:
            runner.retry(original["id"], idempotency_key="original")
        assert failure.value.code == "IDEMPOTENCY_CONFLICT"
        await asyncio.wait_for(runner.queue.join(), 3)
        assert module.runs == 2 and repository.list()["total"] == 2
    finally:
        await runner.stop()


def test_cancel_can_be_repeated_without_changing_terminal_event_log(tmp_path: Path) -> None:
    repository, runner, _ = runner_at(tmp_path)
    run = runner.submit("test", "Cancel", {})
    cancelled = runner.cancel(run["id"])
    count = len(repository.events(run["id"])["items"])
    assert runner.cancel(run["id"]) == cancelled
    assert len(repository.events(run["id"])["items"]) == count
    finished = repository.create("test", "Finished", {})
    repository.transition(finished["id"], {"queued"}, "completed", "done", result={})
    with pytest.raises(WorkbenchError) as failure:
        runner.cancel(finished["id"])
    assert failure.value.code == "JOB_TERMINAL"


def test_progress_event_percent_never_regresses_or_updates_terminal_work(tmp_path: Path) -> None:
    repository, _, _ = runner_at(tmp_path)
    run = repository.create("test", "Progress", {})
    repository.transition(run["id"], {"queued"}, "running", "start")
    repository.progress(run["id"], 70, "New callback")
    repository.progress(run["id"], 20, "Late callback")
    assert repository.get(run["id"])["progress"] == 70
    assert repository.events(run["id"])["items"][-1]["progress"] == 70
    repository.transition(run["id"], {"running"}, "completed", "done", result={})
    events = repository.events(run["id"])["items"]
    repository.progress(run["id"], 90, "Too late")
    assert repository.events(run["id"])["items"] == events


def test_parallel_duplicate_request_creates_one_job_and_one_event(tmp_path: Path) -> None:
    repository, _, _ = runner_at(tmp_path)

    def submit(_: int) -> tuple[str, bool]:
        run, created = repository.create_idempotent("test", "Parallel", {}, request_key="concurrent", request_fingerprint="same")
        return run["id"], created

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, range(8)))
    assert len({run_id for run_id, _ in results}) == 1 and sum(created for _, created in results) == 1
    assert repository.list()["total"] == 1
    assert len(repository.events(results[0][0])["items"]) == 1


@pytest.mark.parametrize("version", [1, 2])
def test_migration_preserves_legacy_state_and_key_replay(tmp_path: Path, version: int) -> None:
    repository, _, _ = runner_at(tmp_path)
    run = repository.create("test", "Retained", {})
    with repository.connection() as db:
        db.execute("DROP TABLE job_requests")
        db.execute("DROP TABLE asset_requests")
        db.execute("UPDATE schema_meta SET version=?", (version,))
    upgraded = JobRepository(repository.path)
    assert upgraded.get(run["id"])["name"] == "Retained"
    with upgraded.connection() as db:
        assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 7
    keyed, created = upgraded.create_idempotent("test", "New", {}, request_key="new", request_fingerprint="value")
    assert created and upgraded.request_job("new", "value")["id"] == keyed["id"]


def test_future_database_is_rejected_without_ddl_or_journal_changes(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES(999)")
        connection.execute("CREATE TABLE future_data(value TEXT)")
        connection.execute("INSERT INTO future_data VALUES('must remain untouched')")
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(WorkbenchError) as failure:
        JobRepository(path)
    assert failure.value.code == "SCHEMA_UNSUPPORTED"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not path.with_name(path.name + "-wal").exists()


def test_migration_ddl_rolls_back_when_an_existing_table_is_incompatible(tmp_path: Path) -> None:
    path = tmp_path / "incompatible.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES(1)")
        connection.execute("CREATE TABLE jobs(old_column TEXT)")
        connection.execute("INSERT INTO jobs VALUES('retain this row')")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(sqlite3.DatabaseError):
        JobRepository(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 1
        assert connection.execute("SELECT old_column FROM jobs").fetchone()[0] == "retain this row"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"schema_meta", "jobs"}
    finally:
        connection.close()


@pytest.mark.parametrize("asset_page", [False, True])
def test_paged_count_and_rows_use_one_snapshot_during_another_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asset_page: bool,
) -> None:
    repository, _, _ = runner_at(tmp_path)
    inventory = AssetRepository(repository)
    repository.create("test", "Original", {})
    inventory.create("cloud", "Original", {"profile_id": "cloud-demo", "mode": "demo"})
    writer = JobRepository(repository.path)
    original_connection = repository.connection
    triggered = False

    @contextmanager
    def traced_connection() -> Iterator[sqlite3.Connection]:
        nonlocal triggered
        with original_connection() as connection:
            def during_query(statement: str) -> None:
                nonlocal triggered
                is_page = statement.startswith("SELECT a.*,COUNT") if asset_page else statement.startswith("SELECT j.id,j.module")
                if not triggered and is_page:
                    triggered = True
                    if asset_page:
                        AssetRepository(writer).create("cloud", "Concurrent", {"mode": "demo", "profile_id": "cloud-demo"})
                    else:
                        writer.create("test", "Concurrent", {})
            connection.set_trace_callback(during_query)
            yield connection

    monkeypatch.setattr(repository, "connection", traced_connection)
    page = inventory.list() if asset_page else repository.list()
    assert triggered and page["total"] == len(page["items"]) == 1
    assert (AssetRepository(writer).list() if asset_page else writer.list())["total"] == 2


def test_replay_does_not_recheck_a_deleted_upload(tmp_path: Path) -> None:
    class UploadedModule(Module):
        def validate(self, config: dict[str, Any]) -> dict[str, Any]:
            return {"mode": "demo", "upload_id": config["upload_id"]}

    repository, _, _ = runner_at(tmp_path)
    upload_id = "a" * 32
    repository.add_upload(upload_id, "sample.json", 1, "digest")
    runner = JobRunner(repository, ModuleRegistry([UploadedModule()]), tmp_path)
    original = runner.submit("test", "Uploaded", {"upload_id": upload_id}, idempotency_key="upload-request")
    with repository.connection() as connection:
        connection.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
    replay = runner.replay("test", "Uploaded", {"upload_id": upload_id}, idempotency_key="upload-request")
    assert replay is not None and replay["id"] == original["id"]
    assert runner.submit("test", "Uploaded", {"upload_id": upload_id}, idempotency_key="upload-request")["id"] == original["id"]
    assert runner.replay("test", "Uploaded", {"upload_id": upload_id}) is None


def test_workspace_lock_reacquire_does_not_lose_ownership(tmp_path: Path) -> None:
    lock, other = WorkspaceLock(tmp_path), WorkspaceLock(tmp_path)
    lock.acquire()
    with pytest.raises(WorkbenchError):
        lock.acquire()
    with pytest.raises(WorkbenchError):
        other.acquire()
    lock.release()
    other.acquire()
    other.release()


def test_asset_lost_response_replay_and_conflict_survive_restart(tmp_path: Path) -> None:
    repository, _, _ = runner_at(tmp_path)
    inventory = AssetRepository(repository)
    source = {"mode": "demo", "profile_id": "cloud-demo"}
    first = inventory.create("cloud", " Asset ", source, idempotency_key="asset-request")
    reopened = AssetRepository(JobRepository(repository.path))
    replay = reopened.create("cloud", "Asset", dict(reversed(list(source.items()))), idempotency_key="asset-request")
    assert replay["id"] == first["id"] and reopened.list()["total"] == 1
    with pytest.raises(WorkbenchError) as failure:
        reopened.create("cloud", "Different", source, idempotency_key="asset-request")
    assert failure.value.code == "IDEMPOTENCY_CONFLICT" and inventory.list()["total"] == 1


def test_asset_parallel_lost_responses_return_one_saved_input(tmp_path: Path) -> None:
    repository, _, _ = runner_at(tmp_path)
    inventory = AssetRepository(repository)

    def create(_: int) -> str:
        return str(inventory.create("website", "Same", {"profile_id": "website-demo", "mode": "demo"},
                                    idempotency_key="concurrent-asset")["id"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        identifiers = list(executor.map(create, range(8)))
    assert len(set(identifiers)) == 1 and inventory.list()["total"] == 1


def test_asset_limit_does_not_block_existing_request_replay(tmp_path: Path) -> None:
    repository, _, _ = runner_at(tmp_path)
    inventory = AssetRepository(repository)
    source = {"profile_id": "cloud-demo", "mode": "demo"}
    original = inventory.create("cloud", "Same", source, idempotency_key="asset-request")
    with repository.connection() as db:
        db.executemany("INSERT INTO assets(id,kind,name,source,created_at,updated_at) VALUES(?,?,?,?,?,?)", [
            (f"fixture-{index}", "cloud", "Other", "{}", "2026-11-01", "2026-11-01") for index in range(4999)
        ])
    assert inventory.create("cloud", "Same", source, idempotency_key="asset-request")["id"] == original["id"]
    with pytest.raises(WorkbenchError) as failure:
        inventory.create("cloud", "New", source, idempotency_key="new-asset")
    assert failure.value.code == "ASSET_LIMIT"
