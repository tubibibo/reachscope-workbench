"""Bounded fixed-command execution, with owned-process cleanup and safe states."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO, cast

TIMEOUT_SECONDS = 10
STDOUT_LIMIT = 256 * 1024
STDERR_LIMIT = 64 * 1024
COMMANDS = {"ssh": ("/usr/sbin/sshd", "-T"), "nginx": ("/usr/sbin/nginx", "-T")}
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class CommandResult:
    state: str
    reason_code: str
    exit_code: int | None = None
    stdout: bytes | None = None


def _stop(process: subprocess.Popen[bytes]) -> None:
    # The leader may have exited while a descendant still owns a pipe. Always
    # stop the entire session we created, including after wait() succeeds.
    try:
        if os.name == "posix":
            cast(Callable[[int, int], None], getattr(os, "killpg", None))(process.pid, signal.SIGTERM)
        else:
            result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=_CREATE_NO_WINDOW, timeout=2)
            if result.returncode == 0:
                process.wait(timeout=1)
                return
            if process.poll() is None:
                process.terminate()
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.wait(timeout=.3)
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            cast(Callable[[int, int], None], getattr(os, "killpg", None))(process.pid, getattr(signal, "SIGKILL", 9))
        except OSError:
            pass
    elif process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def run_component(component: str) -> CommandResult:
    """Execute only a server-owned fixed argv; target stderr is never returned."""
    command = COMMANDS[component]
    # No PATH lookup, shell, user command, cwd config or inherited secrets.
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, env=environment,
                                   cwd="/", start_new_session=os.name == "posix", bufsize=0)
    except FileNotFoundError:
        return CommandResult("unavailable", "missing_executable")
    except OSError:
        return CommandResult("unavailable", "execution_unavailable")
    overflow = threading.Event()
    failed = threading.Event()
    output = bytearray()

    def drain(stream: BinaryIO, limit: int, keep: bool) -> None:
        count = 0
        try:
            while chunk := stream.read(8192):
                count += len(chunk)
                if count > limit:
                    overflow.set()
                if keep and len(output) < limit:
                    output.extend(chunk[:limit - len(output)])
        except (OSError, ValueError):
            failed.set()

    assert process.stdout is not None and process.stderr is not None
    threads = [threading.Thread(target=drain, args=(process.stdout, STDOUT_LIMIT, True), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, STDERR_LIMIT, False), daemon=True)]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    reason = "ok"
    started: list[threading.Thread] = []
    try:
        for thread in threads:
            thread.start()
            started.append(thread)
        while process.poll() is None or any(thread.is_alive() for thread in threads):
            if overflow.is_set():
                reason = "output_budget"
                break
            if time.monotonic() >= deadline:
                reason = "command_timeout"
                break
            time.sleep(.01)
    except BaseException:
        _stop(process)
        raise
    finally:
        if reason != "ok":
            _stop(process)
        for thread in started:
            thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()
    if reason == "output_budget" or overflow.is_set():
        return CommandResult("budget_exceeded", "output_budget", process.returncode)
    if reason == "command_timeout":
        return CommandResult("timeout", "command_timeout", process.returncode)
    if failed.is_set():
        return CommandResult("failed", "output_read_failed", process.returncode)
    if process.returncode:
        return CommandResult("failed", "nonzero_exit", process.returncode)
    return CommandResult("collected", "ok", 0, bytes(output))
