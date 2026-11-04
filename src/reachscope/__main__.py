"""`python -m reachscope` 入口（与 console script 等价）。"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
