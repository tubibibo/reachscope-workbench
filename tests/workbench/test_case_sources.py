"""Case provenance and retest outcomes never turn missing data into remediation."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.case_service import CaseService
from reachscope_workbench.core.case_sources import candidates, compare_retest, source
from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.modules.android import AndroidModule
from reachscope_workbench.modules.android import module as android


def cloud_job(status: str = "review", *, check_id: str = "network.public_sensitive_ports", identifier: str = "original") -> dict[str, Any]:
    group = check_id.partition(".")[0]
    resource = "aws_security_group.main" if group == "network" else "aws_iam_policy.main"
    evidence = {"id": "cloud-evidence-" + identifier, "kind": "cloud_static_configuration", "title": resource,
                "source": "plan.json#/planned_values/root_module/resources/0/values", "data": {"resource": resource}, "sha256": "a" * 64}
    check = {"id": check_id, "resource_id": resource, "title": "Review a configuration", "status": status,
             "severity": "medium", "description": "Observed a limited rule condition", "recommendation": "Review context",
             "evidence_ids": [evidence["id"]], "evidence": {"values": {"affected": [0] if status == "review" else []}}}
    return {"id": identifier, "asset_id": "cloud-asset", "module": "cloud", "status": "completed", "config": {"mode": "import", "checks": [group]},
            "result": {"module": "cloud", "evidence": [evidence], "observations": [], "details": {
                "resources": [{"id": resource, "type": "aws_security_group" if group == "network" else "aws_iam_policy", "supported": True}],
                "checks": [check], "execution": [{"id": group, "status": "completed"}]}}}


def web_job(status: str = "review", *, check_id: str = "csp", identifier: str = "original") -> dict[str, Any]:
    evidence = {"id": "http-evidence-" + identifier, "kind": "http_observation", "title": "A page",
                "source": "https://example.test/path?q=1", "data": {}, "sha256": "b" * 64}
    check = {"id": check_id, "title": "Review response", "status": status, "severity": "low", "description": "Response condition",
             "recommendation": "Review saved response", "evidence_ids": [evidence["id"]], "evidence": {}}
    asset = {"id": "web-row", "url": evidence["source"], "final_url": evidence["source"], "reachable": True,
             "evidence_ids": [evidence["id"]], "checks": [check], "headers_truncated": [], "cookies_truncated": False,
             "body_truncated": False, "page": {"analyzed": True, "truncated": False}}
    return {"id": identifier, "asset_id": "website-asset", "module": "web", "status": "completed", "config": {"mode": "probe"},
            "result": {"module": "web", "evidence": [evidence], "observations": [], "details": {"assets": [asset],
                "execution": [{"id": group, "status": "completed"} for group in ("http", "headers", "page")]}}}


def compare(before: dict[str, Any], after: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    selected = candidates(before)[0]
    return compare_retest(before, selected["source_kind"], selected["source_ref"], after, **kwargs)


def test_cloud_candidates_keep_stable_identity_and_static_confidence() -> None:
    before, after = cloud_job(), cloud_job(identifier="later")
    selected = candidates(before)[0]
    assert selected["source_kind"] == "check" and selected["confidence"] == "static_config"
    assert selected["status"] == "review" and selected["asset_id"] == "cloud-asset"
    assert selected["source_ref"] == candidates(after)[0]["source_ref"]
    assert selected["evidence_ids"] != candidates(after)[0]["evidence_ids"]
    assert source(before, "check", selected["source_ref"]) == selected
    assert selected["locator"] == {"type": "cloud_check", "resource_id": "aws_security_group.main", "check_id": "network.public_sensitive_ports"}
    selected["locator"]["resource_id"] = "mutated"
    assert candidates(before)[0]["locator"]["resource_id"] == "aws_security_group.main"


def test_identity_does_not_split_ambiguous_delimited_resource_names() -> None:
    first, second = cloud_job(), cloud_job()
    first["result"]["details"]["checks"][0].update(resource_id="a|b", id="c")
    second["result"]["details"]["checks"][0].update(resource_id="a", id="b|c")
    assert candidates(first)[0]["source_ref"] != candidates(second)[0]["source_ref"]


@pytest.mark.parametrize("status,expected", [("review", 1), ("unknown", 1), ("pass", 0), ("info", 0), ("not_applicable", 0)])
def test_only_actionable_cloud_states_create_sources(status: str, expected: int) -> None:
    assert len(candidates(cloud_job(status))) == expected


def test_web_checks_are_preferred_over_duplicate_observations_and_noise() -> None:
    job = web_job()
    eid = job["result"]["evidence"][0]["id"]
    job["result"]["observations"] = [
        {"id": "derived", "category": "security_headers", "title": "Duplicate", "severity": "low", "confidence": "observed", "evidence_ids": [eid]},
        {"id": "fingerprint", "category": "fingerprint", "title": "A technology", "severity": "info", "evidence_ids": [eid]},
        {"id": "clear", "category": "cleartext_http", "title": "Plain HTTP", "severity": "low", "confidence": "observed", "evidence_ids": [eid]},
        {"id": "detached", "category": "risk", "title": "No saved proof", "severity": "high", "evidence_ids": ["missing"]},
    ]
    result = candidates(job)
    assert [row["title"] for row in result] == ["Review response", "Plain HTTP"]
    assert result[0]["confidence"] == "observed_config"
    assert result[1]["locator"]["url"] == "https://example.test/path?q=1"


def test_imported_reports_and_static_inference_are_never_promoted() -> None:
    job = web_job("pass")
    eid = job["result"]["evidence"][0]["id"]
    job["result"]["observations"] = [{"id": "external", "category": "imported_finding", "title": "External scanner claim",
                                     "severity": "high", "confidence": "confirmed", "evidence_ids": [eid]}]
    assert candidates(job)[0]["confidence"] == "imported_unverified"
    other = copy.deepcopy(job)
    other["id"] = "new"
    assert compare(job, other)["outcome"] == "not_comparable"
    job.update(module="android")
    job["result"]["module"] = "android"
    job["result"]["observations"][0].update(category="webview_path", confidence="static_inference")
    assert candidates(job)[0]["confidence"] == "static_inference"
    assert compare(job, {**job, "id": "later"})["outcome"] == "not_comparable"


@pytest.mark.parametrize("update,code", [({"status": "running"}, "RESULT_UNAVAILABLE"),
                                      ({"asset_id": None}, "ASSET_REQUIRED"), ({"module": "not-supported"}, "INVALID_RESULT"),
                                      ({"id": ""}, "INVALID_RESULT")])
def test_invalid_job_sources_have_domain_errors(update: dict[str, Any], code: str) -> None:
    job = {**cloud_job(), **update}
    with pytest.raises(WorkbenchError) as error:
        candidates(job)
    assert error.value.code == code


def test_detached_duplicate_or_fabricated_sources_are_rejected() -> None:
    job = cloud_job()
    with pytest.raises(WorkbenchError) as error:
        source(job, "check", "src-fabricated")
    assert error.value.code == "CASE_SOURCE_NOT_FOUND"
    with pytest.raises(WorkbenchError) as error:
        source(job, "code", "x")
    assert error.value.code == "INVALID_CASE_SOURCE"
    job["result"]["details"]["checks"].append(copy.deepcopy(job["result"]["details"]["checks"][0]))
    with pytest.raises(WorkbenchError) as error:
        candidates(job)
    assert error.value.code == "CASE_SOURCE_AMBIGUOUS"
    job = cloud_job()
    job["result"]["evidence"].clear()
    assert candidates(job) == []


@pytest.mark.parametrize("status,outcome", [("review", "still_observed"), ("pass", "not_observed_in_scope"),
                                          ("unknown", "not_comparable"), ("info", "not_comparable"), ("not_applicable", "not_comparable")])
def test_cloud_retest_uses_the_same_resource_rule_and_explicit_state(status: str, outcome: str) -> None:
    before, after = cloud_job(), cloud_job(status, identifier="new")
    original = copy.deepcopy((before, after))
    result = compare(before, after)
    assert result["outcome"] == outcome and result["source_job_id"] == "original" and result["retest_job_id"] == "new"
    assert result["matching"] and result["evidence"][0]["id"] == "cloud-evidence-new"
    assert (before, after) == original


@pytest.mark.parametrize("rule", ["iam.broad_allow", "iam.trust_principal", "storage.bucket_policy_principal"])
def test_limited_policy_no_hit_info_is_comparable_without_effective_access_claim(rule: str) -> None:
    result = compare(cloud_job(check_id=rule), cloud_job("info", check_id=rule, identifier="new"))
    assert result["outcome"] == "not_observed_in_scope"
    assert any("不证明" in limitation for limitation in result["limitations"])


def test_original_unknown_does_not_turn_into_a_repair_when_later_known() -> None:
    result = compare(cloud_job("unknown"), cloud_job("pass", identifier="new"))
    assert result["outcome"] == "not_comparable" and "来源记录是信息不足" in result["reason"]


@pytest.mark.parametrize("change", ["missing-resource", "unsupported", "type-change", "missing-check", "skipped-group", "no-proof", "remaining-unknown"])
def test_cloud_collection_and_identity_gaps_are_not_remediation(change: str) -> None:
    before, after = cloud_job(), cloud_job("pass", identifier="new")
    details = after["result"]["details"]
    if change == "missing-resource":
        details["resources"] = []
    elif change == "unsupported":
        details["resources"][0]["supported"] = False
    elif change == "type-change":
        details["resources"][0]["type"] = "aws_s3_bucket"
    elif change == "missing-check":
        details["checks"] = []
    elif change == "skipped-group":
        details["execution"][0]["status"] = "skipped"
    elif change == "no-proof":
        after["result"]["evidence"] = []
    else:
        details["checks"][0]["evidence"]["values"]["unknown_rule_indexes"] = [1]
    assert compare(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("update", [{"id": "original"}, {"status": "failed"}, {"asset_id": "different"}, {"module": "web"}])
def test_self_incomplete_cross_asset_and_cross_module_retests_are_rejected(update: dict[str, Any]) -> None:
    assert compare(cloud_job(), {**cloud_job("pass", identifier="new"), **update})["outcome"] == "not_comparable"


def test_explicit_revision_link_is_required_and_keeps_actual_identity() -> None:
    before, after = cloud_job(), cloud_job("pass", identifier="new")
    after["asset_id"] = "revised-file"
    assert compare(before, after)["outcome"] == "not_comparable"
    assert compare(before, after, related_asset_ids={"another-file"})["outcome"] == "not_comparable"
    result = compare(before, after, related_asset_ids={"revised-file"})
    assert result["outcome"] == "not_observed_in_scope" and result["input_revision"] is True
    assert result["retest_job_id"] == "new" and after["asset_id"] == "revised-file"
    assert "显式关联" in result["reason"] and any("实际资源身份" in item for item in result["limitations"])
    after["result"]["details"]["resources"][0]["type"] = "different"
    assert compare(before, after, related_asset_ids={"revised-file"})["outcome"] == "not_comparable"


@pytest.mark.parametrize("status,outcome", [("review", "still_observed"), ("pass", "not_observed_in_scope"),
                                          ("info", "not_comparable"), ("unknown", "not_comparable"), ("not_applicable", "not_comparable")])
def test_web_same_url_rule_compares_only_explicit_pass_or_review(status: str, outcome: str) -> None:
    assert compare(web_job(), web_job(status, identifier="new"))["outcome"] == outcome


@pytest.mark.parametrize("gap", ["request-failed", "different-url", "rule-missing", "old-fields", "header-truncated", "skipped", "no-proof"])
def test_web_incomplete_response_is_not_a_fix(gap: str) -> None:
    before, after = web_job(), web_job("pass", identifier="new")
    row = after["result"]["details"]["assets"][0]
    if gap == "request-failed":
        row["reachable"] = False
    elif gap == "different-url":
        row["url"] += "&other=1"
    elif gap == "rule-missing":
        row["checks"][0]["id"] = "new-rule"
    elif gap == "old-fields":
        row.pop("checks")
    elif gap == "header-truncated":
        row["headers_truncated"] = ["content-security-policy"]
    elif gap == "skipped":
        after["result"]["details"]["execution"][1]["status"] = "skipped"
    else:
        after["result"]["evidence"] = []
    assert compare(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("check_id,gap", [("cookie_secure", "cookies"), ("password_forms", "page"), ("mixed_content", "body")])
def test_cookie_or_page_capture_gaps_cannot_resolve_a_case(check_id: str, gap: str) -> None:
    before, after = web_job(check_id=check_id), web_job("pass", check_id=check_id, identifier="new")
    row = after["result"]["details"]["assets"][0]
    if gap == "cookies":
        row["cookies_truncated"] = True
    elif gap == "page":
        row["page"]["truncated"] = True
    else:
        row["body_truncated"] = True
    assert compare(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("check_id,gap", [("csp", "headers"), ("cookie_secure", "cookies"), ("password_forms", "page"), ("mixed_content", "body"), ("csp", "failed")])
def test_incomplete_original_capture_is_not_a_certain_remediation_baseline(check_id: str, gap: str) -> None:
    before, after = web_job(check_id=check_id), web_job("pass", check_id=check_id, identifier="new")
    row = before["result"]["details"]["assets"][0]
    if gap == "headers":
        row["headers_truncated"] = ["content-security-policy"]
    elif gap == "cookies":
        row["cookies_truncated"] = True
    elif gap == "page":
        row["page"]["truncated"] = True
    elif gap == "body":
        row["body_truncated"] = True
    else:
        row["reachable"] = False
    assert compare(before, after)["outcome"] == "not_comparable"


def cleartext_job(identifier: str, final: str) -> dict[str, Any]:
    job = web_job("pass", identifier=identifier)
    row = job["result"]["details"]["assets"][0]
    row.update(url="http://example.test/", final_url=final)
    job["result"]["evidence"][0]["source"] = row["url"]
    job["result"]["observations"] = [{"id": "http-" + identifier, "category": "cleartext_http", "title": "HTTP response", "severity": "low",
                                      "confidence": "observed", "evidence_ids": row["evidence_ids"]}]
    return job


def test_plain_http_observation_retests_by_saved_input_not_observation_id() -> None:
    before = cleartext_job("original", "http://example.test/")
    after = cleartext_job("later", "https://example.test/")
    result = compare(before, after)
    assert result["outcome"] == "not_observed_in_scope" and result["evidence"]
    after["result"]["details"]["assets"][0]["final_url"] = "http://example.test/"
    assert compare(before, after)["outcome"] == "still_observed"
    after["result"]["details"]["assets"][0]["redirect_stopped"] = "out_of_scope"
    assert compare(before, after)["outcome"] == "not_comparable"


def test_network_targets_cannot_borrow_revision_file_authorization() -> None:
    before, after = web_job(), web_job("pass", identifier="new")
    after["asset_id"] = "another-target"
    result = compare(before, after, related_asset_ids={"another-target"})
    assert result["outcome"] == "not_comparable" and result["input_revision"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [["manifest"], ["manifest", "code_paths"]], ids=["manifest-only", "full"])
async def test_real_android_entry_fact_supports_manual_case_without_promoting_confidence(
    tmp_path: Path, selected: list[str],
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    config = {"mode": "demo", "sample": "cross_component", "checks": selected}
    context = RunContext("source-job", tmp_path / "analysis", uploads, lambda *_: None)
    result = (await AndroidModule().run(config, context)).to_dict()
    assert result["summary"]["exported"] == 1
    original = copy.deepcopy(result)
    jobs = JobRepository(tmp_path / "workbench.sqlite3")
    asset = AssetRepository(jobs).create("android", "Synthetic Android entry review", {
        "profile_id": "android-demo", "mode": "demo", "sample": "cross_component"})
    job = jobs.create("android", "Actual module output", config, asset=asset)
    assert jobs.transition(job["id"], {"queued"}, "completed", "fixture completed", result=result)
    persisted = jobs.get(job["id"])
    selected_source = next(row for row in candidates(persisted) if row["category"] == "android_attack_surface")
    assert selected_source["severity"] == "info" and selected_source["confidence"] == "observed"
    assert selected_source["source_kind"] == "observation" and selected_source["evidence_ids"] == ["manifest"]
    assert source(persisted, "observation", selected_source["source_ref"]) == selected_source
    service = CaseService(jobs)
    engagement = service.collaboration.create_engagement("Manual entry review", "Review configuration only", "Synthetic fixture", [asset["id"]])
    case = service.create_case(engagement["id"], job["id"], "observation", selected_source["source_ref"])
    assert case["severity"] == "info" and case["confidence"] == "observed" and case["status"] == "open"
    assert case["evidence"][0]["id"] == "manifest" and case["evidence"][0]["sha256"]
    retest = jobs.create("android", "Later saved entry review", config, asset=asset)
    assert jobs.transition(retest["id"], {"queued"}, "completed", "fixture completed", result=result)
    assert service.assessment(case["id"], retest["id"])["outcome"] == "not_comparable"
    with pytest.raises(WorkbenchError) as caught:
        service.update(case["id"], case["version"], {"status": "resolved", "note": "Static entry observation alone does not establish remediation"},
                       retest_job_id=retest["id"])
    assert caught.value.code == "RETEST_NOT_CLEARED"
    assert service.detail(case["id"])["status"] == "open" and jobs.get(job["id"])["result"] == original


@pytest.mark.parametrize("module,category,exported", [
    ("android", "android_attack_surface", 0), ("android", "android_attack_surface", None),
    ("android", "android_attack_surface", True), ("android", "android_attack_surface", "1"),
    ("android", "analysis_gap", 1), ("android", "fingerprint", 1),
    ("web", "android_attack_surface", 1), ("cloud", "android_attack_surface", 1),
])
def test_android_info_exception_does_not_expand_to_noise_or_unobserved_entries(
    module: str, category: str, exported: Any,
) -> None:
    job = {"id": "source", "asset_id": "asset", "module": module, "status": "completed", "result": {
        "module": module, "summary": {"exported": exported}, "details": {},
        "evidence": [{"id": "manifest", "source": "AndroidManifest.xml", "data": {}}],
        "observations": [{"id": "entry", "category": category, "severity": "info", "confidence": "observed",
                          "title": "Configuration context", "evidence_ids": ["manifest"]}]}}
    assert candidates(job) == []


@pytest.mark.asyncio
async def test_real_zero_exported_manifest_retains_context_without_inventing_a_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sample-root"
    sample = root / "samples" / "cross_component"
    sample.mkdir(parents=True)
    (sample / "AndroidManifest.xml").write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="example.fixture">
      <application><activity android:name=".PrivateEntry" android:exported="false"/></application>
      </manifest>''', encoding="utf-8")
    monkeypatch.setattr(android, "files", lambda _: root)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    result = (await AndroidModule().run({"mode": "demo", "sample": "cross_component", "checks": ["manifest"]},
                                      RunContext("zero-exported", tmp_path / "analysis", uploads, lambda *_: None))).to_dict()
    job = {"id": "zero-exported", "asset_id": "asset", "module": "android", "status": "completed", "result": result}
    assert result["summary"]["exported"] == 0 and result["evidence"][0]["sha256"]
    assert result["observations"][0]["title"] == "观察到 0 个导出组件"
    assert result["observations"][0]["severity"] == "info" and result["observations"][0]["confidence"] == "observed"
    # Independent configuration gaps may now create review tasks. Zero exported
    # entries must still never manufacture an attack-surface case.
    assert all(row["category"] != "android_attack_surface" for row in candidates(job))
