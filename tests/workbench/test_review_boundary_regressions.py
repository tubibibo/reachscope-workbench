"""Independent conservative boundaries across static review and local HTTP guides."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from reachscope_workbench.core.advisory_context import ContextRegistry, HttpGuideEvidenceAdapter
from reachscope_workbench.core.case_sources import candidates, compare_retest
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.cloud.preview import preview_input


def http_job(*, cloud: bool = False) -> dict[str, Any]:
    return {"id": "http-job", "module": "web", "status": "completed", "asset_id": "saved-asset",
        "config": {"mode": "probe"}, "asset_snapshot": {"kind": "cloud" if cloud else "website", "source": {
            "profile_id": "cloud-external" if cloud else "website-probe"}}, "result": {
            "module": "web", "evidence": [{"id": "http-proof"}], "details": {
                "assets": [{"url": "https://service.example/reset?token=private-token", "reachable": True,
                    "status_code": 200, "evidence_ids": ["http-proof"], "checks": [{"id": "nosniff", "status": "review"}]}],
                "execution": [{"id": "http", "status": "completed"}, {"id": "headers", "status": "completed"}]}}}


def test_cloud_http_guide_does_not_expand_paid_ai_eligibility_or_mutate_saved_records() -> None:
    job = http_job(cloud=True)
    before = copy.deepcopy(job)
    guide = HttpGuideEvidenceAdapter().build(job)
    assert guide["origin"] == "cloud_service_probe"
    assert guide["targets"][0]["url"] == "https://service.example/"
    assert "private-token" not in json.dumps(guide)
    with pytest.raises(WorkbenchError) as caught:
        ContextRegistry().build(job)
    assert caught.value.code == "AI_INPUT_UNSUPPORTED"
    assert job == before


@pytest.mark.parametrize("kind,profile,mode", [
    ("cloud", "cloud-config", "import"), ("cloud", "cloud-demo", "demo"),
    ("android", "android-apk", "apk"), ("website", "website-demo", "demo"),
    ("website", "website-import", "import"),
])
def test_http_guides_exclude_offline_or_other_module_inputs(kind: str, profile: str, mode: str) -> None:
    job = http_job()
    job["asset_snapshot"].update(kind=kind, source={"profile_id": profile})
    job["config"]["mode"] = mode
    with pytest.raises(WorkbenchError):
        HttpGuideEvidenceAdapter().build(job)


@pytest.mark.parametrize("field,value", [
    ("asset_snapshot", []), ("asset_snapshot", "bad"), ("config", []), ("result", []),
])
def test_http_adapter_malformed_envelopes_fail_as_domain_errors(field: str, value: Any) -> None:
    job = http_job()
    job[field] = value
    with pytest.raises(WorkbenchError):
        HttpGuideEvidenceAdapter().build(job)


@pytest.mark.parametrize("field,value", [("details", None), ("details", []), ("evidence", None)])
def test_http_adapter_malformed_saved_result_does_not_raise_unhandled_type_errors(field: str, value: Any) -> None:
    job = http_job()
    job["result"][field] = value
    with pytest.raises(WorkbenchError):
        HttpGuideEvidenceAdapter().build(job)


@pytest.mark.parametrize("field,value", [("source", []), ("source", "bad"), ("provenance", []), ("provenance", "bad")])
def test_http_snapshot_optional_metadata_is_conservatively_filtered(field: str, value: Any) -> None:
    job = http_job()
    job["asset_snapshot"][field] = value
    try:
        guide = HttpGuideEvidenceAdapter().build(job)
    except WorkbenchError:
        return
    assert guide["targets"][0]["url"] == "https://service.example/"


@pytest.mark.parametrize("field,value", [("assets", {}), ("assets", None)])
def test_http_adapter_invalid_asset_container_cannot_supply_evidence(field: str, value: Any) -> None:
    job = http_job()
    job["result"]["details"][field] = value
    with pytest.raises(WorkbenchError):
        HttpGuideEvidenceAdapter().build(job)


@pytest.mark.parametrize("field,value", [("evidence_ids", None), ("evidence_ids", {}), ("url", {})])
def test_http_adapter_invalid_asset_evidence_or_url_cannot_be_a_usable_response(field: str, value: Any) -> None:
    job = http_job()
    job["result"]["details"]["assets"][0][field] = value
    with pytest.raises(WorkbenchError):
        HttpGuideEvidenceAdapter().build(job)


@pytest.mark.parametrize("field,value", [("id", {}), ("id", []), ("status", {}), ("status", [])])
def test_http_adapter_rejects_unhashable_check_metadata_without_crashing(field: str, value: Any) -> None:
    job = http_job()
    job["result"]["details"]["assets"][0]["checks"].append({"id": "csp", "status": "review", field: value})
    guide = HttpGuideEvidenceAdapter().build(job)
    assert guide["targets"][0]["checks"] == [{"id": "nosniff", "status": "review", "evidence_ids": ["http-proof"]}]


def android_job(identifier: str, *, status: str = "review") -> dict[str, Any]:
    return {"id": identifier, "module": "android", "asset_id": "same-asset", "status": "completed", "result": {
        "module": "android", "summary": {}, "observations": [], "evidence": [{"id": "android-proof", "data": {}}],
        "details": {"execution": [{"id": "manifest", "status": "completed"}], "security_review": {
            "version": 1, "package": "example.same", "checks": [{"id": "android.debuggable", "resource_id": "example.same",
                "title": "Debug declaration", "status": status, "complete": True, "facts_truncated": False,
                "evidence_ids": ["android-proof"]}]}}}}


def assess(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    selected = candidates(before)[0]
    return compare_retest(before, selected["source_kind"], selected["source_ref"], after)


@pytest.mark.parametrize("state", ["unknown", "info", "not_applicable"])
def test_android_unknown_or_missing_retest_is_not_a_fix(state: str) -> None:
    before = android_job("before")
    after = android_job("after", status=state)
    snapshot = copy.deepcopy((before, after))
    assert assess(before, after)["outcome"] == "not_comparable"
    assert (before, after) == snapshot


@pytest.mark.parametrize("field,value", [("checks", []), ("checks", {}), ("package", "other.package"), ("version", True), ("version", 2)])
def test_android_missing_or_cross_package_or_future_review_is_not_a_fix(field: str, value: Any) -> None:
    before, after = android_job("before"), android_job("after", status="pass")
    after["result"]["details"]["security_review"][field] = value
    assert assess(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("which", ["before", "after"])
def test_android_partial_check_cannot_clear_even_with_pass_state(which: str) -> None:
    before, after = android_job("before"), android_job("after", status="pass")
    target = before if which == "before" else after
    target["result"]["details"]["security_review"]["checks"][0]["complete"] = False
    assert assess(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("which", ["before", "after"])
def test_android_explicit_truncation_cannot_be_overruled_by_inconsistent_complete_flag(which: str) -> None:
    before, after = android_job("before"), android_job("after", status="pass")
    target = before if which == "before" else after
    target["result"]["details"]["security_review"]["checks"][0]["facts_truncated"] = True
    assert assess(before, after)["outcome"] == "not_comparable"


def test_android_legacy_record_stays_without_manufactured_configuration_cases() -> None:
    job = android_job("legacy")
    del job["result"]["details"]["security_review"]
    before = copy.deepcopy(job)
    assert candidates(job) == [] and job == before


def test_cloud_preview_redacts_policy_values_and_keeps_actual_root_pointer() -> None:
    document = {"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*", "Condition": {
        "StringEquals": {"aws:SourceAccount": "sensitive-preview-sentinel"}}}]}
    preview = preview_input(json.dumps(document).encode(), ["iam"])
    assert preview["analysis_executed"] is False and preview["network_requests"] is False
    assert "sensitive-preview-sentinel" not in json.dumps(preview)
    assert all(gap["pointer"] == "" for gap in preview["field_gaps"])


def test_cloud_preview_unknown_unsupported_resources_do_not_grow_security_coverage() -> None:
    document = {"planned_values": {"root_module": {"resources": [{"address": "resource-private-sentinel",
        "type": "aws_instance", "name": "name-private-sentinel", "values": {"user_data": "private-script-sentinel"}}]}}}
    preview = preview_input(json.dumps(document).encode(), ["network", "iam", "storage"])
    assert preview["resources_total"] == 1 and preview["unsupported_resources"] == 1
    assert preview["supported_resources"] == 0
    assert all(row["applicable_resources"] == 0 for row in preview["group_coverage"])
    assert "sentinel" not in json.dumps(preview)


def cloud_plan(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"planned_values": {"root_module": {"resources": [{"address": "private-name",
        "type": kind, "name": "private-name", "values": values}]}}}


def test_cloud_missing_policy_pointer_resolves_to_existing_parent_not_invented_field() -> None:
    document = cloud_plan("aws_iam_policy", {})
    preview = preview_input(json.dumps(document).encode(), ["iam"])
    for gap in preview["field_gaps"]:
        current: Any = document
        for part in gap["pointer"].split("/")[1:]:
            current = current[int(part)] if isinstance(current, list) else current[part.replace("~1", "/").replace("~0", "~")]
        assert isinstance(current, dict)
    assert preview["field_gaps"][0]["field"] == "policy"
    assert preview["field_gaps"][0]["state"] == "missing"


@pytest.mark.parametrize("values", [
    {"rule": []}, {"rule": [{}]}, {"rule": [{"apply_server_side_encryption_by_default": []}]},
    {"rule": [{"apply_server_side_encryption_by_default": [{}]}]},
])
def test_cloud_empty_encryption_substructure_is_visible_as_input_gap(values: dict[str, Any]) -> None:
    document = cloud_plan("aws_s3_bucket_server_side_encryption_configuration", values)
    preview = preview_input(json.dumps(document).encode(), ["storage"])
    assert preview["field_gaps_total"] > 0
    assert any(gap["state"] in {"missing", "unknown", "invalid"} for gap in preview["field_gaps"])
