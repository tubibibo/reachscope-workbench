"""Read upload bytes from a regular, non-symlink file without a check/open gap."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .models import WorkbenchError


def read_upload(
    path: Path,
    *,
    max_bytes: int,
    missing_message: str,
    limit_code: str,
    limit_message: str,
    require_nonempty: bool = False,
) -> bytes:
    """Open once, verify the opened inode, and return at most ``max_bytes``."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if os.name == "posix":
        flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise WorkbenchError("UPLOAD_NOT_FOUND", missing_message)
            if os.name == "nt":
                current = os.stat(path, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode):
                    raise WorkbenchError("UPLOAD_NOT_FOUND", missing_message)
                # Some Windows filesystems report zero inode IDs; there the
                # no-follow path check is the strongest available comparison.
                if opened.st_ino and current.st_ino and (
                    opened.st_dev != current.st_dev or opened.st_ino != current.st_ino
                ):
                    raise WorkbenchError("UPLOAD_NOT_FOUND", missing_message)
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(max_bytes + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except WorkbenchError:
        raise
    except OSError as exc:
        raise WorkbenchError("UPLOAD_NOT_FOUND", missing_message) from exc
    if len(raw) > max_bytes or (require_nonempty and not raw):
        raise WorkbenchError(limit_code, limit_message)
    return raw


__all__ = ["read_upload"]
