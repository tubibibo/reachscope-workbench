"""Android revision cases require actual, complete and comparable declarations."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from reachscope_workbench.core.case_sources import candidates, compare_retest
from reachscope_workbench.core.models import WorkbenchError


def job(status: str = "review", identifier: str = "baseline") -> dict[str, Any]:
    evidence_id = "review-" + identifier
    check = {"id": "android.debuggable", "resource_id": "org.example.app", "status": status,
             "complete": True, "title": "Release debug flag", "description": "Saved declaration only",
             "evidence_ids": [evidence_id]}
    return {"id": identifier, "asset_id": "apk-asset", "module": "android", "status": "completed",
            "result": {"module": "android", "observations": [],
                       "evidence": [{"id": evidence_id, "kind": "android_static_configuration", "data": {}}],
                       "details": {"security_review": {"version": 1, "package": "org.example.app", "checks": [check]},
                                   "execution": [{"id": "manifest", "status": "completed"}]}}}


def compare(before: dict[str, Any], after: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    selected = candidates(before)[0]
    return compare_retest(before, selected["source_kind"], selected["source_ref"], after, **kwargs)


@pytest.mark.parametrize(("status", "count"), [("review", 1), ("unknown", 1), ("pass", 0), ("not_applicable", 0)])
def test_android_sources_keep_state_and_static_confidence(status: str, count: int) -> None:
    rows = candidates(job(status))
    assert len(rows) == count
    if rows:
        assert rows[0]["confidence"] == "static_config"
        assert rows[0]["status"] == status
        assert rows[0]["locator"]["package"] == "org.example.app"


@pytest.mark.parametrize(("status", "outcome"), [("review", "still_observed"), ("pass", "not_observed_in_scope"),
                                                ("unknown", "not_comparable"), ("not_applicable", "not_comparable")])
def test_only_complete_known_pass_can_support_resolution(status: str, outcome: str) -> None:
    assert compare(job(), job(status, "retest"))["outcome"] == outcome


@pytest.mark.parametrize("gap", ["package", "version", "bool-version", "missing-review", "missing-rule", "duplicate-rule",
                                 "resource", "skipped", "missing-evidence", "incomplete", "baseline-incomplete", "baseline-unknown"])
def test_gaps_do_not_become_android_fixes(gap: str) -> None:
    before, after = job(), job("pass", "retest")
    review = after["result"]["details"]["security_review"]
    if gap == "package":
        review["package"] = "org.other.app"
    elif gap == "version":
        review["version"] = 2
    elif gap == "bool-version":
        review["version"] = True
    elif gap == "missing-review":
        after["result"]["details"].pop("security_review")
    elif gap == "missing-rule":
        review["checks"] = []
    elif gap == "duplicate-rule":
        review["checks"].append(copy.deepcopy(review["checks"][0]))
    elif gap == "resource":
        review["checks"][0]["resource_id"] = "org.other.app"
    elif gap == "skipped":
        after["result"]["details"]["execution"][0]["status"] = "skipped"
    elif gap == "missing-evidence":
        after["result"]["evidence"] = []
    elif gap == "incomplete":
        review["checks"][0]["complete"] = False
    elif gap == "baseline-incomplete":
        before["result"]["details"]["security_review"]["checks"][0]["complete"] = False
    else:
        before["result"]["details"]["security_review"]["checks"][0]["status"] = "unknown"
    assert compare(before, after)["outcome"] == "not_comparable"


def test_explicit_revision_relation_and_package_identity_are_both_required() -> None:
    before, after = job(), job("pass", "retest")
    after["asset_id"] = "corrected-apk"
    assert compare(before, after)["outcome"] == "not_comparable"
    assessment = compare(before, after, related_asset_ids={"corrected-apk"})
    assert assessment["outcome"] == "not_observed_in_scope" and assessment["input_revision"] is True
    assert after["asset_id"] == "corrected-apk"
    after["result"]["details"]["security_review"]["package"] = "org.other.app"
    assert compare(before, after, related_asset_ids={"corrected-apk"})["outcome"] == "not_comparable"


def test_derived_observation_is_not_a_second_configuration_case() -> None:
    before = job()
    before["result"]["observations"] = [{"id": "android-config:android.debuggable", "category": "android.debuggable",
                                           "severity": "medium", "evidence_ids": ["review-baseline"]}]
    assert len(candidates(before)) == 1


def test_duplicate_rule_identity_is_rejected_for_case_creation() -> None:
    before = job()
    before["result"]["details"]["security_review"]["checks"] *= 2
    with pytest.raises(WorkbenchError, match="重复"):
        candidates(before)
