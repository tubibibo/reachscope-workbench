"""Bounded async subprocess execution with process-tree cancellation."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Any

from ...core.models import WorkbenchError
from .windows_job import WindowsJob

OUTPUT_LIMIT = 64 * 1024


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def _read_tail(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        return b""
    tail = b""
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return tail
        tail = (tail + chunk)[-OUTPUT_LIMIT:]


async def _terminate_tree(process: asyncio.subprocess.Process) -> None:
    """Stop the analysis worker and its decoder, not unrelated Java processes."""
    if os.name == "nt":
        if process.returncode is not None:
            return
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await asyncio.wait_for(killer.wait(), timeout=10)
        except (OSError, TimeoutError):
            # A racing worker exit is harmless; kill() still covers the direct child.
            if process.returncode is None:
                process.kill()
    else:
        try:
            kill_group = getattr(os, "killpg", None)
            if kill_group is not None:
                kill_group(process.pid, getattr(signal, "SIGKILL", 9))
            else:
                process.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.wait()


async def run_process(
    command: list[str], *, timeout: float, env: dict[str, str], cwd: str,
) -> ProcessResult:
    """Capture only bounded tails while continuously draining both pipe streams.

    A separate process group gives cancellation ownership over the decoder tree.
    No shell, terminal window, target execution or process-global environment change.
    """
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options,
        )
    except OSError as exc:
        raise WorkbenchError("WORKER_START_FAILED", f"Cannot start Android analysis: {exc}") from exc
    stdout = asyncio.create_task(_read_tail(process.stdout))
    stderr = asyncio.create_task(_read_tail(process.stderr))
    job: WindowsJob | None = None
    if os.name == "nt":
        try:
            job = WindowsJob(process.pid)
        except OSError as exc:
            await _terminate_tree(process)
            await asyncio.gather(stdout, stderr, return_exceptions=True)
            raise WorkbenchError("WORKER_START_FAILED", f"Cannot own Android process tree: {exc}") from exc
    async def collect() -> list[bytes]:
        await process.wait()
        return list(await asyncio.gather(stdout, stderr))

    completed = asyncio.create_task(collect())
    try:
        captured = await asyncio.wait_for(asyncio.shield(completed), timeout=timeout)
    except (asyncio.CancelledError, TimeoutError) as exc:
        # Shield cleanup from the caller's cancellation so no decoder is orphaned.
        if job is not None:
            job.close()
        await asyncio.shield(_terminate_tree(process))
        await asyncio.gather(completed, return_exceptions=True)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise WorkbenchError("ANALYSIS_TIMEOUT", f"Android analysis exceeded {timeout:g} seconds") from None
    finally:
        if job is not None:
            job.close()
    return ProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=captured[0].decode("utf-8", errors="replace"),
        stderr=captured[1].decode("utf-8", errors="replace"),
    )
