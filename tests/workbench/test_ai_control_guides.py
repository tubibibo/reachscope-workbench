"""Guides are reviewed templates linked to selected saved evidence, not execution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.advisory_repository import AdvisoryRepository
from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.defense_catalog import catalog, implementation_guide


def seed_report(app: Any, *, control: str = "web.csp", status: str = "completed") -> dict[str, Any]:
    repository = app.state.repository
    job = repository.create("web", "guide-fixture", {"mode": "probe"})
    report = {
        "module": "web", "mode": "ai_api", "provider": {"base_url": "https://fixture.example.invalid", "model": "fixture"},
        "context_sha256": "a" * 64, "context": {
            "evidence_ids": ["saved-e1", "other-e2"],
            "targets": [{"checks": [
                {"id": "csp", "status": "warning", "evidence_ids": ["saved-e1"]},
                {"id": "nosniff", "status": "pass", "evidence_ids": ["other-e2"]},
            ]}],
        }, "red": [], "blue": [], "disclosure": {}, "authorization_note": "fixture only", "usage": {}, "error": None,
        "limitations": [],
    }
    records = AdvisoryRepository(repository)
    saved = records.reserve(job["id"], "guide-" + job["id"], "fixture", report)
    if status != "running":
        row = {"control_id": control, "evidence_ids": ["saved-e1", "invented-unknown"],
               "actions": ["untrusted-model-command-never-render"]}
        return records.finish(saved["id"], status, {"red": [row], "blue": [dict(row)]})
    return saved


@pytest.mark.parametrize("control", [row["id"] for row in catalog()])
def test_every_original_control_has_safe_generic_guide_without_stack_claims(control: str) -> None:
    guide = implementation_guide(control)
    assert guide["control_id"] == control and guide["environment"] == "generic"
    assert guide["guide_version"] == "2026-11-01"
    assert guide["observed_stack"] is None and guide["requires_environment_confirmation"] is False
    assert guide["templates"] == []
    for key in ("preconditions", "red_review", "blue_steps", "verification", "rollback", "acceptance", "limitations", "references"):
        assert guide[key]
    assert "不会连接服务器" in "".join(guide["rollback"])
    assert "案例关闭仍需既有复测规则" in "".join(guide["acceptance"])


@pytest.mark.parametrize("control", ["web.mime", "web.referrer", "web.frame", "web.csp", "web.cookies"])
def test_nginx_templates_are_opt_in_attributed_and_require_manual_context(control: str) -> None:
    guide = implementation_guide(control, "nginx")
    assert guide["observed_stack"] is None and guide["requires_environment_confirmation"] is True
    assert len(guide["templates"]) == 1
    template = guide["templates"][0]
    assert template["language"] == "nginx" and template["content"].endswith(";")
    assert template["conditions"] and template["limitations"] and template["context"]
    assert any(ref["url"].startswith("https://nginx.org/en/docs/") for ref in template["references"])
    if control != "web.cookies":
        assert "当前层" in "".join(template["limitations"])


def test_sensitive_nginx_guides_keep_csp_and_session_caveats() -> None:
    csp = implementation_guide("web.csp", "nginx")["templates"][0]
    assert "Content-Security-Policy-Report-Only" in csp["content"]
    assert "不会阻止" in "".join(csp["conditions"]) and "已有强制 CSP 必须保留" in "".join(csp["conditions"])
    cookie = implementation_guide("web.cookies", "nginx")["templates"][0]
    assert "CHANGE_ME_SESSION_COOKIE" in cookie["content"]
    assert "1.19.3" in "".join(cookie["conditions"]) and "HTTPS" in "".join(cookie["conditions"])
    assert "Cookie 值" in "".join(cookie["conditions"]) and "跨站登录" in "".join(cookie["conditions"])
    assert implementation_guide("web.tls", "nginx")["templates"] == [], "Do not blindly supply persistent HSTS changes"
    assert "继续生效" in "".join(implementation_guide("web.tls")["rollback"])


def test_guides_are_deep_copies_and_do_not_mutate_stable_catalog_schema() -> None:
    before = catalog()
    modified = implementation_guide("web.mime", "nginx")
    modified["blue_steps"].clear()
    modified["templates"][0]["references"][0]["url"] = "https://untrusted.invalid/"
    assert implementation_guide("web.mime", "nginx")["blue_steps"]
    assert implementation_guide("web.mime", "nginx")["templates"][0]["references"][0]["url"].startswith("https://nginx.org/")
    assert catalog() == before


def test_completed_report_guide_has_only_selected_known_evidence_and_server_owned_content(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        report = seed_report(app)
        response = client.get(f"/api/advisories/{report['id']}/controls/web.csp/guide?environment=nginx")
        assert response.status_code == 200, response.text
        guide = response.json()
        assert guide["report_id"] == report["id"] and guide["job_id"] == report["job_id"]
        assert guide["evidence_ids"] == ["saved-e1"]
        assert guide["signal_statuses"] == [{"check_id": "csp", "status": "warning", "evidence_ids": ["saved-e1"]}]
        assert "invented-unknown" not in response.text and "untrusted-model-command-never-render" not in response.text
        assert guide["observed_stack"] is None
        assert app.state.advisory.records.get(report["id"]) == report


@pytest.mark.parametrize("status", ["running", "failed", "interrupted"])
def test_non_completed_reports_cannot_supply_implementation_guides(tmp_path: Path, status: str) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        report = seed_report(app, status=status)
        response = client.get(f"/api/advisories/{report['id']}/controls/web.csp/guide")
        assert response.status_code == 400 and response.json()["error"]["code"] == "AI_GUIDE_UNAVAILABLE"


def test_report_cannot_request_unselected_or_unknown_controls_or_arbitrary_environment(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        report = seed_report(app)
        for control in ("web.mime", "invented.control"):
            response = client.get(f"/api/advisories/{report['id']}/controls/{control}/guide")
            assert response.status_code == 404 and response.json()["error"]["code"] == "AI_CONTROL_NOT_FOUND"
        invalid = client.get(f"/api/advisories/{report['id']}/controls/web.csp/guide?environment=arbitrary-command")
        assert invalid.status_code == 422


def test_manual_review_guide_does_not_manufacture_web_check_evidence(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        report = seed_report(app, control="app.access_control")
        response = client.get(f"/api/advisories/{report['id']}/controls/app.access_control/guide?environment=nginx")
        assert response.status_code == 200, response.text
        guide = response.json()
        assert guide["applicability"] == "manual_review" and guide["signal_statuses"] == [] and guide["templates"] == []
        assert "不登录" in json.dumps(guide["limitations"], ensure_ascii=False)


def seed_probe(app: Any, *, state: str = "review", execution: str = "completed", origin: str = "probe",
               mode: str = "probe", kind: str = "website", status: str = "completed", reachable: bool = True,
               profile_id: str | None = None) -> dict[str, Any]:
    repository = app.state.repository
    provenance = {"kind": "local_training", "label": "controlled fixture", "session_id": "fixture"} if origin == "local_training" else None
    asset = AssetRepository(repository).create(kind, "fixture", {"url": "https://fixture.example.invalid/",
                                                               **({"profile_id": profile_id} if profile_id else {})}, provenance=provenance)
    job = repository.create("web", "guide-fixture", {"mode": mode}, asset=asset)
    result = {"evidence": [{"id": "saved-e1"}], "details": {
        "assets": [{"url": "https://fixture.example.invalid/", "reachable": reachable, "status_code": 200,
                    "evidence_ids": ["saved-e1", "invented-unknown"], "checks": [
                        {"id": "csp", "status": state}, {"id": "nosniff", "status": "pass"},
                        {"id": "mixed_content", "status": "review"},
                    ]}],
        "execution": [{"id": "http", "status": "completed"}, {"id": "headers", "status": execution},
                      {"id": "page", "status": "completed"}],
    }}
    repository.transition(job["id"], {"queued"}, status, "fixture complete", result=result)
    return repository.get(job["id"])


@pytest.mark.parametrize("state", ["pass", "review", "unknown"])
def test_job_guides_are_available_without_ai_and_preserve_check_state(tmp_path: Path, state: str) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        job = seed_probe(app, state=state)
        assert client.get("/api/ai/config").json()["enabled"] is False
        response = client.get(f"/api/jobs/{job['id']}/controls")
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["origin"] == "probe" and value["ai_required"] is False and value["source_kind"] == "deterministic_saved_evidence"
        indexed = {row["control_id"]: row for row in value["items"]}
        assert set(indexed) == {"web.csp", "web.mime", "web.mixed_content"}
        assert indexed["web.csp"]["states"] == [state] and indexed["web.csp"]["evidence_ids"] == ["saved-e1"]
        guide = client.get(f"/api/jobs/{job['id']}/controls/web.csp/guide?environment=nginx")
        assert guide.status_code == 200, guide.text
        assert guide.json()["states"] == [state] and guide.json()["evidence_ids"] == ["saved-e1"]
        assert guide.json()["signal_statuses"] == [{"check_id": "csp", "status": state, "evidence_ids": ["saved-e1"]}]
        assert "invented-unknown" not in response.text + guide.text
        assert client.app.state.repository.get(job["id"]) == job
        assert client.app.state.advisory.records.list(job["id"])["total"] == 0


def test_job_controls_do_not_expose_unexecuted_manual_or_endpoint_topics(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        job = seed_probe(app, execution="skipped")
        response = client.get(f"/api/jobs/{job['id']}/controls")
        assert response.status_code == 200
        assert [row["control_id"] for row in response.json()["items"]] == ["web.mixed_content"]
        for control in ("web.csp", "app.input_validation", "endpoint.hygiene"):
            denied = client.get(f"/api/jobs/{job['id']}/controls/{control}/guide")
            assert denied.status_code == 404 and denied.json()["error"]["code"] == "GUIDE_CONTROL_NOT_FOUND"


def test_teaching_probe_remains_explicit_in_ai_context_and_deterministic_guides(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        job = seed_probe(app, origin="local_training")
        preview = client.get(f"/api/jobs/{job['id']}/advisory/preview").json()
        assert preview["context"]["origin"] == "local_training"
        listed = client.get(f"/api/jobs/{job['id']}/controls").json()
        assert listed["origin"] == "local_training"
        guide = client.get(f"/api/jobs/{job['id']}/controls/web.csp/guide").json()
        assert guide["origin"] == "local_training" and guide["observed_stack"] is None


@pytest.mark.parametrize("change", [
    {"mode": "demo"}, {"mode": "import"}, {"kind": "cloud"}, {"status": "failed"}, {"reachable": False},
])
def test_job_guides_reject_non_website_probes_and_failed_collection(tmp_path: Path, change: dict[str, Any]) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        job = seed_probe(app, **change)
        response = client.get(f"/api/jobs/{job['id']}/controls")
        assert response.status_code == 400 and response.json()["error"]["code"] == "GUIDE_INPUT_UNSUPPORTED"


@pytest.mark.parametrize("state", ["review", "pass", "unknown"])
def test_cloud_service_http_guides_preserve_cloud_identity_without_enabling_ai(tmp_path: Path, state: str) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        job = seed_probe(app, state=state, kind="cloud", profile_id="cloud-external")
        response = client.get(f"/api/jobs/{job['id']}/controls")
        assert response.status_code == 200, response.text
        available = response.json()
        assert available["origin"] == "cloud_service_probe" and available["ai_required"] is False
        csp = next(row for row in available["items"] if row["control_id"] == "web.csp")
        assert csp["states"] == [state] and csp["evidence_ids"] == ["saved-e1"]
        guide = client.get(f"/api/jobs/{job['id']}/controls/web.csp/guide?environment=nginx")
        assert guide.status_code == 200
        assert guide.json()["origin"] == "cloud_service_probe"
        assert "IAM" in "".join(guide.json()["limitations"])
        assert guide.json()["observed_stack"] is None
        # Sharing deterministic guides must never widen the paid context policy.
        preview = client.get(f"/api/jobs/{job['id']}/advisory/preview").json()
        assert preview["eligible"] is False
        assert app.state.advisory.records.list(job["id"])["total"] == 0
        assert app.state.repository.get(job["id"]) == job


@pytest.mark.parametrize("change", [{"mode": "import"}, {"mode": "demo"}, {"status": "failed"},
                                     {"reachable": False}, {"profile_id": "cloud-config"}])
def test_cloud_external_guide_boundary_rejects_import_config_and_failed_capture(tmp_path: Path, change: dict[str, Any]) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        options: dict[str, Any] = {"kind": "cloud", "profile_id": "cloud-external", **change}
        job = seed_probe(app, **options)
        response = client.get(f"/api/jobs/{job['id']}/controls")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "GUIDE_INPUT_UNSUPPORTED"
