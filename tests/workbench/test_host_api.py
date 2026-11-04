"""Actual host file/preview/selected-analysis/case APIs, without target execution."""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.case_sources import candidates, compare_retest
from reachscope_workbench.modules.host import HostModule
from reachscope_workbench.modules.host.demo import (
    access_bytes,
    auth_bytes,
    baseline_bytes,
    input_template,
)

HEADERS = {"X-ReachScope-Client": "workbench"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path)) as current:
        yield current


def save(client: TestClient, raw: bytes, *, profile: str = "host-baseline", host: str = "srv-web-01") -> dict[str, Any]:
    mode = {"host-baseline": "baseline", "host-access-log": "access_log", "host-auth-log": "auth_log"}[profile]
    filename = "snapshot.json" if mode == "baseline" else "events.log"
    response = client.post("/api/uploads", files={"file": (filename, raw)}, headers=HEADERS)
    assert response.status_code == 201, response.text
    uploaded = response.json()
    response = client.post("/api/assets", json={"kind": "host", "name": "Controlled host input", "source": {
        "profile_id": profile, "mode": mode, "host_id": host, "upload_id": uploaded["id"], "filename": uploaded["filename"],
    }}, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def inspect(client: TestClient, asset: dict[str, Any], checks: list[str]) -> dict[str, Any]:
    response = client.post(f"/api/assets/{asset['id']}/inspections", json={"checks": checks}, headers=HEADERS)
    assert response.status_code == 201, response.text
    job = response.json()
    until = time.monotonic() + 10
    while job["status"] in {"queued", "running"} and time.monotonic() < until:
        time.sleep(.02)
        job = client.get("/api/jobs/" + job["id"]).json()
    assert job["status"] == "completed", job.get("error")
    return job


def test_template_and_preview_are_local_without_job_or_evidence_creation(client: TestClient) -> None:
    template = client.get("/api/host/template")
    assert template.status_code == 200 and "attachment" in template.headers["content-disposition"]
    assert template.json()["schema_version"] == "reachscope-host/1"
    asset = save(client, template.content)
    preview = client.post(f"/api/assets/{asset['id']}/preflight", json={"checks": ["ssh"]}, headers=HEADERS)
    assert preview.status_code == 200 and preview.json()["ready"]
    data = preview.json()["input_preview"]
    assert data["module"] == "host" and data["analysis_executed"] is False and data["network_requests"] is False
    assert "permitrootlogin" not in json.dumps(data)
    assert client.get("/api/jobs").json()["total"] == 0
    assert client.get("/api/assets?kind=host").json()["total"] == 1


@pytest.mark.parametrize("checks", [["ssh"], ["nginx"], ["ssh", "nginx"]])
def test_selected_baseline_groups_really_execute_and_keep_saved_input(client: TestClient, checks: list[str]) -> None:
    asset = save(client, baseline_bytes("srv-web-01"))
    job = inspect(client, asset, checks)
    assert job["module"] == "host" and job["asset_id"] == asset["id"]
    result = job["result"]
    assert all(row["id"].split(".")[1] in checks for row in result["details"]["checks"])
    assert job["asset_snapshot"]["source"]["host_id"] == "srv-web-01"
    assert result["details"]["live_state_verified"] is False
    assert all(row["guidance"]["rollback"] for row in result["details"]["checks"])
    execution = {row["id"]: row["status"] for row in result["details"]["execution"]}
    assert execution["auth_logs"] == execution["web_logs"] == "skipped"
    preview = client.get(f"/api/jobs/{job['id']}/advisory/preview").json()
    assert preview["eligible"] is False


@pytest.mark.parametrize(("profile", "raw", "checks"), [("host-access-log", access_bytes(), ["web_logs"]),
                                                        ("host-auth-log", auth_bytes(), ["auth_logs"])])
def test_uploaded_log_results_exports_and_case_sources_keep_privacy(client: TestClient, profile: str, raw: bytes, checks: list[str]) -> None:
    asset = save(client, raw, profile=profile)
    job = inspect(client, asset, checks)
    result = job["result"]
    assert result["details"]["log_events"] and any(row["status"] == "review" for row in result["details"]["checks"])
    assert all(row["status"] != "pass" for row in result["details"]["checks"])
    for format in ("json", "html"):
        exported = client.get(f"/api/jobs/{job['id']}/export?format={format}")
        assert exported.status_code == 200
        for private in ("SYNTHETIC_ONLY", "SYNTHETIC_USER", "192.0.2.10", "192.0.2.20", "/private?", "Synthetic fixture"):
            assert private not in exported.text
    selected = candidates(job)[0]
    assert selected["confidence"] == "log_indicator"
    after = copy.deepcopy(job)
    after["id"] = "different"
    for row in after["result"]["details"]["checks"]:
        row["status"] = "pass"
    assert compare_retest(job, selected["source_kind"], selected["source_ref"], after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("raw", [b"not json", b'{}', b'{"schema_version":"other"}', b'{"schema_version":"reachscope-host/1","host_id":"different"}'])
def test_invalid_or_cross_host_input_blocks_preflight_and_submission(client: TestClient, raw: bytes) -> None:
    asset = save(client, raw)
    path = f"/api/assets/{asset['id']}"
    readiness = client.post(path + "/preflight", json={"checks": ["ssh"]}, headers=HEADERS)
    assert readiness.status_code == 200 and readiness.json()["ready"] is False
    response = client.post(path + "/inspections", json={"checks": ["ssh"]}, headers=HEADERS)
    assert response.status_code == 409
    assert client.get("/api/jobs").json()["total"] == 0


def test_real_baseline_revision_case_closes_only_after_explicit_relation(client: TestClient) -> None:
    asset = save(client, baseline_bytes("srv-web-01"))
    before = inspect(client, asset, ["ssh"])
    engagement = client.post("/api/engagements", json={"name": "Host baseline acceptance", "authorization_note": "Controlled synthetic exported inputs", "asset_ids": [asset["id"]]}, headers=HEADERS).json()
    selected = next(row for row in candidates(before) if row["category"] == "host.ssh.root_login")
    response = client.post(f"/api/engagements/{engagement['id']}/cases", json={"job_id": before["id"], "source_kind": selected["source_kind"], "source_ref": selected["source_ref"]}, headers=HEADERS)
    assert response.status_code == 201, response.text
    case = response.json()
    revised = save(client, baseline_bytes("srv-web-01", hardened=True))
    after = inspect(client, revised, ["ssh"])
    path = f"/api/cases/{case['id']}"
    assessment = client.get(path + "/retest", params={"job_id": after["id"]})
    assert assessment.json()["outcome"] == "not_comparable"
    linked = client.post(path + "/retest-inputs", json={"expected_version": case["version"], "asset_id": revised["id"], "note": "Same declared host and global SSH context; corrected exported settings"}, headers=HEADERS)
    assert linked.status_code == 200, linked.text
    assessment = client.get(path + "/retest", params={"job_id": after["id"]}).json()
    assert assessment["outcome"] == "not_observed_in_scope", assessment
    updated = client.patch(path, json={"expected_version": linked.json()["version"], "status": "resolved", "note": "Reviewed corrected export; runtime deployment requires separate administrator verification", "retest_job_id": after["id"]}, headers=HEADERS)
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "resolved"
    assert client.get("/api/jobs/" + before["id"]).json() == before


@pytest.mark.parametrize("config", [{"mode": "baseline", "host_id": ""}, {"mode": "demo", "checks": ["other"]},
                                   {"mode": "demo", "host_id": "bad\nidentity"}, {"mode": "demo", "host_id": True},
                                   {"mode": "demo", "command": "ignored?"}, {"mode": "access_log", "checks": ["ssh"]}])
def test_host_configuration_rejects_unsupported_scope(config: dict[str, Any]) -> None:
    from reachscope_workbench.core.models import WorkbenchError
    with pytest.raises(WorkbenchError):
        HostModule().validate(config)


def test_synthetic_template_contains_no_real_host_state() -> None:
    assert input_template()["host_id"] == "srv-web-01"


def test_demo_origin_and_event_identity_remain_explicit_in_every_part(client: TestClient) -> None:
    response = client.post("/api/assets", json={"kind": "host", "name": "Synthetic host", "source": {
        "profile_id": "host-demo", "mode": "demo"}}, headers=HEADERS)
    assert response.status_code == 201
    job = inspect(client, response.json(), ["ssh", "nginx", "web_logs", "auth_logs"])
    result = job["result"]
    assert result["details"]["origin"] == "synthetic_demo"
    for proof in result["evidence"]:
        assert proof["data"].get("source_kind", proof["data"].get("capture_kind")) == "synthetic_demo"
    events = result["details"]["log_events"]
    assert len({row["id"] for row in events}) == len(events)
    assert all(row["source_kind"] == "synthetic_demo" for row in events)
    assert {row["input_kind"] for row in events} == {"access_log", "auth_log"}


def test_log_upload_budget_rejects_oversized_file_without_leftover_metadata(client: TestClient) -> None:
    response = client.post("/api/uploads", files={"file": ("oversized.log", b"x" * (2 * 1024 * 1024 + 1))}, headers=HEADERS)
    assert response.status_code == 400 and response.json()["error"]["code"] == "UPLOAD_LIMIT"
    repository = client.app.state.repository
    with repository.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
    assert list(repository.path.parent.joinpath("uploads").iterdir()) == []


def test_revision_cannot_change_host_identity_even_when_profile_matches(client: TestClient) -> None:
    asset = save(client, baseline_bytes("srv-web-01"))
    before = inspect(client, asset, ["ssh"])
    engagement = client.post("/api/engagements", json={"name": "Scoped host review", "authorization_note": "Synthetic files only", "asset_ids": [asset["id"]]}, headers=HEADERS).json()
    selected = next(row for row in candidates(before) if row["category"] == "host.ssh.root_login")
    case = client.post(f"/api/engagements/{engagement['id']}/cases", json={"job_id": before["id"], "source_kind": selected["source_kind"], "source_ref": selected["source_ref"]}, headers=HEADERS).json()
    other = save(client, baseline_bytes("different-host", hardened=True), host="different-host")
    response = client.post(f"/api/cases/{case['id']}/retest-inputs", json={"expected_version": case["version"], "asset_id": other["id"], "note": "Must not expand host scope"}, headers=HEADERS)
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_RETEST_INPUT"
