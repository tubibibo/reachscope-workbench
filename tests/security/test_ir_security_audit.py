"""Duplicate local IDs are rejected, without searching for hash collisions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reachscope.analyze.evidence import build_evidence
from reachscope.analyze.pipeline import analyze_workdir
from reachscope.artifacts import ArtifactStore
from reachscope.ingest.apk import IngestError
from reachscope.ingest.manifest import ManifestInfo
from reachscope.ingest.smali import SmaliIndex
from reachscope.ir.model import Chain, Component, ComponentType, Report
from reachscope.ir.validation import IRValidationError
from reachscope.query import EvidenceSession
from reachscope.report.html_report import render_html
from reachscope.report.json_report import normalize_report, render_json


def ambiguous_report(namespace: str) -> Report:
    # Mutate a caller-owned list after construction, to exercise output and
    # query boundaries in addition to the dataclass constructor itself.
    report = Report(components=[Component(name="example.First", type=ComponentType.ACTIVITY, exported=True)],
                    chains=[Chain(id="legacy01", entries=["first"])])
    if namespace == "component":
        report.components.append(Component(name="example.First", exported=True))
    else:
        report.chains.append(Chain(id="legacy01", entries=["second"]))
    return report


@pytest.mark.parametrize("namespace", ["component", "chain"])
def test_sec_ir_01_duplicate_ids_are_rejected_at_report_boundaries(namespace: str) -> None:
    raw = Report(components=[Component(name="example.First")], chains=[Chain(id="legacy01")]).to_dict()
    field = "components" if namespace == "component" else "chains"
    raw[field].append(dict(raw[field][0]))
    with pytest.raises(IRValidationError, match="duplicate local identifiers"):
        Report.from_dict(raw)
    report = ambiguous_report(namespace)
    for operation in (report.to_dict, lambda: normalize_report(report), lambda: render_json(report), lambda: render_html(report)):
        with pytest.raises(IRValidationError, match="duplicate local identifiers") as failure:
            operation()
        assert "example.First" not in str(failure.value) and "legacy01" not in str(failure.value)


@pytest.mark.parametrize("namespace", ["component", "chain"])
def test_sec_ir_01_analysis_fails_before_first_or_last_wins_enrichment(namespace: str, monkeypatch: pytest.MonkeyPatch) -> None:
    report = ambiguous_report(namespace)

    def must_not_judge(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Ambiguous objects reached evidence judgment")

    monkeypatch.setattr("reachscope.analyze.evidence.j1", must_not_judge)
    with pytest.raises(IRValidationError, match="duplicate local identifiers"):
        build_evidence(report.components, ManifestInfo(), SmaliIndex(), [], [], report.chains)


@pytest.mark.parametrize("namespace", ["component", "chain"])
def test_sec_ir_01_query_and_publication_refuse_ambiguous_references(tmp_path: Path, namespace: str) -> None:
    report = ambiguous_report(namespace)
    # A Python caller can construct an artifact object directly; the query port
    # must reject it before returning first-wins references or risk judgments.
    with pytest.raises(IRValidationError, match="duplicate local identifiers"):
        EvidenceSession(SimpleNamespace(report=report))
    decoded = tmp_path / "decoded"
    decoded.mkdir()
    (decoded / "AndroidManifest.xml").write_text("<manifest><application/></manifest>", encoding="utf-8")
    destination = tmp_path / "artifacts"
    with pytest.raises(IRValidationError, match="duplicate local identifiers"):
        ArtifactStore(destination).create(decoded, report)
    assert not any(destination.iterdir()), "Ambiguous reports must not publish an artifact or leave a staging directory"


def test_sec_ir_01_existing_normal_report_ids_are_not_rewritten() -> None:
    report = Report(components=[Component(name="com.example.Legacy")], chains=[Chain(id="01234567")])
    component_id = report.components[0].id
    encoded = render_json(report)
    loaded = Report.from_dict(json.loads(encoded))
    assert loaded.components[0].id == component_id and len(component_id) == 8
    assert loaded.chains[0].id == "01234567" and render_json(loaded) == encoded


def test_sec_ir_01_computed_ambiguity_is_a_safe_analysis_input_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate the result of colliding local labels; this does not search for a
    # SHA collision or alter how legacy stable_id values are constructed.
    monkeypatch.setattr("reachscope.analyze.pipeline.build_chains", lambda *args: [
        Chain(id="same-local-label", entries=["first"]), Chain(id="same-local-label", entries=["second"]),
    ])
    decoded = Path(__file__).resolve().parents[1] / "fixtures/cases/01_positive_deeplink_bridge_sink"
    with pytest.raises(IngestError, match="ambiguous local identifiers") as failure:
        analyze_workdir(decoded)
    assert "same-local-label" not in str(failure.value)
