"""Terminal persistence failures must not consume the worker pool."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import ModuleResult, ModuleSpec, RunContext
from reachscope_workbench.core.registry import ModuleRegistry
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.core.runner import JobRunner


class SuccessfulModule:
    spec = ModuleSpec("fixture", "Fixture", "Persistence fault", [], ["demo"])

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        return config

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        return ModuleResult("fixture", "done", {})


@pytest.mark.parametrize("error", [sqlite3.OperationalError, OSError])
@pytest.mark.parametrize("persistent", [False, True])
async def test_terminal_failure_keeps_worker_and_next_job_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[Exception], persistent: bool,
) -> None:
    repository = JobRepository(tmp_path / "state.sqlite3")
    runner = JobRunner(repository, ModuleRegistry([SuccessfulModule()]), tmp_path, concurrency=1)
    original = repository.transition

    def faulty(job_id: str, expected: set[str], status: str, message: str, **kwargs: Any) -> bool:
        if status != "running" and (persistent or kwargs.get("error", {}).get("code") != "WORKER_ERROR"):
            raise error("injected terminal write failure")
        return original(job_id, expected, status, message, **kwargs)

    monkeypatch.setattr(repository, "transition", faulty)
    await runner.start()
    try:
        for _ in range(2):
            job = runner.submit("fixture", "fault", {})
            await asyncio.wait_for(runner.queue.join(), 1.5)
            assert not runner.workers[0].done()
            result = repository.get(job["id"])
            assert result["status"] == ("running" if persistent else "failed")
            if not persistent:
                assert result["error"]["code"] == "WORKER_ERROR"
    finally:
        await runner.stop()
