"""从报告 IR 派生开放问题（协议 v0.1）。

**只允许四类来源**（DECISIONS D-074）：

1. `Chain.evidence_complete == false`；
2. `Judgment.result` 或 `confidence` 为 `UNKNOWN`；
3. `Component.impl_present == false`；
4. `Meta.warnings` 非空 / 加固导致分析不可用。

不臆造问题：每条问题都带 `why`（对应 IR 字段）与可用的 `file:line`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from ..ir.model import Chain, JudgmentResult, Level, Report, SourceLoc
from ..ir.serialize import IRSerializable
from .claims import PROTOCOL_SCHEMA_VERSION
from .question import AnswerType, Question, make_question, question_sort_key


class QuestionCode(StrEnum):
    """问题类别；同时用作 verdict `missing_facts[].code`。"""

    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    JUDGMENT_UNKNOWN = "JUDGMENT_UNKNOWN"
    IMPL_MISSING = "IMPL_MISSING"
    NEGATIVE_NOT_DEFINITIVE = "NEGATIVE_NOT_DEFINITIVE"
    INDEX_WARNING = "INDEX_WARNING"
    PROTECTION_UNANALYZABLE = "PROTECTION_UNANALYZABLE"


#: 反例里**不能**当作闭世界否定的判据（J1/J2 的否定是定义性的）。
NON_DEFINITIVE_JUDGMENTS = frozenset({"J4", "J5", "J6"})


@dataclass(frozen=True)
class QuestionsDoc(IRSerializable):
    """`reachscope questions` 的输出。"""

    schema_version: str = PROTOCOL_SCHEMA_VERSION
    questions: list[Question] = field(default_factory=list)


def collect_questions(report: Report) -> list[Question]:
    """按固定顺序生成问题（排序键见 `question_sort_key`）。"""
    questions: list[Question] = []

    for chain in report.chains:
        questions.extend(_chain_questions(chain))

    for component in report.components:
        if component.impl_present:
            continue
        questions.append(
            make_question(
                code=QuestionCode.IMPL_MISSING.value,
                subject_kind="component",
                subject_id=component.name,
                question=(
                    f"manifest 声明了组件 {component.name}，但 APK 内找不到实现类；"
                    "是否由动态加载或混淆提供？"
                ),
                why=(
                    "Component.impl_present=false"
                    f"（{component.impl_reason or 'implementation class not found in APK'}）"
                ),
                evidence=component.source,
                answer_type=AnswerType.BOOLEAN,
            )
        )

    for counter_example in report.counter_examples:
        if counter_example.failed_judgment not in NON_DEFINITIVE_JUDGMENTS:
            continue
        questions.append(
            make_question(
                code=QuestionCode.NEGATIVE_NOT_DEFINITIVE.value,
                subject_kind="entry",
                subject_id=counter_example.entry_id,
                key_suffix=counter_example.failed_judgment,
                question=(
                    f"入口 {counter_example.entry_id} 被记为 {counter_example.failed_judgment} "
                    f"反例（{counter_example.reason}）；该否定是否确实成立？"
                ),
                why=(
                    f"CounterExample.failed_judgment={counter_example.failed_judgment}："
                    "该判据的否定分支可能来自 UNKNOWN，不能单独作为闭世界否定"
                ),
                evidence=counter_example.source,
                answer_type=AnswerType.BOOLEAN,
            )
        )

    warnings = sorted(report.meta.warnings)
    if warnings:
        sample = "；".join(warnings[:3])
        questions.append(
            make_question(
                code=QuestionCode.INDEX_WARNING.value,
                subject_kind="global",
                subject_id="meta.warnings",
                question=(
                    f"报告包含 {len(warnings)} 条分析警告（例如：{sample}）；"
                    "是否可能有类/方法未被解析？"
                ),
                why="Meta.warnings 非空：分析未在完全闭合的世界里完成",
                answer_type=AnswerType.FREE_TEXT,
            )
        )

    if report.protection.analyzable is False:
        labels = ", ".join(report.protection.labels) or "unknown"
        questions.append(
            make_question(
                code=QuestionCode.PROTECTION_UNANALYZABLE.value,
                subject_kind="global",
                subject_id="protection",
                question=(
                    f"检测到强加固（labels={labels}），分析被跳过；"
                    "是否能提供脱壳/去混淆后的 APK？"
                ),
                why="Protection.analyzable=false",
                answer_type=AnswerType.FREE_TEXT,
            )
        )

    deduped: dict[str, Question] = {}
    for question in sorted(questions, key=question_sort_key):
        deduped.setdefault(question.question_id, question)
    return list(deduped.values())


def questions_document(report: Report) -> QuestionsDoc:
    """生成 `QuestionsDoc`。"""
    return QuestionsDoc(questions=collect_questions(report))


def render_questions(document: QuestionsDoc) -> str:
    """确定性 JSON 文本（UTF-8、2 空格缩进、键排序、末尾换行）。"""
    return (
        json.dumps(document.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    )


def _chain_questions(chain: Chain) -> list[Question]:
    """链级问题：证据不完整 + 每条 UNKNOWN 判据。"""
    questions: list[Question] = []
    if not chain.evidence_complete:
        questions.append(
            make_question(
                code=QuestionCode.EVIDENCE_INCOMPLETE.value,
                subject_kind="chain",
                subject_id=chain.id,
                question=(
                    f"链 {chain.id} 的 J6 证据不完整；缺失的步骤是否确实可被攻击者走到？"
                ),
                why="Chain.evidence_complete=false（J6 未覆盖全部步骤）",
                evidence=_first_step_without_source(chain),
                answer_type=AnswerType.BOOLEAN,
            )
        )
    for index, judgment in enumerate(chain.judgments):
        if (
            judgment.result is not JudgmentResult.UNKNOWN
            and judgment.confidence is not Level.UNKNOWN
        ):
            continue
        questions.append(
            make_question(
                code=QuestionCode.JUDGMENT_UNKNOWN.value,
                subject_kind="chain",
                subject_id=chain.id,
                key_suffix=f"{judgment.name}:{index}",
                question=(
                    f"判据 {judgment.name} 在链 {chain.id} 上结果为 UNKNOWN"
                    f"（{judgment.reason or '无说明'}）；请确认该判据涉及的事实。"
                ),
                why=f"Judgment({judgment.name}).result/confidence = UNKNOWN",
                evidence=judgment.source,
                answer_type=AnswerType.FREE_TEXT,
            )
        )
    return questions


def _first_step_without_source(chain: Chain) -> SourceLoc | None:
    """证据缺口最直观的位置：第一条无 source 步骤之前最近的一处证据。"""
    last_source: SourceLoc | None = None
    for step in chain.steps:
        if step.source is None:
            return last_source
        last_source = step.source
    return last_source


__all__ = [
    "NON_DEFINITIVE_JUDGMENTS",
    "QuestionCode",
    "QuestionsDoc",
    "collect_questions",
    "questions_document",
    "render_questions",
]
