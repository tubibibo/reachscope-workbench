"""Check a reachability claim against evidence in one static-analysis report.

SUPPORTED means that a matching candidate path has complete report evidence. It
does not independently prove runtime feasibility or a vulnerability. REFUTED is
reserved for a direct manifest access condition; missing/mismatched report paths
are UNDECIDABLE. Model answers remain assumptions, never new code facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ..ir.model import (
    Chain,
    Component,
    CounterExample,
    Deeplink,
    JudgmentResult,
    Level,
    Report,
)
from ..ir.serialize import IRSerializable
from .answer import Answer, AnswersDoc
from .claims import (
    PROTOCOL_SCHEMA_VERSION,
    Claim,
    ClaimError,
    EntryRefKind,
    StepRef,
)
from .coverage import CoverageView
from .question import AnswerType, Question
from .questions import collect_questions


class VerdictStatus(StrEnum):
    """Report-scoped evidence statuses, not whole-program security judgments."""

    REFUTED = "REFUTED"
    UNDECIDABLE = "UNDECIDABLE"
    SUPPORTED_WITH_ASSUMPTIONS = "SUPPORTED_WITH_ASSUMPTIONS"
    SUPPORTED = "SUPPORTED"


class ReasonCode(StrEnum):
    """裁决原因码（稳定字符串，Agent 可直接分支）。"""

    CHAIN_FOUND = "CHAIN_FOUND"
    NO_CHAIN_J5 = "NO_CHAIN_J5"
    NEGATIVE_NOT_DEFINITIVE = "NEGATIVE_NOT_DEFINITIVE"
    STEP_MISMATCH = "STEP_MISMATCH"
    SINK_MISMATCH = "SINK_MISMATCH"
    ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"
    NOT_ZERO_PERMISSION = "NOT_ZERO_PERMISSION"
    IMPL_MISSING = "IMPL_MISSING"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    UNKNOWN_FACTS = "UNKNOWN_FACTS"
    NO_ANALYSIS_RESULT = "NO_ANALYSIS_RESULT"


@dataclass(frozen=True)
class VerdictEvidence(IRSerializable):
    """一条链步骤证据。"""

    step: int = 0
    sink: str = ""
    description: str = ""
    file: str = ""
    line: int = 0
    snippet: str = ""


@dataclass(frozen=True)
class VerdictCounterexample(IRSerializable):
    """被引用的反例。"""

    entry_id: str = ""
    entry_kind: str = ""
    failed_judgment: str = ""
    reason: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class MissingFact(IRSerializable):
    """缺口：对应 `reachscope questions` 里的一条问题。"""

    question_id: str = ""
    code: str = ""
    question: str = ""
    why: str = ""


@dataclass(frozen=True)
class Verdict(IRSerializable):
    """Evidence consistency of a claim within the supplied analysis report."""

    schema_version: str = PROTOCOL_SCHEMA_VERSION
    claim_id: str = ""
    status: VerdictStatus = VerdictStatus.UNDECIDABLE
    reason_code: ReasonCode = ReasonCode.UNKNOWN_FACTS
    failed_judgment: str | None = None
    evidence: list[VerdictEvidence] = field(default_factory=list)
    counterexample: VerdictCounterexample | None = None
    missing_facts: list[MissingFact] = field(default_factory=list)
    coverage: CoverageView = field(default_factory=CoverageView)
    assumptions_used: list[str] = field(default_factory=list)
    scope: str = "static_analysis_report"
    statement: str = ""


def render_verdict(verdict: Verdict) -> str:
    """确定性 JSON 文本（UTF-8、2 空格缩进、键排序、末尾换行）。"""
    return (
        json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    )


def verify_claim(
    report: Report,
    claim: Claim,
    answers: AnswersDoc | None = None,
) -> Verdict:
    """裁决一条 claim。输入非法（未知问题 / 回答取值）抛 :class:`ClaimError`。"""
    coverage = CoverageView.from_report(report)
    questions = collect_questions(report)
    assumptions_used = _merge_answers(claim, answers, questions)

    target, not_found = _resolve_entry(report, claim)
    subjects: set[str] = set()
    if target is not None:
        subjects.add(target.name)

    if not_found or target is None:
        return _finalize(
            _undecidable(
                claim,
                reason_code=ReasonCode.ENTRY_NOT_FOUND,
                failed_judgment=None,
                assumptions_used=assumptions_used,
                subjects=subjects,
                questions=questions,
                counterexample=None,
                evidence=[],
            ),
            coverage,
            questions,
            subjects,
            assumptions_used,
        )

    component = target.component
    counterexample = _find_counterexample(report, target.name)

    # J1：manifest 层面就能确定的否定（未导出 / 签名级权限）。
    if component is not None:
        j1_reason = _j1_block_reason(component)
        if j1_reason is not None:
            return _finalize(
                _negative(
                    claim,
                    coverage,
                    reason_code=ReasonCode.NOT_ZERO_PERMISSION,
                    failed_judgment="J1",
                    assumptions_used=assumptions_used,
                    subjects=subjects,
                    questions=questions,
                    counterexample=counterexample,
                    # 反例详情比重新拼一条更完整
                    reason_override=(
                        counterexample.reason
                        if counterexample is not None
                        and counterexample.failed_judgment == "J1"
                        else j1_reason
                    ),
                ),
                coverage,
                questions,
                subjects,
                assumptions_used,
            )

    # J2：实现缺失 → 可能是动态加载/混淆，绝不当作闭世界否定。
    if component is not None and not component.impl_present:
        return _finalize(
            _undecidable(
                claim,
                reason_code=ReasonCode.IMPL_MISSING,
                failed_judgment="J2",
                assumptions_used=assumptions_used,
                subjects=subjects,
                questions=questions,
                counterexample=counterexample,
                evidence=[],
            ),
            coverage,
            questions,
            subjects,
            assumptions_used,
        )

    # A risk counterexample (for example missing JS bridge) cannot hide an
    # existing data path. Counterexamples describe the no-path case only.
    entry_chains = _chains_for(report, target.name)
    if not entry_chains:
        return _finalize(
            _undecidable(
                claim,
                reason_code=(
                    ReasonCode.NEGATIVE_NOT_DEFINITIVE
                    if counterexample is not None
                    else ReasonCode.NO_ANALYSIS_RESULT
                ),
                failed_judgment=(
                    counterexample.failed_judgment if counterexample is not None else None
                ),
                assumptions_used=assumptions_used,
                subjects=subjects,
                questions=questions,
                counterexample=counterexample,
                evidence=[],
            ),
            coverage,
            questions,
            subjects,
            assumptions_used,
        )

    sink_kind = claim.sink.kind if claim.sink is not None else "any"
    sink_chains = [chain for chain in entry_chains if _chain_has_sink(chain, sink_kind)]
    if not sink_chains:
        best = _best_chain(entry_chains)
        negative = _undecidable(
            claim,
            reason_code=ReasonCode.SINK_MISMATCH,
            failed_judgment=None,
            assumptions_used=assumptions_used,
            subjects=subjects,
            questions=questions,
            counterexample=None,
            evidence=_chain_evidence(best),
        )
        return _finalize(
            negative, coverage, questions, subjects, assumptions_used
        )

    matching = [
        chain
        for chain in sink_chains
        if _steps_match(chain, claim.asserted_steps)
    ]
    if claim.asserted_steps and not matching:
        best = _best_chain(sink_chains)
        negative = _undecidable(
            claim,
            reason_code=ReasonCode.STEP_MISMATCH,
            failed_judgment=None,
            assumptions_used=assumptions_used,
            subjects=subjects,
            questions=questions,
            counterexample=None,
            evidence=_chain_evidence(best),
        )
        return _finalize(
            negative, coverage, questions, subjects, assumptions_used
        )

    chosen = _best_chain(matching or sink_chains)
    if not _chain_definitive(chosen):
        return _finalize(
            _undecidable(
                claim,
                reason_code=ReasonCode.EVIDENCE_INCOMPLETE,
                failed_judgment=None,
                assumptions_used=assumptions_used,
                subjects=subjects | {chosen.id},
                questions=questions,
                counterexample=None,
                evidence=_chain_evidence(chosen),
            ),
            coverage,
            questions,
            subjects,
            assumptions_used,
        )

    status = (
        VerdictStatus.SUPPORTED_WITH_ASSUMPTIONS
        if assumptions_used
        else VerdictStatus.SUPPORTED
    )
    verdict = Verdict(
        claim_id=claim.claim_id,
        status=status,
        reason_code=ReasonCode.CHAIN_FOUND,
        failed_judgment=None,
        evidence=_chain_evidence(chosen),
        counterexample=None,
        missing_facts=[],
        coverage=coverage,
        assumptions_used=assumptions_used,
    )
    return _finalize(
        verdict, coverage, questions, subjects | {chosen.id}, assumptions_used
    )


# --- 入口解析 ---------------------------------------------------------------


@dataclass(frozen=True)
class _EntryTarget:
    """解析后的入口：组件名统一成全名，深链记录可选。"""

    name: str
    component: Component | None
    deeplink: Deeplink | None


def _resolve_entry(
    report: Report, claim: Claim
) -> tuple[_EntryTarget | None, bool]:
    """返回 `(target, not_found)`；多义直接抛 :class:`ClaimError`。"""
    entry = claim.entry
    package = report.meta.package
    if entry.kind is EntryRefKind.COMPONENT:
        candidates = _match_components(report, entry.id, entry.name, package)
        if not candidates:
            return None, True
        if len(candidates) > 1:
            names = ", ".join(sorted(item.name for item in candidates))
            raise ClaimError(f"claim.entry 指向多个组件（{names}），请改用 id")
        component = candidates[0]
        return _EntryTarget(component.name, component, None), False

    deeplinks = _match_deeplinks(report, entry.id, entry.name)
    if not deeplinks:
        return None, True
    if len(deeplinks) > 1:
        ids = ", ".join(sorted(item.id for item in deeplinks))
        raise ClaimError(f"claim.entry 指向多个深链（{ids}），请改用 id")
    deeplink = deeplinks[0]
    name = _canonical_component(package, deeplink.component)
    target_component = next(
        (
            item
            for item in report.components
            if _canonical_component(package, item.name) == name
        ),
        None,
    )
    return _EntryTarget(name, target_component, deeplink), False


def _match_components(
    report: Report, wanted_id: str, wanted_name: str, package: str
) -> list[Component]:
    """先按 id、再按 name；两者同时给出时必须指向同一记录。"""
    by_id = [
        component
        for component in report.components
        if wanted_id.strip() and component.id == wanted_id.strip()
    ]
    by_name = [
        component
        for component in report.components
        if wanted_name.strip()
        and _canonical_component(package, component.name)
        == _canonical_component(package, wanted_name)
    ]
    if wanted_id.strip() and wanted_name.strip():
        common = [
            component for component in by_id if component in by_name
        ]
        if not common:
            raise ClaimError("claim.entry.id 与 name 指向不同组件")
        return common
    return by_id or by_name


def _match_deeplinks(report: Report, wanted_id: str, wanted_name: str) -> list[Deeplink]:
    """深链按 id / 规范化 URI 匹配；`name` 也可以直接写 id。"""
    wanted = wanted_name.strip()
    by_id = [item for item in report.deeplinks if wanted_id.strip() and item.id == wanted_id.strip()]
    by_name = [
        item for item in report.deeplinks
        if wanted and (item.id == wanted or _deeplink_uri(item) == wanted)
    ]
    if wanted_id.strip() and wanted:
        common = [item for item in by_id if item in by_name]
        if not common:
            raise ClaimError("claim.entry.id 与 name 指向不同深链")
        return common
    return by_id or by_name


def _deeplink_uri(deeplink: Deeplink) -> str:
    """`scheme://host/path` 的规范化形式。"""
    return f"{deeplink.scheme}://{deeplink.host}{deeplink.path}"


def _canonical_component(package: str, name: str) -> str:
    """把 `.MainActivity` / `MainActivity` 补成 `package.MainActivity`。"""
    value = name.strip()
    if not value:
        return ""
    if value.startswith("."):
        return f"{package}{value}" if package else value
    if "." not in value and package:
        return f"{package}.{value}"
    return value


def _j1_block_reason(component: Component) -> str | None:
    """J1 的两种定义性否定：未导出、签名级权限。"""
    if not component.exported:
        if component.exported_inferred:
            return None
        return "not exported"
    protection = component.permission_protection or ""
    if component.permission and "signature" in protection:
        return "signature-level permission"
    return None


def _find_counterexample(report: Report, name: str) -> CounterExample | None:
    """按组件全名匹配反例；同一入口最多一条（`build_evidence` 的契约）。"""
    package = report.meta.package
    matches = [
        counter_example
        for counter_example in report.counter_examples
        if _canonical_component(package, counter_example.entry_id)
        == _canonical_component(package, name)
    ]
    if not matches:
        return None
    return min(matches, key=lambda item: (item.failed_judgment, item.reason))


# --- 链匹配 ----------------------------------------------------------------


def _chains_for(report: Report, name: str) -> list[Chain]:
    """`Chain.entries` 存的是组件 name（见 `analyze/chains.py`）。"""
    package = report.meta.package
    canonical = _canonical_component(package, name)
    return [
        chain
        for chain in report.chains
        if chain.entries
        and _canonical_component(package, chain.entries[0]) == canonical
    ]


def _chain_has_sink(chain: Chain, kind: str) -> bool:
    """claim 的 sink 聚合别名 → `Step.sink` 词表。"""
    if kind == "any":
        return True
    if kind == "bridge":
        accepted = {"bridge", "bridge_method"}
    else:
        accepted = {kind}
    return any(step.sink in accepted for step in chain.steps)


def _steps_match(chain: Chain, asserted: list[StepRef]) -> bool:
    """`asserted_steps` 是否为链上 sink 序列的子序列。"""
    if not asserted:
        return True
    wanted = [step.sink for step in asserted]
    index = 0
    for step in chain.steps:
        if not step.sink:
            continue
        if index < len(wanted) and step.sink == wanted[index]:
            index += 1
    return index == len(wanted)


def _chain_definitive(chain: Chain) -> bool:
    """Complete candidate-path evidence, independent of impact/bridge findings.

    J3 (impact) and J4 (bridge risk) are intentionally irrelevant to a path
    query. This is still only the analyzer's candidate path, not proof that its
    branch conditions are simultaneously feasible at runtime.
    """
    if not chain.evidence_complete or not chain.steps:
        return False
    if any(
        step.source is None or not step.source.file or step.source.line <= 0
        for step in chain.steps
    ):
        return False
    path_judgments = [
        judgment for judgment in chain.judgments if judgment.name in {"J1", "J2", "J5", "J6"}
    ]
    if not any(judgment.name == "J6" for judgment in path_judgments):
        return False
    return all(
        judgment.result in {JudgmentResult.PASS, JudgmentResult.PASS_WITH_NOTE}
        and judgment.confidence is not Level.UNKNOWN
        for judgment in path_judgments
    )


def _best_chain(chains: list[Chain]) -> Chain:
    """确定性选择：证据完整优先，再按 id 升序。"""
    return min(chains, key=lambda chain: (not _chain_definitive(chain), chain.id))


def _chain_evidence(chain: Chain) -> list[VerdictEvidence]:
    """步骤证据，保持链上顺序。"""
    evidence: list[VerdictEvidence] = []
    for step in chain.steps:
        source = step.source
        evidence.append(
            VerdictEvidence(
                step=step.order,
                sink=step.sink,
                description=step.description,
                file=source.file if source is not None else "",
                line=source.line if source is not None else 0,
                snippet=source.snippet if source is not None else "",
            )
        )
    return evidence


def _counterexample_detail(item: CounterExample) -> VerdictCounterexample:
    """反例 → 输出结构。"""
    source = item.source
    return VerdictCounterexample(
        entry_id=item.entry_id,
        entry_kind=item.entry_kind.value,
        failed_judgment=item.failed_judgment,
        reason=item.reason,
        file=source.file if source is not None else "",
        line=source.line if source is not None else 0,
    )


# --- 回答 → 假设 -----------------------------------------------------------


def _merge_answers(
    claim: Claim, answers: AnswersDoc | None, questions: list[Question]
) -> list[str]:
    """校验回答并转成假设 ID 列表；回答永远不升格为事实。"""
    used = [assumption.id for assumption in claim.assumptions]
    if answers is None:
        return used
    by_id = {question.question_id: question for question in questions}
    for answer in answers.answers:
        question = by_id.get(answer.question_id)
        if question is None:
            raise ClaimError(
                f"answers 引用了不存在的问题：{answer.question_id!r}"
                "（先运行 reachscope questions 获取当前问题列表）"
            )
        _validate_answer_value(question, answer)
        used.append(f"answer:{answer.question_id}")
    return used


def _validate_answer_value(question: Question, answer: Answer) -> None:
    """按问题类型校验回答取值。"""
    value = answer.value.strip()
    if question.answer_type is AnswerType.BOOLEAN:
        if value.lower() not in ("true", "false", "yes", "no", "1", "0"):
            raise ClaimError(
                f"问题 {question.question_id} 需要布尔回答（true/false），实际 {value!r}"
            )
        return
    if question.answer_type is AnswerType.ENUM and value not in question.candidates:
        allowed = ", ".join(question.candidates)
        raise ClaimError(
            f"问题 {question.question_id} 的取值必须是：{allowed}；实际 {value!r}"
        )


# --- 裁决构造与覆盖度闸门 ---------------------------------------------------


def _negative(
    claim: Claim,
    coverage: CoverageView,
    *,
    reason_code: ReasonCode,
    failed_judgment: str | None,
    assumptions_used: list[str],
    subjects: set[str],
    questions: list[Question],
    counterexample: CounterExample | None = None,
    evidence: list[VerdictEvidence] | None = None,
    reason_override: str | None = None,
) -> Verdict:
    """Reject only a direct manifest access condition, never a missing path."""
    detail = (
        _counterexample_detail(counterexample)
        if counterexample is not None
        else None
    )
    if detail is not None and reason_override:
        detail = replace(detail, reason=reason_override)
    return Verdict(
        claim_id=claim.claim_id,
        status=VerdictStatus.REFUTED,
        reason_code=reason_code,
        failed_judgment=failed_judgment,
        evidence=list(evidence or []),
        counterexample=detail,
        missing_facts=_facts(questions, subjects),
        coverage=coverage,
        assumptions_used=list(assumptions_used),
    )


def _undecidable(
    claim: Claim,
    *,
    reason_code: ReasonCode,
    failed_judgment: str | None,
    assumptions_used: list[str],
    subjects: set[str],
    questions: list[Question],
    counterexample: CounterExample | None,
    evidence: list[VerdictEvidence],
) -> Verdict:
    """构造 UNDECIDABLE 裁决（coverage 由 `_finalize` 填）。"""
    return Verdict(
        claim_id=claim.claim_id,
        status=VerdictStatus.UNDECIDABLE,
        reason_code=reason_code,
        failed_judgment=failed_judgment,
        evidence=list(evidence),
        counterexample=(
            _counterexample_detail(counterexample)
            if counterexample is not None
            else None
        ),
        missing_facts=_facts(questions, subjects),
        coverage=CoverageView(),
        assumptions_used=list(assumptions_used),
    )


def _finalize(
    verdict: Verdict,
    coverage: CoverageView,
    questions: list[Question],
    subjects: set[str],
    assumptions_used: list[str],
) -> Verdict:
    """Attach explicit scope and conservatively handle actual analysis failures."""
    if coverage.report_usable:
        return replace(verdict, coverage=coverage, statement=_statement(verdict))
    missing = _facts(questions, subjects)
    degraded = replace(
        verdict,
        status=VerdictStatus.UNDECIDABLE,
        reason_code=ReasonCode.OUTSIDE_COVERAGE,
        missing_facts=missing or verdict.missing_facts,
        coverage=coverage,
        assumptions_used=assumptions_used,
    )
    return replace(degraded, statement=_statement(degraded))


def _statement(verdict: Verdict) -> str:
    """Describe exactly what was checked so status names cannot imply more."""
    if verdict.status is VerdictStatus.SUPPORTED:
        return (
            "A matching candidate path has complete evidence in this static-analysis report. "
            "Runtime feasibility and vulnerability impact have not been independently proven."
        )
    if verdict.status is VerdictStatus.SUPPORTED_WITH_ASSUMPTIONS:
        return (
            "The report contains a matching candidate path; supplied assumptions remain unverified. "
            "This does not establish runtime feasibility or a vulnerability."
        )
    if verdict.status is VerdictStatus.REFUTED:
        return (
            "The component's manifest access condition blocks this direct zero-permission entry "
            "under the report's configuration. Indirect paths and application safety are not decided."
        )
    messages = {
        ReasonCode.ENTRY_NOT_FOUND: "The requested entry is absent from this report.",
        ReasonCode.SINK_MISMATCH: "No candidate path in this report matches the requested sink.",
        ReasonCode.STEP_MISMATCH: "No candidate path in this report matches the asserted step order.",
        ReasonCode.OUTSIDE_COVERAGE: "The report has analysis failures or warnings that require review.",
        ReasonCode.IMPL_MISSING: "The report does not contain the component implementation.",
        ReasonCode.EVIDENCE_INCOMPLETE: "The matching candidate path has incomplete report evidence.",
        ReasonCode.NO_ANALYSIS_RESULT: "The report has no candidate path for this entry.",
        ReasonCode.NEGATIVE_NOT_DEFINITIVE: "The report's counterexample does not prove unreachability.",
    }
    return (
        messages.get(verdict.reason_code, "The available report evidence is insufficient.")
        + " Actual program unreachability and application safety are not established."
    )


def _facts(questions: list[Question], subjects: set[str]) -> list[MissingFact]:
    """挑出与本次裁决相关的缺口；全局问题（警告/加固）始终纳入。"""
    facts = [
        MissingFact(
            question_id=question.question_id,
            code=question.code,
            question=question.question,
            why=question.why,
        )
        for question in questions
        if question.subject_kind == "global" or question.subject_id in subjects
    ]
    return facts


__all__ = [
    "MissingFact",
    "ReasonCode",
    "Verdict",
    "VerdictCounterexample",
    "VerdictEvidence",
    "VerdictStatus",
    "render_verdict",
    "verify_claim",
]
