"""Upload persistence remains responsive and consistent under local contention."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from reachscope_workbench.api.app import create_app

HEADERS = {"X-ReachScope-Client": "workbench"}


@pytest.mark.asyncio
async def test_upload_sqlite_wait_does_not_block_health_or_event_loop(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path)
    repository = app.state.repository
    entered = threading.Event()
    original = repository.add_upload

    def observed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        entered.set()
        return original(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(repository, "add_upload", observed)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=HEADERS,
    ) as client:
        writer = sqlite3.connect(repository.path)
        writer.execute("BEGIN IMMEDIATE")
        pending = asyncio.create_task(client.post("/api/uploads", files={"file": ("input.json", b'{"fixture":true}')}))
        try:
            assert await asyncio.to_thread(entered.wait, 2), "Upload did not reach persistence"
            for _ in range(5):
                await asyncio.wait_for(asyncio.sleep(.01), .3)
            assert not pending.done(), "The upload should still be waiting for the writer"
            health = await asyncio.wait_for(client.get("/api/health"), .3)
            assert health.status_code == 200 and health.json()["ready"]
        finally:
            writer.rollback()
            writer.close()
        response = await asyncio.wait_for(pending, 3)
        assert response.status_code == 201, response.text
        saved = response.json()
        data = (tmp_path / "uploads" / saved["id"]).read_bytes()
        assert repository.get_upload(saved["id"])["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_cancelled_upload_response_does_not_remove_committed_file(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path)
    repository = app.state.repository
    committed, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = repository.add_upload
    saved: list[dict[str, Any]] = []

    def paused_after_commit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        saved.append(result)
        committed.set()
        try:
            assert release.wait(5), "Test did not release the committed upload"
            return result  # type: ignore[no-any-return]
        finally:
            finished.set()

    monkeypatch.setattr(repository, "add_upload", paused_after_commit)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=HEADERS,
    ) as client:
        pending = asyncio.create_task(client.post("/api/uploads", files={"file": ("input.json", b'{"fixture":true}')}))
        try:
            assert await asyncio.to_thread(committed.wait, 2)
            pending.cancel()
            await asyncio.sleep(.02)
            assert repository.get_upload(saved[0]["id"])["size"] == len(b'{"fixture":true}')
            assert (tmp_path / "uploads" / saved[0]["id"]).read_bytes() == b'{"fixture":true}'
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 3)
        assert await asyncio.to_thread(finished.wait, 2)
        assert (tmp_path / "uploads" / saved[0]["id"]).is_file()
        assert repository.get_upload(saved[0]["id"])["sha256"] == hashlib.sha256(b'{"fixture":true}').hexdigest()


@pytest.mark.asyncio
async def test_failed_upload_commit_removes_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(app.state.repository, "add_upload", fail)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=HEADERS,
    ) as client:
        response = await client.post("/api/uploads", files={"file": ("input.json", b'{"fixture":true}')})
        assert response.status_code == 503 and response.json()["error"]["code"] == "WORKSPACE_BUSY"
        assert not list((tmp_path / "uploads").iterdir())

