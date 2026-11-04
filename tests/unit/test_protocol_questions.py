"""开放问题：来源限定、排序与确定性。"""

from __future__ import annotations

import json

from reachscope.ir.model import (
    Chain,
    Component,
    ComponentType,
    CounterExample,
    EntryKind,
    Judgment,
    JudgmentResult,
    Level,
    Meta,
    Protection,
    Report,
    SourceLoc,
    Step,
)
from reachscope.protocol.questions import (
    collect_questions,
    questions_document,
    render_questions,
)

MAIN = "com.example.app.MainActivity"


def _report(
    *,
    chains: list[Chain] | None = None,
    components: list[Component] | None = None,
    counter_examples: list[CounterExample] | None = None,
    warnings: list[str] | None = None,
    analyzable: bool = True,
) -> Report:
    return Report(
        meta=Meta(package="com.example.app", warnings=list(warnings or [])),
        protection=Protection(
            detected=not analyzable,
            labels=[] if analyzable else ["packer::dexguard"],
            analyzable=analyzable,
        ),
        components=[] if components is None else components,
        chains=[] if chains is None else chains,
        counter_examples=list(counter_examples or []),
    )


def test_incomplete_chain_generates_question_with_evidence() -> None:
    chain = Chain(
        id="c1",
        entries=[MAIN],
        steps=[
            Step(order=0, sink="webview", source=SourceLoc("a.smali", 3)),
            Step(order=1, sink="file"),
        ],
        evidence_complete=False,
    )
    questions = collect_questions(_report(chains=[chain]))
    assert len(questions) == 1
    question = questions[0]
    assert question.code == "EVIDENCE_INCOMPLETE"
    assert question.subject_id == "c1"
    assert question.evidence is not None
    assert question.evidence.file == "a.smali"
    assert question.evidence.line == 3


def test_unknown_judgment_generates_one_question_per_judgment() -> None:
    chain = Chain(
        id="c1",
        entries=[MAIN],
        steps=[],
        evidence_complete=True,
        judgments=[
            Judgment(
                name="J4",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="no bridge",
                source=SourceLoc("b.smali", 9),
            ),
            Judgment(
                name="J5",
                result=JudgmentResult.PASS,
                confidence=Level.UNKNOWN,
                reason="low confidence",
            ),
        ],
    )
    questions = collect_questions(_report(chains=[chain]))
    assert [question.code for question in questions] == [
        "JUDGMENT_UNKNOWN",
        "JUDGMENT_UNKNOWN",
    ]
    assert len({question.question_id for question in questions}) == 2


def test_missing_impl_generates_boolean_question() -> None:
    component = Component(
        name=MAIN,
        type=ComponentType.ACTIVITY,
        exported=True,
        impl_present=False,
        impl_reason="implementation class not found in APK",
        source=SourceLoc("AndroidManifest.xml", 12),
    )
    questions = collect_questions(_report(components=[component]))
    assert len(questions) == 1
    assert questions[0].code == "IMPL_MISSING"
    assert questions[0].answer_type == "boolean"
    assert questions[0].subject_id == MAIN


def test_non_definitive_counterexamples_generate_questions() -> None:
    counter_examples = [
        CounterExample(
            entry_id=MAIN,
            entry_kind=EntryKind.DEEPLINK,
            failed_judgment=judgment,
            reason="blocked",
        )
        for judgment in ("J4", "J5", "J6", "J1", "J2")
    ]
    questions = collect_questions(_report(counter_examples=counter_examples))
    assert [question.code for question in questions] == [
        "NEGATIVE_NOT_DEFINITIVE",
        "NEGATIVE_NOT_DEFINITIVE",
        "NEGATIVE_NOT_DEFINITIVE",
    ]


def test_warnings_and_hardening_generate_global_questions() -> None:
    report = _report(
        warnings=["x.smali：跳过 2 行未知语法", "AndroidManifest.xml：无法解析属性"],
        analyzable=False,
    )
    questions = collect_questions(report)
    codes = sorted(question.code for question in questions)
    assert codes == ["INDEX_WARNING", "PROTECTION_UNANALYZABLE"]
    assert all(question.subject_kind == "global" for question in questions)


def test_questions_are_sorted_deduped_and_stable() -> None:
    report = _report(
        warnings=["b", "a"],
        chains=[Chain(id="c1", entries=[MAIN], evidence_complete=False)],
    )
    first = collect_questions(report)
    second = collect_questions(report)
    assert [question.question_id for question in first] == [
        question.question_id for question in second
    ]
    keys = [
        (question.subject_kind, question.subject_id, question.code)
        for question in first
    ]
    assert keys == sorted(keys)
    assert len({question.question_id for question in first}) == len(first)


def test_clean_report_has_no_questions() -> None:
    assert collect_questions(_report()) == []


def test_render_questions_is_deterministic_json() -> None:
    report = _report(warnings=["w"])
    first = render_questions(questions_document(report))
    second = render_questions(questions_document(report))
    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["schema_version"] == "0.2"
    assert payload["questions"][0]["code"] == "INDEX_WARNING"
