"""分析层（PLAN §6）。

本层只做**判定与链构造**，所有事实输入（组件 / 桥 / 来源校验 / 汇点）由 `extract/`
提供。判定必须可被独立单测，不依赖 `cli`。
"""

from __future__ import annotations

__all__: list[str] = []
