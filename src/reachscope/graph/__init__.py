"""图分析基础设施（PLAN §6.1 / §6.2）。

`graph` 只提供**寄存器级与调用图级**的原语，不做判定（判定在 `analyze/`）。
它被 `extract/`（单步回溯）与 `analyze/`（链构造）共同使用，因此是 `extract` 的
**下层**：分层依赖 `graph → ir, ingest`，`extract → ir, ingest, graph`。
"""

from __future__ import annotations

__all__: list[str] = []
