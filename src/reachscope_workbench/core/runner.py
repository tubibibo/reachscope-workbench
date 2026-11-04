"""Bounded async execution with durable state and explicit cancellation semantics."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, TypeVar

from .assets import AssetRepository
from .catalog import validate_binding
from .models import RunContext, WorkbenchError
from .registry import ModuleRegistry
from .repository import TERMINAL, JobRepository

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, repository: JobRepository, registry: ModuleRegistry, data_dir: Path,
                 *, concurrency: int = 2, capacity: int = 100) -> None:
        self.repository, self.registry, self.data_dir = repository, registry, data_dir
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=capacity)
        self.concurrency = concurrency
        self.workers: list[asyncio.Task[None]] = []
        self.active: dict[str, asyncio.Task[None]] = {}
        self.stopping = False
        self._submission_lock = asyncio.Lock()
        self._reserved = 0
        (data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    async def start(self) -> None:
        if any(not worker.done() for worker in self.workers) or self._submission_lock.locked():
            raise WorkbenchError("RUNNER_ACTIVE", "任务执行器已经启动")
        # Persisted queued rows are the source of truth after each start. The old
        # in-memory queue may still contain IDs from submissions before start or
        # a previous stop; reusing it would schedule those jobs twice.
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        # A previous lifespan may have bound Queue's waiters to another loop.
        self.queue = asyncio.Queue(maxsize=self.queue.maxsize)
        self._submission_lock = asyncio.Lock()
        self._reserved = 0
        self.stopping = False
        try:
            queued = await asyncio.to_thread(self.repository.recover)
            self.workers = [asyncio.create_task(self._worker()) for _ in range(self.concurrency)]
            for job in queued:
                await self.queue.put(job["id"])
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        self.stopping = True
        # Finish the durable write + loop enqueue of an accepted async request
        # before cancelling workers. Never strand a committed job after a lost
        # client response or let it enqueue after shutdown completed.
        async with self._submission_lock:
            pass
        for task in list(self.active.values()):
            task.cancel()
        if self.active:
            await asyncio.gather(*list(self.active.values()), return_exceptions=True)
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    def submit(self, module_id: str, name: str, config: dict[str, Any], *, asset_id: str | None = None,
               idempotency_key: str | None = None) -> dict[str, Any]:
        return self._submit(module_id, name, config, asset_id=asset_id,
                            idempotency_key=idempotency_key, request_scope="create")

    @staticmethod
    def _fingerprint(module_id: str, name: str, normalized: dict[str, Any], asset_id: str | None,
                     request_scope: str) -> str:
        return hashlib.sha256(json.dumps(
            {"scope": request_scope, "module": module_id, "name": name,
             "config": normalized, "asset_id": asset_id},
            ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    def replay(self, module_id: str, name: str, config: dict[str, Any], *, asset_id: str | None = None,
               idempotency_key: str | None = None) -> dict[str, Any] | None:
        """Resolve a durable create request before checking current input availability."""
        if idempotency_key is None:
            return None
        module = self.registry.get(module_id)
        normalized = module.validate(config)
        fingerprint = self._fingerprint(module_id, name.strip()[:120] or module.spec.name,
                                        normalized, asset_id, "create")
        return self.repository.request_job(idempotency_key, fingerprint)

    def _submit(self, module_id: str, name: str, config: dict[str, Any], *, asset_id: str | None,
                idempotency_key: str | None, request_scope: str) -> dict[str, Any]:
        display_name, normalized, fingerprint, replay = self._prepare(
            module_id, name, config, asset_id, idempotency_key, request_scope)
        if replay is not None:
            return replay
        self._check_capacity()
        job, created = self._persist(module_id, display_name, normalized, asset_id, idempotency_key, fingerprint)
        if created:
            self.queue.put_nowait(job["id"])
        return job

    def _prepare(self, module_id: str, name: str, config: dict[str, Any], asset_id: str | None,
                 idempotency_key: str | None, request_scope: str,
                 ) -> tuple[str, dict[str, Any], str, dict[str, Any] | None]:
        module = self.registry.get(module_id)
        normalized = module.validate(config)
        display_name = name.strip()[:120] or module.spec.name
        fingerprint = self._fingerprint(module_id, display_name, normalized, asset_id, request_scope)
        replay = self.repository.request_job(idempotency_key, fingerprint) if idempotency_key is not None else None
        return display_name, normalized, fingerprint, replay

    def _check_capacity(self) -> None:
        if self.stopping or (self.queue.maxsize > 0 and self.queue.qsize() + self._reserved >= self.queue.maxsize):
            raise WorkbenchError("QUEUE_FULL", "等待队列已满，请稍后再试")

    def _persist(self, module_id: str, display_name: str, normalized: dict[str, Any], asset_id: str | None,
                 idempotency_key: str | None, fingerprint: str) -> tuple[dict[str, Any], bool]:
        upload_id = normalized.get("upload_id")
        if upload_id:
            self.repository.get_upload(upload_id)
        asset = AssetRepository(self.repository).get(asset_id) if asset_id else None
        if asset is not None:
            validate_binding(asset, module_id, normalized)
        if idempotency_key is not None:
            return self.repository.create_idempotent(module_id, display_name, normalized, asset=asset,
                                                    request_key=idempotency_key, request_fingerprint=fingerprint)
        return self.repository.create(module_id, display_name, normalized, asset=asset), True

    @staticmethod
    async def _complete(operation: asyncio.Task[_T]) -> _T:
        """Client cancellation cannot interrupt durable-write/loop-state finalization."""
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            await asyncio.shield(operation)
            raise

    async def submit_async(self, module_id: str, name: str, config: dict[str, Any], *, asset_id: str | None = None,
                           idempotency_key: str | None = None) -> dict[str, Any]:
        operation = asyncio.create_task(self._submit_async(module_id, name, config, asset_id=asset_id,
                                                          idempotency_key=idempotency_key, request_scope="create"))
        return await self._complete(operation)

    async def _submit_async(self, module_id: str, name: str, config: dict[str, Any], *, asset_id: str | None,
                            idempotency_key: str | None, request_scope: str) -> dict[str, Any]:
        async with self._submission_lock:
            display_name, normalized, fingerprint, replay = await asyncio.to_thread(
                self._prepare, module_id, name, config, asset_id, idempotency_key, request_scope)
            if replay is not None:
                return replay
            self._check_capacity()
            self._reserved += 1
            try:
                job, created = await asyncio.to_thread(
                    self._persist, module_id, display_name, normalized, asset_id, idempotency_key, fingerprint)
                if created:
                    self.queue.put_nowait(job["id"])
                return job
            finally:
                self._reserved -= 1

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._cancel_state(job_id)
        if job_id in self.active:
            self.active[job_id].cancel()
        return job

    def _cancel_state(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get(job_id)
        if job["status"] == "cancelled":
            return job
        if job["status"] in TERMINAL:
            raise WorkbenchError("JOB_TERMINAL", "该任务已经结束")
        changed = self.repository.transition(job_id, {"queued", "running"}, "cancelled", "任务已取消")
        if not changed:
            current = self.repository.get(job_id)
            if current["status"] == "cancelled":
                return current
            raise WorkbenchError("JOB_TERMINAL", "该任务已经结束，未被取消")
        return self.repository.get(job_id)

    async def cancel_async(self, job_id: str) -> dict[str, Any]:
        async def cancel() -> dict[str, Any]:
            async with self._submission_lock:
                job = await asyncio.to_thread(self._cancel_state, job_id)
                if job_id in self.active:
                    self.active[job_id].cancel()
                return job
        return await self._complete(asyncio.create_task(cancel()))

    def retry(self, job_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        old = self._retry_input(job_id)
        return self._submit(old["module"], old["name"], old["config"], asset_id=old.get("asset_id"),
                            idempotency_key=idempotency_key, request_scope="retry:" + job_id)

    def _retry_input(self, job_id: str) -> dict[str, Any]:
        old = self.repository.get(job_id)
        if old["status"] not in TERMINAL:
            raise WorkbenchError("JOB_ACTIVE", "运行中的任务不能重试")
        return old

    async def retry_async(self, job_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        async def retry() -> dict[str, Any]:
            old = await asyncio.to_thread(self._retry_input, job_id)
            return await self._submit_async(old["module"], old["name"], old["config"], asset_id=old.get("asset_id"),
                                            idempotency_key=idempotency_key, request_scope="retry:" + job_id)
        return await self._complete(asyncio.create_task(retry()))

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                task = asyncio.create_task(self._execute(job_id))
                self.active[job_id] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if self.stopping:
                        return
                finally:
                    self.active.pop(job_id, None)
            finally:
                self.queue.task_done()

    async def _execute(self, job_id: str) -> None:
        loop = asyncio.get_running_loop()
        progress_tail: asyncio.Task[None] | None = None
        progress_closed = False

        def schedule_progress(percent: int, message: str) -> None:
            nonlocal progress_tail
            if progress_closed:
                return
            previous = progress_tail

            async def write() -> None:
                if previous is not None:
                    await previous
                await asyncio.to_thread(self.repository.progress, job_id, percent, message)

            # All chain state and Task operations belong to this event loop.
            # RunContext.progress may be called from a module's worker thread.
            progress_tail = asyncio.create_task(write())

        def progress(percent: int, message: str) -> None:
            loop.call_soon_threadsafe(schedule_progress, percent, message)

        async def drain_progress(*, suppress_errors: bool = False) -> None:
            nonlocal progress_closed
            # Process already-posted thread-safe progress callbacks before closing
            # the chain. Later callbacks are ignored; terminal DB guards also stop
            # any pending write from overriding cancelled/completed jobs.
            await asyncio.sleep(0)
            progress_closed = True
            if progress_tail is not None:
                try:
                    await asyncio.shield(progress_tail)
                except Exception:
                    if not suppress_errors:
                        raise
                    logger.exception("Progress persistence failed for job %s", job_id)

        async def transition(expected: set[str], status: str, message: str, **kwargs: Any) -> bool:
            operation = asyncio.create_task(asyncio.to_thread(
                self.repository.transition, job_id, expected, status, message, **kwargs))
            return await self._complete(operation)

        try:
            if not await transition({"queued"}, "running", "开始分析"):
                return
            job = await asyncio.to_thread(self.repository.get, job_id)
            module = self.registry.get(job["module"])
            workspace = self.data_dir / "jobs" / job_id
            workspace.mkdir(parents=True, exist_ok=True)
            context = RunContext(job_id, workspace, self.data_dir / "uploads", progress)
            result = await module.run(job["config"], context)
            await drain_progress()
            await transition({"running"}, "completed", "分析完成", result=result.to_dict())
        except asyncio.CancelledError:
            await drain_progress(suppress_errors=True)
            if self.stopping:
                await transition({"running"}, "failed", "服务关闭，任务已中断",
                                 error={"code": "INTERRUPTED", "message": "服务关闭，可重新执行"})
            else:
                await transition({"running"}, "cancelled", "任务已取消")
            raise
        except WorkbenchError as exc:
            await drain_progress(suppress_errors=True)
            await transition({"running"}, "failed", exc.message, error={"code": exc.code, "message": exc.message})
        except Exception:
            logger.exception("Unexpected module error for job %s", job_id)
            await drain_progress(suppress_errors=True)
            await transition({"running"}, "failed", "模块内部错误，请查看服务日志",
                             error={"code": "MODULE_ERROR", "message": "模块执行失败，未生成完整结果"})
