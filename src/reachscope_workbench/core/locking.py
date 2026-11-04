"""One server process owns a workspace; database writes remain transactional."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO

from .models import WorkbenchError


class WorkspaceLock:
    def __init__(self, directory: Path) -> None:
        self.path = directory / "server.lock"
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self.handle is not None:
            raise WorkbenchError("WORKSPACE_BUSY", "这个服务已经持有工作目录锁")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise WorkbenchError("WORKSPACE_BUSY", "另一个服务已经打开这个工作目录") from exc
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
