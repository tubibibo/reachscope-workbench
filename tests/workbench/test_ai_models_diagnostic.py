"""Saved-provider catalogue checks are explicit, bounded GETs, not inference."""
from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.integrations import ai_provider

HEADERS = {"X-ReachScope-Client": "workbench"}
BASE = "https://configured.example.invalid/v1"
SECRET = "fixture-saved-provider-key"


def configure(client: TestClient, **changes: Any) -> dict[str, Any]:
    response = client.put("/api/ai/config", headers=HEADERS, json={
        "enabled": True, "provider_id": "custom", "base_url": BASE, "model": "selected-model", "api_key": SECRET, **changes,
    })
    assert response.status_code == 200, response.text
    return response.json()


def mock_catalogue(monkeypatch: pytest.MonkeyPatch, body: bytes, status: int = 200) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    async def addresses(*_args: Any) -> list[str]:
        return ["93.184.216.34"]

    async def send(_client: httpx.AsyncClient, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, request=request, headers={"Content-Type": "application/json"}, stream=httpx.ByteStream(body))

    monkeypatch.setattr(ai_provider, "_addresses", addresses)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return seen


def test_saved_models_diagnostic_sends_one_scoped_get_and_returns_only_selected_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    raw = json.dumps({"data": [{"id": "selected-model"}, {"id": "private-unselected-model"}]}).encode()
    seen = mock_catalogue(monkeypatch, raw)
    with TestClient(create_app(tmp_path)) as client:
        config = configure(client)
        result = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": config["configuration_sha256"], "consent": True,
        })
        assert result.status_code == 200, result.text
        value = result.json()
        assert value["kind"] == "saved_models" and value["base_url"] == BASE
        assert value["status"] == "models_visible" and value["model_available"] is True
        assert value["authentication"] == "accepted"
        assert value["model_call"] is False and value["inference_verified"] is False and value["business_data_sent"] is False
        assert "private-unselected-model" not in result.text and SECRET not in result.text + caplog.text
        assert client.get("/api/ai/config").json() == config
        with client.app.state.repository.connection() as db:
            assert db.execute("SELECT COUNT(*) FROM ai_reports").fetchone()[0] == 0
            assert "private-unselected-model" not in db.execute("SELECT data FROM ai_settings WHERE id=1").fetchone()[0]
    assert len(seen) == 1 and seen[0].method == "GET" and seen[0].url.path == "/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer " + SECRET
    assert seen[0].headers["Host"] == "configured.example.invalid"
    assert seen[0].extensions["sni_hostname"] == "configured.example.invalid"
    assert seen[0].content == b""


@pytest.mark.parametrize(("status", "state", "authentication"), [
    (401, "auth_rejected", "rejected"), (403, "access_denied", "rejected"),
    (404, "models_unsupported", "unknown"), (405, "models_unsupported", "unknown"),
    (429, "rate_limited", "unknown"), (302, "redirect_blocked", "unknown"),
    (500, "provider_unavailable", "unknown"),
])
def test_models_http_classification_never_exposes_provider_errors_or_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, state: str, authentication: str,
) -> None:
    seen = mock_catalogue(monkeypatch, b'{"error":"private-provider-message-or-key"}', status)
    with TestClient(create_app(tmp_path)) as client:
        config = configure(client)
        result = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": config["configuration_sha256"], "consent": True,
        })
        assert result.status_code == 200, result.text
        assert result.json()["http_status"] == status and result.json()["status"] == state
        assert result.json()["authentication"] == authentication and result.json()["model_available"] is None
        assert "private-provider-message-or-key" not in result.text
    assert len(seen) == 1 and seen[0].method == "GET"


@pytest.mark.parametrize(("body", "available", "state"), [
    ({"data": [{"id": "different-model"}]}, False, "models_visible"),
    ({"data": []}, False, "models_visible"),
    ({"data": [], "has_more": True}, None, "models_visible"),
    ({"data": [], "next_cursor": "cursor"}, None, "models_visible"),
    ({"data": [{"id": "selected-model"}], "has_more": True}, True, "models_visible"),
    ({"data": [{"id": []}]}, None, "models_unsupported"),
    ({"data": "not-a-directory"}, None, "models_unsupported"),
])
def test_models_match_preserves_missing_and_partial_directory_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], available: bool | None, state: str,
) -> None:
    mock_catalogue(monkeypatch, json.dumps(body).encode())
    with TestClient(create_app(tmp_path)) as client:
        config = configure(client)
        result = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": config["configuration_sha256"], "consent": True,
        })
        assert result.status_code == 200, result.text
        assert result.json()["status"] == state and result.json()["model_available"] is available


@pytest.mark.parametrize(("body", "state"), [(b"not-json-private-provider-error", "models_unsupported"), (b"x" * (128 * 1024 + 1), "response_limit")])
def test_models_response_budget_and_invalid_json_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes, state: str,
) -> None:
    mock_catalogue(monkeypatch, body)
    with TestClient(create_app(tmp_path)) as client:
        config = configure(client)
        result = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": config["configuration_sha256"], "consent": True,
        })
        assert result.status_code == 200 and result.json()["status"] == state
        assert "private-provider-error" not in result.text and result.json()["model_available"] is None


def test_models_diagnostic_requires_consent_current_revision_and_saved_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = mock_catalogue(monkeypatch, b'{"data":[]}')
    monkeypatch.delenv("REACHSCOPE_AI_API_KEY", raising=False)
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/ai/config").json()
        missing = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": before["configuration_sha256"], "consent": True,
        })
        assert missing.status_code == 409 and missing.json()["error"]["code"] == "AI_NOT_CONFIGURED"
        saved = configure(client)
        no_consent = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": saved["configuration_sha256"], "consent": False,
        })
        assert no_consent.status_code == 400 and no_consent.json()["error"]["code"] == "AI_CONSENT_REQUIRED"
        changed = configure(client, base_url="https://other.example.invalid/v1", api_key=None)
        assert changed["has_key"] is False
        stale = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": saved["configuration_sha256"], "consent": True,
        })
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "AI_PREVIEW_STALE"
        draft = client.post("/api/ai/diagnose/models", headers=HEADERS, json={
            "configuration_sha256": changed["configuration_sha256"], "consent": True, "base_url": BASE,
        })
        assert draft.status_code == 422
    assert seen == []


@pytest.mark.parametrize(("failure", "code"), [("tls", "tls_verification_failed"), ("connect", "connection_failed"), ("dns", "dns_failed")])
async def test_models_network_failures_remain_unknown_without_error_text(
    monkeypatch: pytest.MonkeyPatch, failure: str, code: str,
) -> None:
    mock_catalogue(monkeypatch, b'{"data":[]}')

    async def addresses(*_args: Any) -> list[str]:
        raise WorkbenchError("AI_NETWORK_ERROR", "private-resolver-detail")

    async def fail(_client: httpx.AsyncClient, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        if failure == "tls":
            raise httpx.ConnectError("private-network-details", request=request) from ssl.SSLCertVerificationError("private-cert-details")
        raise httpx.ConnectError("private-network-details", request=request)

    if failure == "dns":
        monkeypatch.setattr(ai_provider, "_addresses", addresses)
    else:
        monkeypatch.setattr(httpx.AsyncClient, "send", fail)
    result = await ai_provider.diagnose_models({"base_url": BASE, "model": "selected-model"}, SECRET)
    assert result["error_code"] == code and result["model_available"] is None and result["authentication"] == "unknown"
    assert "private-" not in str(result) and SECRET not in str(result)


async def test_models_deadline_also_bounds_dns_and_never_assumes_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stall(*_args: Any) -> list[str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(ai_provider, "_addresses", stall)
    monkeypatch.setattr(ai_provider, "_DIAGNOSTIC_TIMEOUT", 0.01)
    result = await asyncio.wait_for(ai_provider.diagnose_models({"base_url": BASE, "model": "selected-model"}, SECRET), 1)
    assert result["error_code"] == "timeout" and result["stage"] == "dns"
    assert result["authentication"] == "unknown" and result["model_available"] is None
