"""Evidence minimisation and opt-in AI advisory API coverage.

The provider used here is deliberately local and deterministic.  These tests
exercise the boundary around a provider call without making an external model
request or treating model output as a finding.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.advisory_context import ContextRegistry, canonical
from reachscope_workbench.core.ai_contracts import validate_selection
from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.defense_catalog import catalog
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.integrations.ai_provider import endpoint

HEADERS = {"X-ReachScope-Client": "workbench"}


@pytest.fixture
def local_http() -> Iterator[tuple[str, list[str]]]:
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            visited.append(self.path)
            body = b'<html><title>untrusted title</title><script>never send this body</script></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", visited
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _result(*, evidence_id: str = "e-1", url: str = "https://example.com/private/page?token=do-not-share") -> dict[str, Any]:
    return {
        "module": "web",
        "target": url,
        "summary": {"assets": 1, "online": 1, "mode": "probe"},
        "evidence": [{"id": evidence_id, "kind": "http_observation", "title": "response", "source": url}],
        "details": {
            "assets": [{
                "url": url,
                "reachable": True,
                "status_code": 200,
                "evidence_ids": [evidence_id, "unknown-evidence"],
                "checks": [{"id": "csp", "status": "pass", "evidence_ids": [evidence_id]}],
                "headers_truncated": [], "body_truncated": False, "cookies_truncated": False,
            }],
            "execution": [
                {"id": "http", "status": "completed"},
                {"id": "headers", "status": "completed"},
                {"id": "page", "status": "skipped"},
                {"id": "fingerprints", "status": "completed"},
            ],
        },
    }


def _standalone_job(*, mode: str = "probe", module: str = "web", result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "f" * 32,
        "module": module,
        "status": "completed",
        "asset_id": "a" * 32,
        "asset_snapshot": {"id": "a" * 32, "kind": "website", "name": "target", "source": {"url": "https://example.com/"}},
        "config": {"mode": mode},
        "result": result or _result(),
    }


def _seed_job(app: Any, *, result: dict[str, Any] | None = None) -> str:
    repository: JobRepository = app.state.repository
    asset = AssetRepository(repository).create("website", "Example", {"url": "https://example.com/"})
    job = repository.create("web", "Web probe", {"mode": "probe"}, asset=asset)
    repository.transition(job["id"], {"queued"}, "completed", "Web probe complete", result=result or _result())
    return job["id"]


class FakeProvider:
    """A provider-shaped fake that never performs network I/O."""

    def __init__(self, *, invalid: bool = False, wait: bool = False) -> None:
        self.calls: list[tuple[dict[str, Any], str, dict[str, Any], list[dict[str, Any]]]] = []
        self.invalid, self.wait = invalid, wait
        self.entered = threading.Event()

    async def consult(self, settings: dict[str, Any], key: str, context: dict[str, Any],
                      controls: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append((settings, key, context, controls))
        self.entered.set()
        if self.wait:
            await asyncio.Event().wait()
        row = {"control_id": "invented.control" if self.invalid else "app.input_validation",
               "priority": "medium", "evidence_ids": []}
        return {"selection": {"red": [row], "blue": [dict(row)]},
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}


def _wait_report(client: TestClient, report_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/advisories/{report_id}")
        assert response.status_code == 200, response.text
        report = response.json()
        if report["status"] in {"completed", "failed", "interrupted"}:
            return report
        time.sleep(0.01)
    raise AssertionError("advisory did not finish")


def _configure(client: TestClient) -> dict[str, Any]:
    response = client.put("/api/ai/config", headers=HEADERS, json={
        "enabled": True, "base_url": "https://api.example.invalid/v1", "model": "fake-model",
        "allow_local": False, "api_key": "memory-only-key",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_web_context_accepts_only_completed_real_probe_and_minimizes_urls() -> None:
    registry = ContextRegistry()
    context = registry.build(_standalone_job())
    assert context["targets"][0]["url"] == "https://example.com/"
    assert context["targets"][0]["evidence_ids"] == ["e-1"]
    assert context["targets"][0]["checks"][0]["evidence_ids"] == ["e-1"]
    assert context["evidence_ids"] == ["e-1"]
    encoded = canonical(context)
    assert "private/page" not in encoded and "token=do-not-share" not in encoded


@pytest.mark.parametrize(
    ("module", "mode", "kind"),
    [("web", "demo", "website"), ("web", "import", "website"), ("cloud", "probe", "cloud")],
)
def test_context_rejects_demo_import_and_cloud_inputs(module: str, mode: str, kind: str) -> None:
    job = _standalone_job(module=module, mode=mode)
    job["asset_snapshot"]["kind"] = kind
    with pytest.raises(WorkbenchError) as caught:
        ContextRegistry().build(job)
    assert caught.value.code == "AI_INPUT_UNSUPPORTED"


def test_context_has_a_hard_64_kibibyte_budget() -> None:
    huge_id = "e" * (64 * 1024)
    job = _standalone_job(result=_result(evidence_id=huge_id))
    with pytest.raises(WorkbenchError) as caught:
        ContextRegistry().build(job)
    assert caught.value.code == "AI_CONTEXT_LIMIT"


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8080/v1",
        "https://user:password@example.com/v1",
        "https://api.example.com/v1?api_key=secret",
        "https://api.example.com/v1#fragment",
        "https://api.example.com/v1/chat/completions",
        "https://metadata.google.internal/v1",
    ],
)
def test_provider_endpoint_rejects_credentials_queries_and_unsafe_targets(value: str) -> None:
    with pytest.raises(WorkbenchError) as caught:
        endpoint(value, allow_local=False)
    assert caught.value.code == "AI_INVALID_ENDPOINT"


def test_structured_selection_rejects_unknown_control_and_evidence_ids() -> None:
    controls = catalog()
    context = {
        "evidence_ids": ["e-1"],
        "targets": [{"checks": [{"id": "csp", "evidence_ids": ["e-1"]}]}],
    }
    unknown_control = {"control_id": "web.not-in-catalog", "priority": "high", "evidence_ids": []}
    good = {"control_id": "app.input_validation", "priority": "medium", "evidence_ids": []}
    with pytest.raises(WorkbenchError, match="未知"):
        validate_selection({"red": [unknown_control], "blue": [good]}, controls, context)

    unknown_evidence = {"control_id": "web.csp", "priority": "high", "evidence_ids": ["e-404"]}
    with pytest.raises(WorkbenchError, match="未知"):
        validate_selection({"red": [unknown_evidence], "blue": [good]}, controls, context)


def test_ai_config_never_persists_secret_and_endpoint_is_reloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REACHSCOPE_AI_API_KEY", raising=False)
    secret = "test-secret-that-must-not-be-written"
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "base_url": "https://api.example.invalid/v1", "model": "fake-model",
            "allow_local": False, "api_key": secret,
        })
        assert response.status_code == 200, response.text
        assert response.json()["has_key"] is True
        assert secret not in response.text
        with closing(sqlite3.connect(tmp_path / "workbench.sqlite3")) as db:
            raw = db.execute("SELECT data FROM ai_settings WHERE id=1").fetchone()[0]
        assert secret not in raw and "api_key" not in raw

    reopened = create_app(tmp_path)
    with TestClient(reopened) as client:
        config = client.get("/api/ai/config").json()
        assert config["base_url"] == "https://api.example.invalid/v1"
        assert config["has_key"] is False
        assert config["credential_source"] == "missing"


def test_fake_provider_preview_submit_idempotency_status_and_safe_export(tmp_path: Path) -> None:
    provider = FakeProvider()
    app = create_app(tmp_path, advisory_provider=provider)
    job_id = _seed_job(app)
    with TestClient(app) as client:
        configured = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "base_url": "https://api.example.invalid/v1", "model": "<script>alert(1)</script>",
            "allow_local": False, "api_key": "memory-only-key",
        })
        assert configured.status_code == 200, configured.text
        preview = client.get(f"/api/jobs/{job_id}/advisory/preview")
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["eligible"] is True
        assert preview_body["context"]["targets"][0]["url"] == "https://example.com/"
        assert preview_body["disclosure"]["bytes"] <= 64 * 1024
        context_sha = preview_body["context_sha256"]

        missing_consent = client.post(f"/api/jobs/{job_id}/advisory", headers={**HEADERS, "Idempotency-Key": "consent-test"}, json={
            "context_sha256": context_sha, "consent": False, "authorization_note": "approved review",
        })
        assert missing_consent.status_code == 400
        assert missing_consent.json()["error"]["code"] == "AI_CONSENT_REQUIRED"
        stale = client.post(f"/api/jobs/{job_id}/advisory", headers={**HEADERS, "Idempotency-Key": "stale-test"}, json={
            "context_sha256": "0" * 64, "consent": True, "authorization_note": "approved review",
        })
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "AI_PREVIEW_STALE"

        key_headers = {**HEADERS, "Idempotency-Key": "advisory-request-1"}
        accepted = client.post(f"/api/jobs/{job_id}/advisory", headers=key_headers, json={
            "context_sha256": context_sha, "consent": True, "authorization_note": "approved review of example.test",
        })
        assert accepted.status_code == 202, accepted.text
        report_id = accepted.json()["id"]
        assert accepted.json()["status"] == "running"
        replay = client.post(f"/api/jobs/{job_id}/advisory", headers=key_headers, json={
            "context_sha256": context_sha, "consent": True, "authorization_note": "approved review of example.test",
        })
        assert replay.status_code == 202 and replay.json()["id"] == report_id
        report = _wait_report(client, report_id)
        assert report["status"] == "completed", report
        assert report["red"][0]["control_id"] == "app.input_validation"
        assert report["usage"]["total_tokens"] == 7
        assert len(provider.calls) == 1

        conflict = client.post(f"/api/jobs/{job_id}/advisory", headers=key_headers, json={
            "context_sha256": context_sha, "consent": True, "authorization_note": "different scope",
        })
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

        html = client.get(f"/api/advisories/{report_id}/export?format=html")
        assert html.status_code == 200
        assert html.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        assert "<script>alert(1)</script>" not in html.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html.text
        exported = client.get(f"/api/advisories/{report_id}/export?format=json")
        assert exported.status_code == 200 and exported.json()["status"] == "completed"


def test_real_local_saved_probe_is_minimized_before_fake_provider_receives_it(
    tmp_path: Path, local_http: tuple[str, list[str]],
) -> None:
    base, visited = local_http
    provider = FakeProvider()
    with TestClient(create_app(tmp_path, advisory_provider=provider)) as client:
        _configure(client)
        target = base + "/private/reset?token=do-not-share"
        asset = client.post("/api/assets", headers=HEADERS, json={
            "kind": "website", "name": "Local test", "source": {
                "profile_id": "website-probe", "mode": "probe", "targets": [target], "allow_private": True,
            },
        })
        assert asset.status_code == 201, asset.text
        inspection = client.post(f"/api/assets/{asset.json()['id']}/inspections", headers=HEADERS,
                                 json={"checks": ["http", "headers", "page"]})
        assert inspection.status_code == 201, inspection.text
        job_id = inspection.json()["id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        assert visited == ["/private/reset?token=do-not-share"]
        preview = client.get(f"/api/jobs/{job_id}/advisory/preview").json()
        assert preview["eligible"] is True
        assert preview["context"]["targets"][0]["url"] == base + "/"
        submitted = client.post(f"/api/jobs/{job_id}/advisory", headers={**HEADERS, "Idempotency-Key": "local-real"}, json={
            "context_sha256": preview["context_sha256"], "consent": True, "authorization_note": "approved local server only",
        })
        assert submitted.status_code == 202, submitted.text
        assert _wait_report(client, submitted.json()["id"])["status"] == "completed"
        assert len(provider.calls) == 1
        settings, key, context, controls = provider.calls[0]
        assert key == "memory-only-key" and settings["model"] == "fake-model"
        assert len(controls) == 14
        payload = canonical(context)
        for excluded in ("private/reset", "do-not-share", "untrusted title", "never send this body", "approved local server only", "memory-only-key"):
            assert excluded not in payload
        known = {row["id"] for row in job["result"]["evidence"]}
        assert set(context["evidence_ids"]) <= known


def test_invalid_provider_output_is_a_durable_failure_without_model_text(tmp_path: Path) -> None:
    provider = FakeProvider(invalid=True)
    app = create_app(tmp_path, advisory_provider=provider)
    job_id = _seed_job(app)
    with TestClient(app) as client:
        _configure(client)
        preview = client.get(f"/api/jobs/{job_id}/advisory/preview").json()
        submitted = client.post(f"/api/jobs/{job_id}/advisory", headers={**HEADERS, "Idempotency-Key": "invalid-output"}, json={
            "context_sha256": preview["context_sha256"], "consent": True, "authorization_note": "approved review",
        })
        assert submitted.status_code == 202, submitted.text
        report = _wait_report(client, submitted.json()["id"])
        assert report["status"] == "failed"
        assert report["error"]["code"] == "AI_INVALID_RESPONSE"
        assert report["red"] == report["blue"] == []
        assert "invented.control" not in canonical(report)
        assert client.get(f"/api/jobs/{job_id}/advisories").json()["total"] == 1


def test_shutdown_cancels_running_provider_without_repeating_call_on_restart(tmp_path: Path) -> None:
    provider = FakeProvider(wait=True)
    app = create_app(tmp_path, advisory_provider=provider)
    job_id = _seed_job(app)
    with TestClient(app) as client:
        _configure(client)
        preview = client.get(f"/api/jobs/{job_id}/advisory/preview").json()
        submitted = client.post(f"/api/jobs/{job_id}/advisory", headers={**HEADERS, "Idempotency-Key": "cancel-running"}, json={
            "context_sha256": preview["context_sha256"], "consent": True, "authorization_note": "approved review",
        })
        assert submitted.status_code == 202, submitted.text
        assert provider.entered.wait(timeout=3)
        report_id = submitted.json()["id"]
        assert client.get(f"/api/advisories/{report_id}").json()["status"] == "running"
    fresh_provider = FakeProvider()
    with TestClient(create_app(tmp_path, advisory_provider=fresh_provider)) as reopened:
        report = reopened.get(f"/api/advisories/{report_id}").json()
        assert report["status"] == "interrupted"
        assert report["error"]["code"] == "AI_INTERRUPTED"
        assert len(provider.calls) == 1 and fresh_provider.calls == []


def test_running_advisory_is_marked_interrupted_on_next_start(tmp_path: Path) -> None:
    app = create_app(tmp_path, advisory_provider=FakeProvider())
    job_id = _seed_job(app)
    with TestClient(app):
        pass
    repository = JobRepository(tmp_path / "workbench.sqlite3")
    report = {
        "module": "web", "mode": "ai_api", "provider": {"base_url": "https://api.example.invalid/v1", "model": "fake"},
        "context_sha256": "1" * 64, "context": {}, "disclosure": {}, "authorization_note": "approved",
        "red": [], "blue": [], "usage": {}, "error": None, "limitations": [],
    }
    from reachscope_workbench.core.advisory_repository import AdvisoryRepository

    saved = AdvisoryRepository(repository).reserve(job_id, "restart-key", "fingerprint", report)
    reopened = create_app(tmp_path, advisory_provider=FakeProvider())
    with TestClient(reopened) as client:
        detail = client.get(f"/api/advisories/{saved['id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "interrupted"
        assert detail.json()["error"]["code"] == "AI_INTERRUPTED"

