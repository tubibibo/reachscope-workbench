"""Regression tests for report consistency versus security/coverage claims."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from reachscope.analyze.pipeline import analyze_workdir
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
    Report,
    SourceLoc,
    Step,
)
from reachscope.protocol.answer import AnswersDoc
from reachscope.protocol.claims import Claim, ClaimError
from reachscope.protocol.coverage import CoverageView
from reachscope.protocol.questions import collect_questions
from reachscope.protocol.verdict import ReasonCode, VerdictStatus, verify_claim

MAIN = "com.example.app.MainActivity"


def _candidate() -> Chain:
    return Chain(
        id="candidate",
        entries=[MAIN],
        steps=[
            Step(
                order=0,
                sink="webview",
                source=SourceLoc("smali/com/example/app/MainActivity.smali", 8, "invoke"),
            )
        ],
        judgments=[
            Judgment(name="J4", result=JudgmentResult.UNKNOWN, confidence=Level.LOW),
            Judgment(name="J6", result=JudgmentResult.PASS, confidence=Level.HIGH),
        ],
        evidence_complete=True,
    )


def _report(*, chain: Chain | None = None) -> Report:
    return Report(
        meta=Meta(package="com.example.app"),
        components=[Component(name=MAIN, type=ComponentType.ACTIVITY, exported=True)],
        chains=[_candidate() if chain is None else chain],
        counter_examples=[
            CounterExample(
                entry_id=MAIN,
                entry_kind=EntryKind.COMPONENT,
                failed_judgment="J4",
                reason="no bridge + WebView pair for this chain",
            )
        ],
    )


def _claim(**values: object) -> Claim:
    payload: dict[str, object] = {
        "kind": "reachability",
        "entry": {"kind": "component", "name": MAIN},
        "sink": {"kind": "webview"},
    }
    payload.update(values)
    return Claim.from_dict(payload)


def test_risk_counterexample_does_not_hide_matching_candidate_path() -> None:
    verdict = verify_claim(_report(), _claim())
    assert verdict.status is VerdictStatus.SUPPORTED
    assert verdict.reason_code is ReasonCode.CHAIN_FOUND
    assert verdict.scope == "static_analysis_report"
    assert "not been independently proven" in verdict.statement
    assert verdict.coverage.closed_world is False
    assert verdict.coverage.report_usable is True
    assert verdict.coverage.negative_conclusions_limited is True
    assert len(verdict.evidence) == 1


@pytest.mark.parametrize("risk_judgment", ["J3", "J4"])
def test_impact_and_bridge_risk_are_not_path_proof_conditions(risk_judgment: str) -> None:
    chain = replace(
        _candidate(),
        judgments=[
            Judgment(name=risk_judgment, result=JudgmentResult.FAIL, confidence=Level.UNKNOWN),
            Judgment(name="J6", result=JudgmentResult.PASS, confidence=Level.HIGH),
        ],
    )
    assert verify_claim(_report(chain=chain), _claim()).status is VerdictStatus.SUPPORTED


@pytest.mark.parametrize("path_judgment", ["J1", "J2", "J5", "J6"])
def test_unknown_path_judgment_cannot_be_supported(path_judgment: str) -> None:
    chain = replace(
        _candidate(),
        judgments=[
            Judgment(name="J6", result=JudgmentResult.PASS, confidence=Level.HIGH),
            Judgment(name=path_judgment, result=JudgmentResult.UNKNOWN, confidence=Level.LOW),
        ],
    )
    verdict = verify_claim(_report(chain=chain), _claim())
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.EVIDENCE_INCOMPLETE


@pytest.mark.parametrize("source", [None, SourceLoc(), SourceLoc("x.smali", 0)])
def test_completeness_flag_cannot_replace_real_source_locations(source: SourceLoc | None) -> None:
    chain = replace(_candidate(), steps=[Step(sink="webview", source=source)])
    verdict = verify_claim(_report(chain=chain), _claim())
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.EVIDENCE_INCOMPLETE


def test_matching_evidence_is_preferred_over_lower_id_incomplete_candidate() -> None:
    complete = _candidate()
    incomplete = replace(complete, id="a", judgments=[])
    report = replace(_report(), chains=[incomplete, complete])
    assert verify_claim(report, _claim()).status is VerdictStatus.SUPPORTED


def test_report_mismatch_never_establishes_program_unreachability() -> None:
    report = _report()
    verdict = verify_claim(report, _claim(asserted_steps=[{"sink": "file"}]))
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.STEP_MISMATCH
    assert "in this report" in verdict.statement
    assert "not established" in verdict.statement
    assert verdict.evidence


def test_absent_sink_is_not_a_whole_program_negative() -> None:
    verdict = verify_claim(_report(), _claim(sink={"kind": "file"}))
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.SINK_MISMATCH


def test_component_identity_cannot_fall_back_when_name_and_id_disagree() -> None:
    report = _report()
    for entry in (
        {"kind": "component", "id": report.components[0].id, "name": "Missing"},
        {"kind": "component", "id": "missing", "name": MAIN},
    ):
        with pytest.raises(ClaimError, match="不同组件"):
            verify_claim(report, _claim(entry=entry))


def test_deeplink_identity_cannot_mix_uri_and_id() -> None:
    deeplink = Deeplink(id="dl-1", scheme="example", host="a", component=MAIN)
    report = replace(_report(), deeplinks=[deeplink])
    for entry in (
        {"kind": "deeplink", "id": "dl-1", "name": "example://missing"},
        {"kind": "deeplink", "id": "missing", "name": "example://a"},
    ):
        with pytest.raises(ClaimError, match="不同深链"):
            verify_claim(report, _claim(entry=entry))


def test_manifest_block_only_refutes_direct_access_condition() -> None:
    report = replace(
        _report(),
        components=[Component(name=MAIN, type=ComponentType.ACTIVITY, exported=False)],
    )
    verdict = verify_claim(report, _claim())
    assert verdict.status is VerdictStatus.REFUTED
    assert "direct zero-permission entry" in verdict.statement
    assert "Indirect paths" in verdict.statement
    assert verdict.coverage.closed_world is False


def test_warning_is_disclosed_and_prevents_support() -> None:
    report = replace(_report(), meta=Meta(package="com.example.app", warnings=["unknown opcode"]))
    verdict = verify_claim(report, _claim())
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.reason_code is ReasonCode.OUTSIDE_COVERAGE
    assert verdict.coverage.report_usable is False
    assert verdict.coverage.reasons
    assert verdict.coverage.limitations


def test_answers_to_risk_questions_remain_explicit_assumptions() -> None:
    report = _report()
    question = next(item for item in collect_questions(report) if item.code == "JUDGMENT_UNKNOWN")
    answers = AnswersDoc.from_dict(
        {"schema_version": "0.1", "answers": [{"question_id": question.question_id, "value": "yes"}]}
    )
    verdict = verify_claim(report, _claim(), answers)
    assert verdict.status is VerdictStatus.SUPPORTED_WITH_ASSUMPTIONS
    assert verdict.assumptions_used == [f"answer:{question.question_id}"]
    assert "unverified" in verdict.statement


def test_answers_never_fill_missing_code_evidence() -> None:
    report = _report(chain=replace(_candidate(), evidence_complete=False))
    question = next(item for item in collect_questions(report) if item.code == "EVIDENCE_INCOMPLETE")
    answers = AnswersDoc.from_dict(
        {"answers": [{"question_id": question.question_id, "value": "true"}]}
    )
    verdict = verify_claim(report, _claim(), answers)
    assert verdict.status is VerdictStatus.UNDECIDABLE
    assert verdict.assumptions_used


def test_fixed_limits_survive_clean_report() -> None:
    coverage = CoverageView.from_report(Report())
    assert coverage.report_usable is True
    assert coverage.closed_world is False
    limits = " ".join(coverage.limitations)
    for keyword in ("depth 4", "one explicit Intent", "branch", "Reflection", "JNI"):
        assert keyword in limits


@pytest.mark.parametrize("schema", ["0.1", "0.2"])
def test_protocol_input_migration(schema: str) -> None:
    claim = _claim(schema_version=schema)
    assert claim.schema_version == "0.2"
    assert verify_claim(_report(), claim).schema_version == "0.2"
    assert AnswersDoc.from_dict({"schema_version": schema}).schema_version == "0.2"


@pytest.mark.parametrize("schema", ["0.3", "1.0", "future"])
def test_unsupported_protocol_versions_are_rejected(schema: str) -> None:
    with pytest.raises(ClaimError, match="schema_version"):
        _claim(schema_version=schema)
    with pytest.raises(ClaimError, match="schema_version"):
        AnswersDoc.from_dict({"schema_version": schema})


def test_real_analyzer_path_without_bridge_can_be_queried(tmp_path: Path) -> None:
    """Exercise the coupling fix using code parsed by the existing analyzer."""
    (tmp_path / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="com.example.app"><uses-sdk android:targetSdkVersion="28"/>'
        '<application><activity android:name=".MainActivity" android:exported="true"/>'
        '</application></manifest>',
        encoding="utf-8",
    )
    smali = tmp_path / "smali/com/example/app/MainActivity.smali"
    smali.parent.mkdir(parents=True)
    smali.write_text(
        ".class public Lcom/example/app/MainActivity;\n"
        ".super Landroid/app/Activity;\n"
        ".method public onCreate(Landroid/os/Bundle;)V\n"
        "    .registers 5\n"
        "    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;\n"
        "    move-result-object v0\n"
        "    invoke-virtual {v0}, Landroid/content/Intent;->getDataString()Ljava/lang/String;\n"
        "    move-result-object v1\n"
        "    new-instance v2, Landroid/webkit/WebView;\n"
        "    invoke-direct {v2, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V\n"
        "    invoke-virtual {v2, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V\n"
        "    return-void\n"
        ".end method\n",
        encoding="utf-8",
    )
    report = analyze_workdir(tmp_path)
    assert report.chains
    assert not report.findings
    assert any(item.failed_judgment == "J4" for item in report.counter_examples)
    verdict = verify_claim(report, _claim())
    assert verdict.status is VerdictStatus.SUPPORTED
    assert verdict.evidence[0].file == "smali/com/example/app/MainActivity.smali"
