"""Durable lifecycle behavior, cancellation and restart contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.locking import WorkspaceLock
from reachscope_workbench.core.models import ModuleResult, ModuleSpec, RunContext, WorkbenchError
from reachscope_workbench.core.registry import ModuleRegistry
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.core.runner import JobRunner


class FakeModule:
    spec = ModuleSpec("test", "Test", "Lifecycle module", ["test"], ["test"])

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        if config.get("invalid"):
            raise WorkbenchError("BAD_CONFIG", "Invalid test configuration")
        return config

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        self.started.set()
        context.progress(40, "Collected evidence")
        try:
            if config.get("wait"):
                await asyncio.sleep(30)
            if config.get("fail"):
                raise WorkbenchError("TEST_FAILURE", "Module explicitly failed")
            return ModuleResult("test", "local", {"count": 1})
        finally:
            self.cleaned.set()


def test_repository_reopens_results_and_events(tmp_path: Path) -> None:
    db = JobRepository(tmp_path / "db.sqlite3")
    job = db.create("test", "job", {"value": "<script>"})
    assert db.transition(job["id"], {"queued"}, "running", "start")
    db.progress(job["id"], 30, "step")
    db.progress(job["id"], 20, "older callback")
    assert db.get(job["id"])["progress"] == 30
    assert db.transition(job["id"], {"running"}, "completed", "done", result={"answer": 1})
    reopened = JobRepository(tmp_path / "db.sqlite3")
    assert reopened.get(job["id"])["result"] == {"answer": 1}
    assert reopened.get(job["id"])["progress"] == 100
    assert len(reopened.events(job["id"])["items"]) == 5
    assert reopened.list()["items"][0]["config"]["value"] == "<script>"
    assert "result" not in reopened.list()["items"][0]
    assert not db.transition(job["id"], {"running"}, "failed", "late callback")
    with pytest.raises(WorkbenchError):
        db.list(limit=500)


def test_recovery_marks_interrupted_without_claiming_success(tmp_path: Path) -> None:
    db = JobRepository(tmp_path / "db.sqlite3")
    running = db.create("test", "running", {})
    queued = db.create("test", "queued", {})
    db.transition(running["id"], {"queued"}, "running", "start")
    recovered = db.recover()
    assert [item["id"] for item in recovered] == [queued["id"]]
    assert db.get(running["id"])["error"]["code"] == "INTERRUPTED"


@pytest.mark.asyncio
async def test_runner_completes_fails_and_retries(tmp_path: Path) -> None:
    db = JobRepository(tmp_path / "db.sqlite3")
    module = FakeModule()
    runner = JobRunner(db, ModuleRegistry([module]), tmp_path)
    await runner.start()
    try:
        success = runner.submit("test", "Success", {})
        failure = runner.submit("test", "Failure", {"fail": True})
        await asyncio.wait_for(runner.queue.join(), 5)
        assert db.get(success["id"])["status"] == "completed"
        assert db.get(failure["id"])["error"]["code"] == "TEST_FAILURE"
        retry = runner.retry(success["id"])
        assert retry["id"] != success["id"]
        await asyncio.wait_for(runner.queue.join(), 5)
        with pytest.raises(WorkbenchError):
            runner.cancel(success["id"])
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_cancel_cleans_module_and_never_finishes_late(tmp_path: Path) -> None:
    db = JobRepository(tmp_path / "db.sqlite3")
    module = FakeModule()
    runner = JobRunner(db, ModuleRegistry([module]), tmp_path, concurrency=1)
    await runner.start()
    try:
        job = runner.submit("test", "Wait", {"wait": True})
        await asyncio.wait_for(module.started.wait(), 3)
        runner.cancel(job["id"])
        await asyncio.wait_for(module.cleaned.wait(), 3)
        await asyncio.wait_for(runner.queue.join(), 3)
        assert db.get(job["id"])["status"] == "cancelled"
        assert db.get(job["id"])["result"] is None
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_capacity_and_queued_cancellation(tmp_path: Path) -> None:
    db = JobRepository(tmp_path / "db.sqlite3")
    runner = JobRunner(db, ModuleRegistry([FakeModule()]), tmp_path, capacity=1)
    job = runner.submit("test", "queued", {})
    with pytest.raises(WorkbenchError, match="队列"):
        runner.submit("test", "too many", {})
    assert db.list()["total"] == 1
    runner.cancel(job["id"])
    await runner.start()
    await asyncio.wait_for(runner.queue.join(), 3)
    await runner.stop()
    assert db.get(job["id"])["status"] == "cancelled"


def test_workspace_lock_has_one_owner_and_releases(tmp_path: Path) -> None:
    first, second = WorkspaceLock(tmp_path), WorkspaceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(WorkbenchError):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_registry_duplicate_and_unknown_are_errors() -> None:
    with pytest.raises(ValueError):
        ModuleRegistry([FakeModule(), FakeModule()])
    with pytest.raises(WorkbenchError):
        ModuleRegistry([]).get("missing")
