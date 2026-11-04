"""进程退出码（PLAN §7）。

单独成模块：`cli` 与 `ingest` 都要用它，放在 `cli.py` 里会造成
`cli → ingest → cli` 的循环导入（见 DECISIONS.md D-018）。
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """进程退出码。"""

    OK = 0
    INPUT_ERROR = 2
    UNANALYZABLE = 3
    INTERNAL_ERROR = 4


__all__ = ["ExitCode"]
