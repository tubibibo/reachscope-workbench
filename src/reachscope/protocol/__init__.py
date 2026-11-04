"""Claim–Verdict 协议：模型举证、工具判决（v0.2）。

协议层只依赖 `ir/`：

- :mod:`reachscope.protocol.claims` —— 模型提交的 claim
- :mod:`reachscope.protocol.question` —— 工具向模型提问的数据模型
- :mod:`reachscope.protocol.answer` —— 模型回答
- :mod:`reachscope.protocol.questions` —— 从报告 IR 派生开放问题
- :mod:`reachscope.protocol.coverage` —— 闭世界判定
- :mod:`reachscope.protocol.verdict` —— 裁决引擎

设计口径见 `docs/reference/evidence-protocol.md` 与 DECISIONS.md 的 D-070 起。
"""

from __future__ import annotations

from .claims import (
    Assumption,
    Claim,
    ClaimError,
    ClaimKind,
    EntryRef,
    SinkRef,
    StepRef,
    load_claim,
)
from .coverage import CoverageView
from .question import AnswerType, Question
from .verdict import ReasonCode, Verdict, VerdictStatus, render_verdict, verify_claim

__all__ = [
    "AnswerType",
    "Assumption",
    "Claim",
    "ClaimError",
    "ClaimKind",
    "CoverageView",
    "EntryRef",
    "Question",
    "ReasonCode",
    "SinkRef",
    "StepRef",
    "Verdict",
    "VerdictStatus",
    "load_claim",
    "render_verdict",
    "verify_claim",
]
