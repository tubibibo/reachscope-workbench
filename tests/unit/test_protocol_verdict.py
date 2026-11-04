"""裁决引擎：状态矩阵、闭世界闸门、确定性。"""

from __future__ import annotations

import json

import pytest

from reachscope.ir.model import (
    Chain,
    Component,
    ComponentType,
    CounterExample,
    Deeplink,
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
from reachscope.protocol.answer import AnswersDoc
from reachscope.protocol.claims import Claim, ClaimError
from reachscope.protocol.question import AnswerType, Question
from reachscope.protocol.verdict import (
    ReasonCode,
    VerdictStatus,
    _validate_answer_value,
    render_verdict,
    verify_claim,
)

PACKAGE = "com.example.app"
MAIN = f"{PACKAGE}.MainActivity"


def _source(line: int = 10) -> SourceLoc:
    return SourceLoc(file="smali/com/example/app/MainActivity.smali", line=line, snippet="invoke")


def _component(
    *,
    name: str = MAIN,
    exported: bool = True,
    impl_present: bool = True,
    permission: str | None = None,
    protection: str | None = None,
) -> Component:
    return Component(
        name=name,
        type=ComponentType.ACTIVITY,
        exported=exported,
        permission=permission,
        permission_protection=protection,
        impl_present=impl_present,
        impl_reason=None if impl_present else "implementation class not found in APK",
        source=_source(1),
    )


def _chain(
    *,
    chain_id: str = "chain-1",
    entry: str = MAIN,
    sinks: tuple[str, ...] = ("webview", "bridge_method", "file"),
    evidence_complete: bool = True,
    judgments: list[Judgment] | None = None,
) -> Chain:
    steps = [
        Step(order=index, description=f"step {index}", sink=sink, source=_source(index + 2))
        for index, sink in enumerate(sinks)
    ]
    return Chain(
        id=chain_id,
        entries=[entry],
        steps=steps,
        judgments=(
            judgments
            if judgments is not None
            else [Judgment(name="J6", result=JudgmentResult.PASS, confidence=Level.HIGH)]
        ),
        evidence_complete=evidence_complete,
    )


def _report(
    *,
    components: list[Component] | None = None,
    chains: list[Chain] | None = None,
    counter_examples: list[CounterExample] | None = None,
    deeplinks: list[Deeplink] | None = None,
    warnings: list[str] | None = None,
    analyzable: bool = True,
) -> Report:
    return Report(
        meta=Meta(package=PACKAGE, warnings=list(warnings or [])),
        protection=Protection(
            detected=not analyzable,
            labels=[] if analyzable else ["packer::dexguard"],
            analyzable=analyzable,
        ),
        components=[_component()] if components is None else components,
        chains=[] if chains is None else chains,
        counter_examples=list(counter_examples or []),
        deeplinks=list(deeplinks or []),
    )


def _claim(**overrides: object) -> Claim:
    data: dict[str, object] = {
        "schema_version": "0.1",
        "kind": "reachability",
        "entry": {"kind": "component", "name": MAIN},
        "sink": {"kind": "file"},
    }
    data.update(overrides)
    return Claim.from_dict(data)


def test_supported_chain() -> None:
    verdict = verify_claim(_report(chains=[_chain()]), _claim())
    assert verdict.status is VerdictStatus.SUPPORTED
    assert verdict.reason_code is ReasonCode.CHAIN_FOUND
    assert len(verdict.evidence) == 3
    assert verdict.evidence[2].sink == "file"
    assert verdict.evidence[2].line == 4
    assert verdict.coverage.closed_world is False
    assert verdict.coverage.report_usable is True
    assert verdict.assumptions_used == []


def test_supported_with_assumptions() -> None:
    claim = _claim(
        assumptions=[{"id": "a-1", "text": "page URL is attacker controlled"}]
    )
    verdict = verify_claim(_report(chains=[_chain()]), claim)
    assert verdict.status is VerdictStatus.SUPPORTED_WITH_ASSUMPTIONS
    assert verdict.assumptions_used == ["a-1"]


def test_short_component_name_is_normalized() -> None:
    verdict = verify_claim(
        _report(chains=[_chain()]), _claim(entry={"kind": "component", "name": ".MainActivity"})
    )
    assert verdict.status is VerdictStatus.SUPPORTED


def test_component_id_resolves() -> None:
    component = _component()
    verdict = verify_claim(
        _report(components=[component], chains=[_chain()]),
        _claim(entry={"kind": "component", "id": component.id}),
    )
    assert verdict.status is VerdictStatus.SUPPORTED


def test_step_mismatch_is_undecidable_and_echoes_real_steps() -> None:
    claim = _claim(asserted_steps=[{"sink": "bridge_method"}, {"sink": "webview"}])
    verdict = verify_claim(_report(chains=[_chain()]), claim)
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.STEP_MISMATCH
    assert [item.sink for item in verdict.evidence] == [
        "webview",
        "bridge_method",
        "file",
    ]


def test_sink_mismatch_is_undecidable() -> None:
    verdict = verify_claim(
        _report(chains=[_chain(sinks=("webview", "bridge_method"))]), _claim()
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.SINK_MISMATCH


def test_entry_not_found_is_undecidable() -> None:
    verdict = verify_claim(
        _report(), _claim(entry={"kind": "component", "name": f"{PACKAGE}.Nope"})
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.ENTRY_NOT_FOUND


def test_unexported_component_is_refuted() -> None:
    verdict = verify_claim(_report(components=[_component(exported=False)]), _claim())
    assert verdict.status is VerdictStatus.REFUTED
    assert verdict.reason_code is ReasonCode.NOT_ZERO_PERMISSION
    assert verdict.failed_judgment == "J1"


def test_signature_permission_is_refuted() -> None:
    component = _component(permission="p", protection="signature")
    verdict = verify_claim(_report(components=[component]), _claim())
    assert verdict.status is VerdictStatus.REFUTED
    assert verdict.reason_code is ReasonCode.NOT_ZERO_PERMISSION


def test_missing_implementation_is_undecidable_not_refuted() -> None:
    verdict = verify_claim(_report(components=[_component(impl_present=False)]), _claim())
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.IMPL_MISSING
    assert verdict.failed_judgment == "J2"
    assert any(fact.code == "IMPL_MISSING" for fact in verdict.missing_facts)


@pytest.mark.parametrize("judgment", ["J4", "J5", "J6"])
def test_non_definitive_counterexample_is_undecidable(judgment: str) -> None:
    counter_example = CounterExample(
        entry_id=MAIN,
        entry_kind=EntryKind.DEEPLINK,
        failed_judgment=judgment,
        reason="blocked or unknown",
        source=_source(20),
    )
    verdict = verify_claim(
        _report(chains=[], counter_examples=[counter_example]), _claim()
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.NEGATIVE_NOT_DEFINITIVE
    assert verdict.failed_judgment == judgment
    assert any(fact.code == "NEGATIVE_NOT_DEFINITIVE" for fact in verdict.missing_facts)


def test_j1_counterexample_is_refuted_with_detail() -> None:
    counter_example = CounterExample(
        entry_id=MAIN,
        entry_kind=EntryKind.COMPONENT,
        failed_judgment="J1",
        reason="signature-level permission",
        source=_source(30),
    )
    verdict = verify_claim(
        _report(
            components=[_component(permission="p", protection="signature")],
            counter_examples=[counter_example],
        ),
        _claim(),
    )
    assert verdict.status is VerdictStatus.REFUTED
    assert verdict.counterexample is not None
    assert verdict.counterexample.reason == "signature-level permission"
    assert verdict.counterexample.line == 30


def test_incomplete_evidence_is_undecidable() -> None:
    verdict = verify_claim(
        _report(chains=[_chain(evidence_complete=False)]), _claim()
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.EVIDENCE_INCOMPLETE
    assert any(fact.code == "EVIDENCE_INCOMPLETE" for fact in verdict.missing_facts)


def test_unknown_risk_judgment_does_not_block_path_support() -> None:
    judgments = [
        Judgment(
            name="J4",
            result=JudgmentResult.UNKNOWN,
            confidence=Level.LOW,
            reason="no bridge",
        ),
        Judgment(name="J6", result=JudgmentResult.PASS, confidence=Level.HIGH),
    ]
    verdict = verify_claim(_report(chains=[_chain(judgments=judgments)]), _claim())
    assert verdict.status is VerdictStatus.SUPPORTED
    assert verdict.reason_code is ReasonCode.CHAIN_FOUND
    assert verdict.scope == "static_analysis_report"


def test_warning_forces_undecidable_even_for_found_chain() -> None:
    verdict = verify_claim(
        _report(chains=[_chain()], warnings=["x.smali：跳过 2 行未知语法"]), _claim()
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.OUTSIDE_COVERAGE
    assert verdict.coverage.closed_world is False
    assert any(fact.code == "INDEX_WARNING" for fact in verdict.missing_facts)


def test_hardened_report_never_refutes() -> None:
    verdict = verify_claim(
        _report(components=[], analyzable=False),
        _claim(entry={"kind": "component", "name": MAIN}),
    )
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.OUTSIDE_COVERAGE
    assert any(
        fact.code == "PROTECTION_UNANALYZABLE" for fact in verdict.missing_facts
    )


def test_no_analysis_result_is_undecidable() -> None:
    verdict = verify_claim(_report(chains=[]), _claim())
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.NO_ANALYSIS_RESULT


def test_deeplink_resolution_by_uri_and_by_id() -> None:
    deeplink = Deeplink(
        id="dl-1",
        scheme="myapp",
        host="open.example.com",
        component=MAIN,
        source=_source(40),
    )
    report = _report(chains=[_chain()], deeplinks=[deeplink])
    for entry in (
        {"kind": "deeplink", "name": "myapp://open.example.com"},
        {"kind": "deeplink", "id": "dl-1"},
    ):
        verdict = verify_claim(report, _claim(entry=entry))
        assert verdict.status is VerdictStatus.SUPPORTED


def test_deeplink_ambiguous_uri_raises() -> None:
    first = Deeplink(id="dl-1", scheme="myapp", host="h", component=MAIN)
    second = Deeplink(id="dl-2", scheme="myapp", host="h", component=MAIN)
    report = _report(chains=[], deeplinks=[first, second])
    with pytest.raises(ClaimError, match="多个深链"):
        verify_claim(report, _claim(entry={"kind": "deeplink", "name": "myapp://h"}))


def test_component_id_and_name_must_agree() -> None:
    other = _component(name=f"{PACKAGE}.Other")
    report = _report(components=[_component(), other], chains=[])
    with pytest.raises(ClaimError, match="不同组件"):
        verify_claim(
            report,
            _claim(entry={"kind": "component", "id": other.id, "name": MAIN}),
        )


def test_answers_unknown_question_is_input_error() -> None:
    answers = AnswersDoc.from_dict(
        {"answers": [{"question_id": "00000000", "value": "false"}]}
    )
    with pytest.raises(ClaimError, match="不存在的问题"):
        verify_claim(_report(chains=[_chain()]), _claim(), answers)


def test_answers_become_assumptions_and_cap_status() -> None:
    report = _report(
        chains=[_chain(evidence_complete=False)],
    )
    from reachscope.protocol.questions import collect_questions

    question = next(
        item for item in collect_questions(report) if item.code == "EVIDENCE_INCOMPLETE"
    )
    answers = AnswersDoc.from_dict(
        {"answers": [{"question_id": question.question_id, "value": "true"}]}
    )
    verdict = verify_claim(report, _claim(), answers)
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.assumptions_used == [f"answer:{question.question_id}"]


def test_answers_do_not_turn_undecidable_into_supported() -> None:
    report = _report(
        chains=[_chain()],
        warnings=["manifest.xml：无法解析某属性"],
    )
    from reachscope.protocol.questions import collect_questions

    question = next(
        item for item in collect_questions(report) if item.code == "INDEX_WARNING"
    )
    answers = AnswersDoc.from_dict(
        {"answers": [{"question_id": question.question_id, "value": "no"}]}
    )
    verdict = verify_claim(report, _claim(), answers)
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.OUTSIDE_COVERAGE
    assert verdict.assumptions_used == [f"answer:{question.question_id}"]


def test_boolean_answer_validation() -> None:
    question = Question(question_id="q", answer_type=AnswerType.BOOLEAN)
    with pytest.raises(ClaimError, match="布尔回答"):
        _validate_answer_value(
            question,
            AnswersDoc.from_dict(
                {"answers": [{"question_id": "q", "value": "maybe"}]}
            ).answers[0],
        )


def test_enum_answer_validation() -> None:
    question = Question(
        question_id="q",
        answer_type=AnswerType.ENUM,
        candidates=["a", "b"],
    )
    with pytest.raises(ClaimError, match="取值必须是"):
        _validate_answer_value(
            question,
            AnswersDoc.from_dict(
                {"answers": [{"question_id": "q", "value": "c"}]}
            ).answers[0],
        )


def test_render_verdict_is_deterministic() -> None:
    report = _report(chains=[_chain()])
    first = render_verdict(verify_claim(report, _claim()))
    second = render_verdict(verify_claim(report, _claim()))
    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["status"] == "SUPPORTED"
    assert payload["coverage"]["closed_world"] is False
    assert payload["coverage"]["report_usable"] is True
