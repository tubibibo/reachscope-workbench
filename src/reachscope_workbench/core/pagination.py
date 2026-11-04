"""Bound persistence pagination before values reach SQLite parameter binding."""

from __future__ import annotations

from .models import WorkbenchError

MAX_SQLITE_INTEGER = 2**63 - 1


def validate_page(limit: int, offset: int, *, maximum: int = 100) -> None:
    """The offset may also represent an append-only event cursor."""
    if (type(limit) is not int or type(offset) is not int
            or not 1 <= limit <= maximum or not 0 <= offset <= MAX_SQLITE_INTEGER):
        raise WorkbenchError("INVALID_PAGE", f"分页 limit 须在 1–{maximum} 之间，offset 或游标须为有效的非负 64 位整数")
