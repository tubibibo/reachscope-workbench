"""Bounded diagnostics and owned subprocess trees for trusted local decoders."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Any, BinaryIO

from .windows_job import WindowsJob

OUTPUT_LIMIT = 64 * 1024


class CommandLimitError(RuntimeError):
    """Fixed reason codes; raw decoder output is never attached to failures."""


def run_bounded(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Drain both raw pipes, fail on overflow and reclaim only our process tree."""
    options: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False, bufsize=0, **options)
    job: WindowsJob | None = None
    threads: list[threading.Thread] = []
    overflow, read_failed = threading.Event(), threading.Event()
    captured = [bytearray(), bytearray()]

    def stop() -> None:
        nonlocal job
        if job is not None:
            job.close()
            job = None
        try:
            if os.name == "nt":
                if process.poll() is None:
                    process.kill()
            else:
                kill_group = getattr(os, "killpg", None)
                if kill_group is not None:
                    kill_group(process.pid, getattr(signal, "SIGKILL", 9))
                else:
                    process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def drain(stream: BinaryIO, target: bytearray) -> None:
        count = 0
        try:
            while block := stream.read(8192):
                count += len(block)
                if count > OUTPUT_LIMIT:
                    overflow.set()
                if len(target) < OUTPUT_LIMIT:
                    target.extend(block[:OUTPUT_LIMIT - len(target)])
        except (OSError, ValueError):
            read_failed.set()

    assert process.stdout is not None and process.stderr is not None
    try:
        if os.name == "nt":
            job = WindowsJob(process.pid)
        for stream, target in zip((process.stdout, process.stderr), captured, strict=True):
            thread = threading.Thread(target=drain, args=(stream, target), daemon=True)
            thread.start()
            threads.append(thread)
        deadline = time.monotonic() + timeout
        while process.poll() is None or any(thread.is_alive() for thread in threads):
            if overflow.is_set():
                raise CommandLimitError("output_limit")
            if read_failed.is_set():
                raise CommandLimitError("read_failed")
            if time.monotonic() >= deadline:
                raise CommandLimitError("timeout")
            time.sleep(.005)
        if overflow.is_set():
            raise CommandLimitError("output_limit")
        if read_failed.is_set():
            raise CommandLimitError("read_failed")
    except BaseException:
        stop()
        raise
    finally:
        if job is not None:
            job.close()
        for thread in threads:
            thread.join(timeout=1)
        # Popen bufsize=0 gives FileIO, so close cannot wait on a buffered
        # reader lock after a timeout or an interrupted owned process tree.
        process.stdout.close()
        process.stderr.close()
    return subprocess.CompletedProcess(command, process.returncode if process.returncode is not None else -1,
                                       captured[0].decode("utf-8", errors="replace"),
                                       captured[1].decode("utf-8", errors="replace"))
