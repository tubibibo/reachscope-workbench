"""Red/blue workflows retain original evidence and require comparable retests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.modules.cloud.module import CloudModule
from reachscope_workbench.modules.cloud.sample import demo_document

HEADERS = {"X-ReachScope-Client": "workbench"}


def saved_cloud(repository: JobRepository, *, revision_of: dict[str, Any] | None = None,
                mitigated: bool = False, missing_resource: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory = AssetRepository(repository)
    asset = inventory.create("cloud", "Cloud revised" if mitigated else "Cloud baseline", {
        "profile_id": "cloud-config", "mode": "import", "upload_id": "a" * 32, "filename": "plan.json"}) if revision_of is None else revision_of
    document = demo_document()
    if mitigated:
        document["planned_values"]["root_module"]["resources"][0]["values"]["ingress"][0]["cidr_blocks"] = ["10.0.0.0/24"]
    if missing_resource:
        document["planned_values"]["root_module"]["resources"].pop(0)
    result = CloudModule._analyze(json.dumps(document).encode(), {"checks": ["network", "iam", "storage"], "mode": "demo"}, "test-only fixture").to_dict()
    job = repository.create("cloud", "API fixture", {"mode": "demo", "checks": ["network", "iam", "storage"]}, asset=asset)
    assert repository.transition(job["id"], {"queued"}, "completed", "fixture completed", result=result)
    return asset, repository.get(job["id"])


def workspace(client: TestClient, asset_id: str) -> str:
    response = client.post("/api/engagements", json={"name": "Review <script>unsafe()</script>", "objective": "Local evidence review",
                                                   "authorization_note": "Synthetic local configuration; no cloud account access", "asset_ids": [asset_id]},
                           headers={**HEADERS, "Idempotency-Key": "workspace-request"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def add_network_case(client: TestClient, engagement_id: str, job_id: str) -> dict[str, Any]:
    response = client.get(f"/api/engagements/{engagement_id}/candidates", params={"job_id": job_id})
    assert response.status_code == 200, response.text
    candidate = next(row for row in response.json()["items"] if row["category"] == "network.public_sensitive_ports")
    response = client.post(f"/api/engagements/{engagement_id}/cases", json={"job_id": job_id, "source_kind": candidate["source_kind"],
                                                                         "source_ref": candidate["source_ref"]},
                           headers={**HEADERS, "Idempotency-Key": "case-request"})
    assert response.status_code == 201, response.text
    return response.json()


def test_scope_candidates_evidence_and_duplicate_requests(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    asset, job = saved_cloud(app.state.repository)
    outside, outside_job = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        engagement = workspace(client, asset["id"])
        assert workspace(client, asset["id"]) == engagement
        assert client.get("/api/engagements").json()["total"] == 1
        rejected = client.get(f"/api/engagements/{engagement}/candidates", params={"job_id": outside_job["id"]})
        assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "OUT_OF_SCOPE"
        case = add_network_case(client, engagement, job["id"])
        assert case["confidence"] == "static_config" and case["source"]["status"] == "review"
        assert case["evidence"] and case["events"][0]["event_type"] == "created"
        assert add_network_case(client, engagement, job["id"])["id"] == case["id"]
        assert client.get(f"/api/engagements/{engagement}/cases").json()["total"] == 1
        assert client.get(f"/api/engagements/{engagement}").json()["case_counts"]["open"] == 1
        forged = client.post(f"/api/engagements/{engagement}/cases", json={"job_id": job["id"], "source_kind": "check", "source_ref": "invented"}, headers=HEADERS)
        assert forged.status_code == 404
        assert outside["id"] not in client.get(f"/api/engagements/{engagement}").json()["asset_ids"]


def test_triage_cas_and_resolution_require_evidence_not_missing_resource(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        engagement = workspace(client, asset["id"])
        case = add_network_case(client, engagement, baseline["id"])
        response = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 1, "status": "in_progress", "owner": "Local maintainer",
                                                                 "due_date": "2026-11-03", "note": "Review the source CIDR"}, headers=HEADERS)
        assert response.status_code == 200, response.text
        case = response.json()
        assert case["version"] == 2 and case["owner"] == "Local maintainer"
        stale = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 1, "owner": "Stale edit"}, headers=HEADERS)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "CASE_CONFLICT"
        denied = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 2, "status": "resolved", "note": "I think it is fixed"}, headers=HEADERS)
        assert denied.status_code == 409 and denied.json()["error"]["code"] == "RETEST_REQUIRED"
        _, still = saved_cloud(app.state.repository, revision_of=asset)
        assessment = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": still["id"]})
        assert assessment.status_code == 200 and assessment.json()["outcome"] == "still_observed"
        denied = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 2, "status": "resolved", "note": "No change",
                                                               "retest_job_id": still["id"]}, headers=HEADERS)
        assert denied.status_code == 409 and denied.json()["error"]["code"] == "RETEST_NOT_CLEARED"
        _, missing = saved_cloud(app.state.repository, revision_of=asset, missing_resource=True)
        assert client.get(f"/api/cases/{case['id']}/retest", params={"job_id": missing["id"]}).json()["outcome"] == "not_comparable"
        _, cleared = saved_cloud(app.state.repository, revision_of=asset, mitigated=True)
        recorded = client.post(f"/api/cases/{case['id']}/retests", json={"expected_version": 2, "job_id": cleared["id"], "note": "Compare matching resource"}, headers=HEADERS)
        assert recorded.status_code == 200, recorded.text
        case = recorded.json()
        assert case["status"] == "in_progress" and case["version"] == 3
        closed = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 3, "status": "resolved", "note": "Matching rule no longer observes the CIDR condition",
                                                               "retest_job_id": cleared["id"]}, headers=HEADERS)
        assert closed.status_code == 200, closed.text
        case = closed.json()
        assert case["status"] == "resolved" and case["confidence"] == "static_config"
        assert case["events"][-1]["data"]["assessment"]["retest_job_id"] == cleared["id"]
        assert "values" not in case["events"][-1]["data"]["assessment"]
        assert client.patch(f"/api/cases/{case['id']}", json={"expected_version": case["version"], "status": "open"}, headers=HEADERS).status_code == 400
        reopened = client.patch(f"/api/cases/{case['id']}", json={"expected_version": case["version"], "status": "open", "note": "New context warrants review"}, headers=HEADERS)
        assert reopened.status_code == 200


def test_file_revisions_require_explicit_link_without_widening_network_scope(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    original_asset, baseline = saved_cloud(app.state.repository)
    revised_asset, revised = saved_cloud(app.state.repository, mitigated=True)
    with TestClient(app) as client:
        engagement = workspace(client, original_asset["id"])
        case = add_network_case(client, engagement, baseline["id"])
        assert client.get(f"/api/cases/{case['id']}/retest", params={"job_id": revised["id"]}).json()["outcome"] == "not_comparable"
        linked = client.post(f"/api/cases/{case['id']}/retest-inputs", json={"expected_version": case["version"], "asset_id": revised_asset["id"],
                                                                           "note": "Revised plan for the same named resources"}, headers=HEADERS)
        assert linked.status_code == 200, linked.text
        case = linked.json()
        assert len(case["retest_inputs"]) == 1 and case["asset_id"] == original_asset["id"]
        result = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": revised["id"]}).json()
        assert result["outcome"] == "not_observed_in_scope" and result["input_revision"]
        assert client.get(f"/api/engagements/{engagement}").json()["asset_ids"] == [original_asset["id"]]
        assert revised["id"] in {row["id"] for row in client.get(f"/api/cases/{case['id']}/retest-jobs").json()["items"]}
        website = AssetRepository(app.state.repository).create("cloud", "Other service", {"profile_id": "cloud-external", "mode": "probe", "targets": ["https://example.test/"]})
        denied = client.post(f"/api/cases/{case['id']}/retest-inputs", json={"expected_version": case["version"], "asset_id": website["id"], "note": "Different scope"}, headers=HEADERS)
        assert denied.status_code == 400 and denied.json()["error"]["code"] == "INVALID_RETEST_INPUT"


@pytest.mark.parametrize("decision", ["accepted_risk", "false_positive"])
def test_manual_decisions_need_notes_and_do_not_modify_source_certainty(tmp_path: Path, decision: str) -> None:
    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        case = add_network_case(client, workspace(client, asset["id"]), baseline["id"])
        denied = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 1, "status": decision}, headers=HEADERS)
        assert denied.status_code == 400
        updated = client.patch(f"/api/cases/{case['id']}", json={"expected_version": 1, "status": decision, "note": "Explicit local decision, retained evidence"}, headers=HEADERS)
        assert updated.status_code == 200 and updated.json()["confidence"] == "static_config"
        assert app.state.repository.get(baseline["id"])["result"] == baseline["result"]


def test_report_escaping_event_pagination_and_retest_identity(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        engagement = workspace(client, asset["id"])
        case = add_network_case(client, engagement, baseline["id"])
        assert client.get(f"/api/cases/{case['id']}/retest", params={"job_id": baseline["id"]}).status_code == 400
        _, earlier = saved_cloud(app.state.repository, revision_of=asset, mitigated=True)
        with app.state.repository.connection() as connection:
            connection.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (earlier["id"],))
        assert client.get(f"/api/cases/{case['id']}/retest", params={"job_id": earlier["id"]}).status_code == 400
        events = client.get(f"/api/cases/{case['id']}/events?limit=1").json()
        assert len(events["items"]) == 1 and events["next_cursor"]
        assert client.get(f"/api/cases/{case['id']}/events?after=-1").status_code == 400
        report = client.get(f"/api/engagements/{engagement}/export?format=json")
        assert report.status_code == 200 and report.json()["export_scope"]["exported_cases"] == 1
        html = client.get(f"/api/engagements/{engagement}/export?format=html")
        assert html.status_code == 200 and "sandbox" in html.headers["content-security-policy"]
        assert "<script>unsafe()</script>" not in html.text and "&lt;script&gt;" in html.text
        assert client.post("/api/engagements", json={}).status_code == 403
        assert client.get("/api/cases/not-a-valid-id").status_code == 400


def test_service_export_budget_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.core.case_service import CaseService

    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        engagement = workspace(client, asset["id"])
        case = add_network_case(client, engagement, baseline["id"])
        service = CaseService(app.state.repository)
        original = service.detail(case["id"])
        inflated = copy.deepcopy(original)
        inflated["note"] = "x" * (8 * 1024 * 1024 + 1)
        monkeypatch.setattr(service, "detail", lambda _: inflated)
        report = service.export(engagement)
        assert report["export_scope"]["truncated"] and report["export_scope"]["exported_cases"] == 0
        assert report["export_scope"]["total_cases"] == 1
        with pytest.raises(WorkbenchError):
            service.retest_jobs(case["id"], limit=1000)


def test_scope_note_must_not_be_whitespace(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path), headers=HEADERS) as client:
        response = client.post("/api/engagements", json={"name": "Scope", "authorization_note": " \t ", "asset_ids": ["a" * 32]})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_ENGAGEMENT"
