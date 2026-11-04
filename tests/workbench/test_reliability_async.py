"""SQLite contention must not freeze the event loop or lose accepted mutations."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import ModuleResult, ModuleSpec, RunContext, WorkbenchError
from reachscope_workbench.core.registry import ModuleRegistry
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.core.runner import JobRunner


class Module:
    spec = ModuleSpec("test", "Fixture", "Contention fixture", [], ["demo"])

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"mode": "demo", "value": config.get("value", 1)}

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        return ModuleResult("test", "fixture", {"value": config["value"]})


def make_runner(path: Path, capacity: int = 100, module: Module | None = None) -> tuple[JobRepository, JobRunner]:
    repository = JobRepository(path / "state.sqlite3")
    return repository, JobRunner(repository, ModuleRegistry([module or Module()]), path, capacity=capacity)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "cancel", "retry"])
async def test_writer_contention_does_not_block_async_heartbeat(tmp_path: Path, operation: str) -> None:
    repository, runner = make_runner(tmp_path)
    original = runner.submit("test", "Original", {}) if operation in {"cancel", "retry"} else None
    if operation == "retry":
        assert original is not None
        repository.transition(original["id"], {"queued"}, "completed", "done", result={})
    writer = sqlite3.connect(repository.path, timeout=2)
    writer.execute("BEGIN IMMEDIATE")
    try:
        if operation == "submit":
            pending = asyncio.create_task(runner.submit_async("test", "New", {}, idempotency_key="new"))
        elif operation == "cancel":
            assert original is not None
            pending = asyncio.create_task(runner.cancel_async(original["id"]))
        else:
            assert original is not None
            pending = asyncio.create_task(runner.retry_async(original["id"], idempotency_key="retry"))
        # A synchronous sqlite write wait blocks this timer until its 10s timeout.
        # With the async API this real heartbeat runs while the writer still owns
        # its lock, and the mutation remains pending instead of timing out early.
        ticks = 0
        for _ in range(5):
            await asyncio.wait_for(asyncio.sleep(.01), timeout=.3)
            ticks += 1
        assert ticks == 5 and not pending.done()
    finally:
        writer.rollback()
        writer.close()
    result = await asyncio.wait_for(pending, 3)
    assert result["status"] == ("cancelled" if operation == "cancel" else "queued")


@pytest.mark.asyncio
async def test_parallel_async_replays_consume_only_one_queue_slot(tmp_path: Path) -> None:
    repository, runner = make_runner(tmp_path, capacity=1)
    results = await asyncio.gather(*[
        runner.submit_async("test", "Same", {}, idempotency_key="same") for _ in range(8)
    ])
    assert len({row["id"] for row in results}) == 1 and runner.queue.qsize() == 1
    assert repository.list()["total"] == 1
    replay = await runner.submit_async("test", "Same", {"value": 1}, idempotency_key="same")
    assert replay["id"] == results[0]["id"]
    with pytest.raises(WorkbenchError) as failure:
        await runner.submit_async("test", "Overflow", {}, idempotency_key="other")
    assert failure.value.code == "QUEUE_FULL" and repository.list()["total"] == 1


@pytest.mark.asyncio
async def test_client_cancellation_cannot_strand_committed_submission(tmp_path: Path) -> None:
    repository, runner = make_runner(tmp_path)
    writer = sqlite3.connect(repository.path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        pending = asyncio.create_task(runner.submit_async("test", "Lost response", {}, idempotency_key="lost"))
        for _ in range(100):
            if runner._reserved:
                break
            await asyncio.sleep(.002)
        assert runner._reserved == 1
        pending.cancel()
        await asyncio.sleep(.02)
        assert not pending.done()
    finally:
        writer.rollback()
        writer.close()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 3)
    replay = await runner.submit_async("test", "Lost response", {}, idempotency_key="lost")
    assert runner.queue.qsize() == repository.list()["total"] == 1
    assert replay["status"] == "queued" and runner._reserved == 0


@pytest.mark.asyncio
async def test_sync_compatibility_cannot_steal_a_reserved_async_queue_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, runner = make_runner(tmp_path, capacity=1)
    entered, release = threading.Event(), threading.Event()
    original = runner._persist

    def gated(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], bool]:
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "_persist", gated)
    pending = asyncio.create_task(runner.submit_async("test", "Async", {}, idempotency_key="async"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        with pytest.raises(WorkbenchError) as failure:
            runner.submit("test", "Sync", {})
        assert failure.value.code == "QUEUE_FULL"
    finally:
        release.set()
    await asyncio.wait_for(pending, 3)
    assert runner.queue.qsize() == repository.list()["total"] == 1


@pytest.mark.asyncio
async def test_shutdown_waits_for_a_pending_submission_before_finishing(tmp_path: Path) -> None:
    repository, runner = make_runner(tmp_path)
    writer = sqlite3.connect(repository.path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        pending = asyncio.create_task(runner.submit_async("test", "Accepted", {}, idempotency_key="accepted"))
        for _ in range(100):
            if runner._reserved:
                break
            await asyncio.sleep(.002)
        assert runner._reserved == 1
        stopping = asyncio.create_task(runner.stop())
        await asyncio.sleep(.03)
        assert not stopping.done()
    finally:
        writer.rollback()
        writer.close()
    accepted = await asyncio.wait_for(pending, 3)
    await asyncio.wait_for(stopping, 3)
    assert runner.stopping and repository.get(accepted["id"])["status"] == "queued"
    await runner.start()
    await asyncio.wait_for(runner.queue.join(), 3)
    await runner.stop()
    assert repository.get(accepted["id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_async_cancel_is_idempotent_and_still_cancels_active_coroutine(tmp_path: Path) -> None:
    started, cleaned = asyncio.Event(), asyncio.Event()

    class SlowModule(Module):
        async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
            started.set()
            try:
                await asyncio.sleep(30)
                return await super().run(config, context)
            finally:
                cleaned.set()

    repository, runner = make_runner(tmp_path, module=SlowModule())
    await runner.start()
    try:
        run = await runner.submit_async("test", "Running", {})
        await asyncio.wait_for(started.wait(), 3)
        cancelled = await runner.cancel_async(run["id"])
        await asyncio.wait_for(cleaned.wait(), 3)
        await asyncio.wait_for(runner.queue.join(), 3)
        assert await runner.cancel_async(run["id"]) == cancelled
        assert repository.get(run["id"])["status"] == "cancelled"
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_cancelled_half_start_cleans_spawned_workers(tmp_path: Path) -> None:
    class SlowModule(Module):
        async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
            await asyncio.sleep(30)
            return await super().run(config, context)

    repository, runner = make_runner(tmp_path, capacity=1, module=SlowModule())
    for index in range(8):
        repository.create("test", f"Pending {index}", {})
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(runner.start(), .05)
    assert not runner.workers and not runner.active and runner.stopping
    assert all(item["status"] != "running" for item in repository.list()["items"])


@pytest.mark.asyncio
async def test_thread_progress_is_ordered_and_drained_before_completion(tmp_path: Path) -> None:
    class ProgressModule(Module):
        async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
            def emit() -> None:
                context.progress(20, "thread first")
                context.progress(70, "thread second")
                context.progress(30, "thread late")
            await asyncio.to_thread(emit)
            return ModuleResult("test", "fixture", {"done": True})

    repository, runner = make_runner(tmp_path, module=ProgressModule())
    await runner.start()
    try:
        run = await runner.submit_async("test", "Thread progress", {})
        await asyncio.wait_for(runner.queue.join(), 3)
        events = repository.events(run["id"])["items"]
        assert [event["message"] for event in events] == ["任务已创建", "开始分析", "thread first", "thread second", "thread late", "分析完成"]
        assert [event["progress"] for event in events] == [0, 0, 20, 70, 70, 100]
        assert repository.get(run["id"])["status"] == "completed"
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_worker_progress_contention_keeps_heartbeat_and_cancellation_responsive(tmp_path: Path) -> None:
    started, emit, emitted = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class ProgressModule(Module):
        async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
            started.set()
            await emit.wait()
            await asyncio.to_thread(context.progress, 60, "thread progress waits for storage")
            emitted.set()
            await asyncio.sleep(30)
            return await super().run(config, context)

    repository, runner = make_runner(tmp_path, module=ProgressModule())
    await runner.start()
    try:
        run = await runner.submit_async("test", "Progress contention", {})
        await asyncio.wait_for(started.wait(), 3)
        writer = sqlite3.connect(repository.path)
        writer.execute("BEGIN IMMEDIATE")
        try:
            emit.set()
            await asyncio.wait_for(emitted.wait(), 1)
            cancelling = asyncio.create_task(runner.cancel_async(run["id"]))
            for _ in range(5):
                await asyncio.wait_for(asyncio.sleep(.01), timeout=.3)
            assert not cancelling.done()
        finally:
            writer.rollback()
            writer.close()
        result = await asyncio.wait_for(cancelling, 3)
        await asyncio.wait_for(runner.queue.join(), 3)
        assert result["status"] == repository.get(run["id"])["status"] == "cancelled"
        assert all(event["message"] != "分析完成" for event in repository.events(run["id"])["items"])
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_pending_worker_transition_without_late_running_state(tmp_path: Path) -> None:
    repository, runner = make_runner(tmp_path)
    run = repository.create("test", "Waiting to start", {})
    writer = sqlite3.connect(repository.path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        await runner.start()
        for _ in range(100):
            if runner.active:
                break
            await asyncio.sleep(.002)
        assert runner.active
        stopping = asyncio.create_task(runner.stop())
        for _ in range(5):
            await asyncio.wait_for(asyncio.sleep(.01), timeout=.3)
        assert not stopping.done()
    finally:
        writer.rollback()
        writer.close()
    await asyncio.wait_for(stopping, 3)
    final = repository.get(run["id"])
    assert final["status"] == "failed" and final["error"]["code"] == "INTERRUPTED"
    assert not runner.workers and not runner.active
