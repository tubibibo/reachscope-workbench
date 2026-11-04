"""Public evidence queries over real decoded fixtures, including misuse boundaries."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from reachscope.analyze.pipeline import analyze_workdir
from reachscope.artifacts import ArtifactStore
from reachscope.ir.model import Judgment, JudgmentResult, Level, Meta, Report, Step
from reachscope.query import EvidenceSession, QueryError

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"
POSITIVE = CASES / "01_positive_deeplink_bridge_sink"
MAIN = "com.example.app.MainActivity"
MAIN_REF = "Lcom/example/app/MainActivity;->onCreate(Landroid/os/Bundle;)V"


def _session(tmp_path: Path, report: Report | None = None, case: Path = POSITIVE) -> EvidenceSession:
    if report is None:
        report = analyze_workdir(case, analyzed_at="2026-11-01T00:00:00Z")
    artifact = ArtifactStore(tmp_path / "artifacts").create(case, report)
    return EvidenceSession(artifact)


@pytest.fixture
def session(tmp_path: Path) -> EvidenceSession:
    return _session(tmp_path)


def _claim(entry: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "reachability",
        "entry": entry or {"kind": "component", "name": MAIN},
        "sink": {"kind": "webview"},
        "asserted_steps": [{"sink": "webview"}],
    }


def test_overview_binds_results_to_analysis_identity(session: EvidenceSession) -> None:
    result = session.overview()
    assert result["artifact_id"] == session.artifact.id
    assert result["scope"] == "static_analysis_report"
    assert result["data"]["package"] == "com.example.app"
    assert result["data"]["counts"]["chains"] >= 1
    assert result["data"]["metadata"]["method_count"] >= 2
    assert "files" not in result["data"]["metadata"]
    assert result["limitations"]
    assert "method" in result["data"]["operations"]
    json.dumps(result, allow_nan=False)


def test_entries_paginate_and_filter_component_and_deeplink(session: EvidenceSession) -> None:
    first = session.entries(limit=1)
    assert len(first["data"]) == 1
    assert first["pagination"] == {
        "offset": 0, "limit": 1, "total": 2, "truncated": True, "next_offset": 1
    }
    second = session.entries(offset=1, limit=1)
    assert second["pagination"]["next_offset"] is None
    assert {first["data"][0]["kind"], second["data"][0]["kind"]} == {"component", "deeplink"}
    assert len(session.entries(query="MAINACTIVITY")["data"]) == 2
    assert session.entries(query="does.not.exist")["data"] == []
    assert session.entries(offset=100)["data"] == []


def test_entry_and_source_references_are_scoped_and_code_is_locatable(session: EvidenceSession) -> None:
    entry = session.entries(query=MAIN)["data"][0]
    assert entry["reference"].startswith(session.artifact.id + ":component:")
    assert entry["source"]["reference"].startswith(session.artifact.id + ":source:")
    assert entry["source"]["sha256"]
    assert entry["source"]["saved_source_available"] is True
    assert entry["source"]["snippet_is_context"] is False
    assert entry["implementation"]["evidence_type"] == "static_inference"


def test_chain_filter_resolves_name_id_and_deeplink_to_same_paths(session: EvidenceSession) -> None:
    entries = session.entries()["data"]
    component = next(item for item in entries if item["kind"] == "component")
    deeplink = next(item for item in entries if item["kind"] == "deeplink")
    expected = session.chains(entry=MAIN)["data"]
    assert expected
    for selector in (
        component["id"], component["reference"], deeplink["id"],
        deeplink["reference"], deeplink["uri"],
    ):
        assert session.chains(entry=selector)["data"] == expected
    assert all(item["evidence_type"] == "static_inference" for item in expected)
    assert "rank" not in expected[0]


def test_chain_detail_distinguishes_path_evidence_from_risk_rules(session: EvidenceSession) -> None:
    summary = session.chains()["data"][0]
    detail = session.chain(summary["reference"])["data"]
    assert detail == session.chain(summary["id"])["data"]
    assert detail["steps"]
    assert all(item["evidence_type"] == "static_inference" for item in detail["steps"])
    assert all(item["source"]["reference"] for item in detail["steps"])
    assert detail["risk_assessment"]["evidence_type"] == "risk_judgment"
    assert any(item["evidence_type"] == "risk_judgment" for item in detail["judgments"])
    assert detail["detail_limits"]["truncated"] is False
    detail["steps"][0]["description"] = "modified by caller"
    assert session.chain(summary["id"])["data"]["steps"][0]["description"] != "modified by caller"


def test_large_chain_details_explicitly_report_truncation(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    chain = report.chains[0]
    expanded = replace(
        chain,
        steps=[replace(chain.steps[0], order=index) for index in range(105)],
        judgments=[Judgment(name="J6", result=JudgmentResult.UNKNOWN) for _ in range(102)],
    )
    session = _session(tmp_path, replace(report, chains=[expanded]))
    detail = session.chain(chain.id)["data"]
    assert len(detail["steps"]) == 100
    assert len(detail["judgments"]) == 100
    assert detail["detail_limits"]["steps_total"] == 105
    assert detail["detail_limits"]["truncated"] is True
    checked = session.check(_claim())["data"]
    assert checked["detail_limits"]["truncated"] is True
    assert len(checked["verdict"]["evidence"]) <= 100


def test_method_paging_reconstructs_exact_saved_source(session: EvidenceSession) -> None:
    catalogue = session.methods(query="MainActivity;->onCreate", limit=1)
    assert len(catalogue["data"]) == 1
    assert catalogue["pagination"]["total"] == 1
    method = catalogue["data"][0]
    assert method["method_ref"] == MAIN_REF
    assert method["sha256"]
    pages: list[str] = []
    offset = 0
    while True:
        result = session.method(method["reference"], offset=offset, limit=7)
        body = result["data"]
        assert body["evidence_type"] == "code_fact"
        assert body["reference"] == method["reference"]
        assert body["sha256"] == method["sha256"]
        pages.append(body["code"])
        if result["pagination"]["next_offset"] is None:
            break
        offset = result["pagination"]["next_offset"]
    source = session.artifact.path / "source" / body["file"]
    data = source.read_bytes()
    expected = data.decode("utf-8").splitlines()[body["method_start_line"] - 1 : body["method_end_line"]]
    assert "\n".join(pages) == "\n".join(expected)
    assert hashlib.sha256(data).hexdigest() == body["sha256"]
    assert body["end_line"] == body["method_end_line"]
    assert session.method(MAIN_REF, offset=10000)["data"]["code"] == ""


def test_queries_do_not_reanalyze_or_decode(session: EvidenceSession, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("A query unexpectedly decoded or analyzed the APK")

    monkeypatch.setattr("reachscope.ingest.apk.run_apktool", unexpected)
    monkeypatch.setattr("reachscope.analyze.pipeline.analyze_workdir", unexpected)
    monkeypatch.setattr("reachscope.artifacts.store.build_index", unexpected)
    session.overview()
    session.entries()
    session.chains()
    session.chain(session.artifact.report.chains[0].id)
    session.methods()
    session.method(MAIN_REF)
    session.check(_claim())
    session.questions()


def test_check_is_explicitly_report_scoped_and_has_traceable_evidence(session: EvidenceSession) -> None:
    component = next(item for item in session.entries()["data"] if item["kind"] == "component")
    claim = _claim({"kind": "component", "id": component["reference"]})
    result = session.check(claim)
    assert result["data"]["evidence_type"] == "report_consistency_check"
    verdict = result["data"]["verdict"]
    assert verdict["status"] == "SUPPORTED"
    assert verdict["evidence"][0]["source"]["reference"].startswith(session.artifact.id)
    assert "does not independently" in result["data"]["interpretation"]
    assert claim["entry"]["id"] == component["reference"]  # Input not mutated.
    assert session.check(_claim({"kind": "component", "id": "", "name": MAIN}))["data"]["verdict"]["status"] == "SUPPORTED"


def test_check_does_not_claim_runtime_unreachability_for_mismatched_steps(session: EvidenceSession) -> None:
    claim = _claim()
    claim["asserted_steps"] = [{"sink": "command_exec"}]
    verdict = session.check(claim)["data"]["verdict"]
    assert verdict["status"] == "UNDECIDABLE"
    assert verdict["reason_code"] == "STEP_MISMATCH"


def test_signature_permission_is_a_local_manifest_block(tmp_path: Path) -> None:
    session = _session(tmp_path, case=CASES / "02_signature_permission")
    claim = _claim({"kind": "component", "name": "com.example.app.InternalActivity"})
    result = session.check(claim)
    assert result["data"]["verdict"]["status"] == "REFUTED"
    assert result["data"]["verdict"]["reason_code"] == "NOT_ZERO_PERMISSION"
    assert result["scope"] == "static_analysis_report"


def test_questions_preserve_gaps_and_scope_source_evidence(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    chain = replace(report.chains[0], evidence_complete=False)
    session = _session(tmp_path, replace(report, chains=[chain]))
    result = session.questions()["data"]
    assert result["evidence_type"] == "analysis_gap"
    gap = next(item for item in result["questions"] if item["code"] == "EVIDENCE_INCOMPLETE")
    assert gap["reference"].startswith(session.artifact.id + ":question:")
    assert gap["evidence"]["reference"].startswith(session.artifact.id + ":source:")
    assert "assumptions" in result["interpretation"]


def test_warnings_and_builtin_limits_are_present_in_every_query(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    report = replace(report, meta=replace(report.meta, warnings=["unresolved reflection"]))
    session = _session(tmp_path, report)
    for result in (session.overview(), session.entries(), session.chains(), session.methods()):
        assert any("reflection" in limitation for limitation in result["limitations"])
        assert any("depth 4" in limitation for limitation in result["limitations"])
    assert session.check(_claim())["data"]["verdict"]["status"] == "UNDECIDABLE"


def test_warning_output_is_bounded_without_hiding_total(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    report = replace(report, meta=replace(report.meta, warnings=[f"warning-{index}" for index in range(40)]))
    result = _session(tmp_path, report).overview()
    assert result["warning_count"] == 40
    assert sum(item.startswith("Analysis warning:") for item in result["limitations"]) == 20
    assert any("20 further" in item for item in result["limitations"])


def test_questions_explicitly_bound_large_gap_sets(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    report = replace(report, chains=[
        replace(report.chains[0], id=f"chain-{index:03d}", evidence_complete=False)
        for index in range(105)
    ])
    result = _session(tmp_path, report).questions()["data"]
    assert len(result["questions"]) == 100
    assert result["detail_limits"]["total"] == 105
    assert result["detail_limits"]["truncated"] is True


def test_code_page_character_budget_reports_error_instead_of_silent_truncation(tmp_path: Path) -> None:
    decoded = tmp_path / "decoded"
    shutil.copytree(POSITIVE, decoded)
    source = decoded / "smali/com/example/app/MainActivity.smali"
    source.write_text(
        source.read_text(encoding="utf-8").replace(".locals 3", ".locals 3\n    # " + "x" * 25000),
        encoding="utf-8",
    )
    session = _session(tmp_path, case=decoded)
    with pytest.raises(QueryError) as exc:
        session.method(MAIN_REF)
    assert exc.value.code == "OUTPUT_LIMIT"


def test_invalid_text_and_reference_kind_are_structured_errors(session: EvidenceSession) -> None:
    for value in ("", "x" * 1001):
        with pytest.raises(QueryError) as exc:
            session.chain(value)
        assert exc.value.code == "INVALID_QUERY"
    with pytest.raises(QueryError) as exc:
        session.chain(f"{session.artifact.id}:component:abcd")
    assert exc.value.code == "INVALID_REFERENCE"


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, 101), (True, 1), (0, True)])
def test_page_validation_is_shared_across_operations(
    session: EvidenceSession, offset: int, limit: int
) -> None:
    for operation in (session.entries, session.chains, session.methods):
        with pytest.raises(QueryError) as exc:
            operation(offset=offset, limit=limit)
        assert exc.value.code == "INVALID_PAGE"
    with pytest.raises(QueryError, match="offset|limit"):
        session.method(MAIN_REF, offset=offset, limit=limit)


@pytest.mark.parametrize("kind", ["chain", "component", "method"])
def test_cross_artifact_references_are_rejected(session: EvidenceSession, kind: str) -> None:
    foreign = f"{'f' * 64}:{kind}:something"
    with pytest.raises(QueryError) as exc:
        if kind == "chain":
            session.chain(foreign)
        elif kind == "component":
            session.chains(entry=foreign)
        else:
            session.method(foreign)
    assert exc.value.code == "ARTIFACT_MISMATCH"


def test_invalid_claim_and_wrong_artifact_are_distinct(session: EvidenceSession) -> None:
    with pytest.raises(QueryError) as exc:
        session.check({"kind": "made_up"})
    assert exc.value.code == "INVALID_CLAIM"
    with pytest.raises(QueryError) as exc:
        session.check({**_claim(), "artifact_id": "other"})
    assert exc.value.code == "ARTIFACT_MISMATCH"


@pytest.mark.parametrize("operation,arg,code", [
    ("chain", "missing", "CHAIN_NOT_FOUND"),
    ("chains", "missing", "ENTRY_NOT_FOUND"),
    ("method", "Lmissing;->nope()V", "METHOD_NOT_FOUND"),
])
def test_not_found_differs_from_an_empty_page(
    session: EvidenceSession, operation: str, arg: str, code: str
) -> None:
    with pytest.raises(QueryError) as exc:
        if operation == "chains":
            session.chains(entry=arg)
        else:
            getattr(session, operation)(arg)
    assert exc.value.code == code


def test_integrity_error_is_preserved_when_reading_method(session: EvidenceSession) -> None:
    first = session.method(MAIN_REF)["data"]
    source = session.artifact.path / "source" / first["file"]
    source.write_text(".class public Ltampered;", encoding="utf-8")
    with pytest.raises(QueryError) as exc:
        session.method(MAIN_REF)
    assert exc.value.code == "INTEGRITY_ERROR"


def test_empty_report_has_no_invented_candidates(tmp_path: Path) -> None:
    report = Report(meta=Meta(package="com.example.app"))
    session = _session(tmp_path, report)
    assert session.chains()["data"] == []
    assert session.entries()["data"] == []
    assert session.questions()["data"]["questions"] == []


def test_incomplete_code_locations_are_not_invented(tmp_path: Path) -> None:
    report = analyze_workdir(POSITIVE)
    chain = replace(
        report.chains[0],
        steps=[Step(order=0, sink="webview")],
        judgments=[Judgment(name="J6", result=JudgmentResult.UNKNOWN, confidence=Level.LOW)],
        evidence_complete=False,
    )
    session = _session(tmp_path, replace(report, chains=[chain]))
    detail = session.chain(chain.id)["data"]
    assert detail["steps"][0]["source"] is None
    assert session.check(_claim())["data"]["verdict"]["status"] == "UNDECIDABLE"
