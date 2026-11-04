"""工具向模型提出的开放问题（协议 v0.1）。

问题只能由报告 IR 里**明确标为未知**的事实派生（见 `questions.py`），
不允许工具凭自由文本推断。`question_id` 由 `(code, subject, 判别键)` 稳定生成，
同一份报告重复生成逐字节一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..ir.model import SourceLoc
from ..ir.serialize import IRSerializable, stable_id


class AnswerType(StrEnum):
    """回答的取值类型；`verify` 会按它校验回答。"""

    FREE_TEXT = "free_text"
    BOOLEAN = "boolean"
    ENUM = "enum"


@dataclass(frozen=True)
class Question(IRSerializable):
    """一条开放问题。"""

    question_id: str = ""
    code: str = ""
    subject_kind: str = ""
    subject_id: str = ""
    question: str = ""
    why: str = ""
    evidence: SourceLoc | None = None
    answer_type: AnswerType = AnswerType.FREE_TEXT
    candidates: list[str] = field(default_factory=list)


def make_question(
    *,
    code: str,
    subject_kind: str,
    subject_id: str,
    question: str,
    why: str,
    evidence: SourceLoc | None = None,
    answer_type: AnswerType = AnswerType.FREE_TEXT,
    candidates: list[str] | None = None,
    key_suffix: str = "",
) -> Question:
    """构造问题并计算稳定 ID。

    `key_suffix` 只参与 ID 计算、不写入 JSON：同一 subject 下同类问题
    （如同一链上的多条 UNKNOWN 判据）靠它区分。
    """
    key = f"{code}|{subject_kind}|{subject_id}|{key_suffix}"
    return Question(
        question_id=stable_id("question", key),
        code=code,
        subject_kind=subject_kind,
        subject_id=subject_id,
        question=question,
        why=why,
        evidence=evidence,
        answer_type=answer_type,
        candidates=list(candidates or []),
    )


def question_sort_key(question: Question) -> tuple[str, str, str, str]:
    """确定性排序键：subject 类别 → subject → code → id。"""
    return (
        question.subject_kind,
        question.subject_id,
        question.code,
        question.question_id,
    )


__all__ = [
    "AnswerType",
    "Question",
    "make_question",
    "question_sort_key",
]
