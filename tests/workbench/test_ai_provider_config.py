"""Provider preset, configuration and connection-diagnostic boundaries."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.ai_providers import infer_provider, presets
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.integrations import ai_provider
from reachscope_workbench.integrations.ai_provider import ChatCompletionsProvider

HEADERS = {"X-ReachScope-Client": "workbench"}


class NoCallProvider:
    """Provider spy: diagnostics must not enter the advisory provider port."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def consult(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        raise AssertionError("diagnose must not call the model provider")


@pytest.fixture
def protocol_fixture() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size)
            requests.append({"method": "POST", "path": self.path,
                             "headers": dict(self.headers), "body": json.loads(raw)})
            payload = {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"red": [], "blue": []}),
            }}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            requests.append({"method": "GET", "path": self.path,
                             "headers": dict(self.headers), "body": None})
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_provider_presets_are_stable_and_expose_openai_deepseek_custom(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/ai/providers")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert {item["id"] for item in items} == {"openai_compatible", "deepseek", "custom"}
        indexed = {item["id"]: item for item in items}
        assert indexed["openai_compatible"]["base_url"] == "https://api.openai.com/v1"
        assert indexed["deepseek"]["base_url"] == "https://api.deepseek.com/v1"
        assert indexed["deepseek"]["models"] == ["deepseek-flash", "deepseek-v4-pro"]
        assert indexed["custom"]["base_url"] == ""
        assert indexed["deepseek"]["reasoning_efforts"] == ["default", "none", "low", "high", "max"]
        assert indexed["openai_compatible"]["token_limit_field"] == "max_completion_tokens"
        assert indexed["custom"]["token_limit_field"] == "max_tokens"


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": False, "provider_id": "custom", "base_url": "https://api.example.test/v1?token=secret"},
        {"enabled": False, "provider_id": "custom", "base_url": "https://user:pass@example.test/v1"},
        {"enabled": True, "provider_id": "custom", "base_url": "https://api.example.test/v1", "model": "model\nname"},
        {"enabled": True, "provider_id": "custom", "base_url": "https://api.example.test/v1", "model": ""},
    ],
)
def test_provider_configuration_rejects_unsafe_base_or_model(tmp_path: Path, payload: dict[str, Any]) -> None:
    with TestClient(create_app(tmp_path)) as client:
        response = client.put("/api/ai/config", headers=HEADERS, json=payload)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] in {"AI_INVALID_ENDPOINT", "AI_INVALID_CONFIG"}


def test_deepseek_configuration_is_saved_but_key_stays_in_session_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REACHSCOPE_AI_API_KEY", raising=False)
    secret = "deepseek-session-secret"
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash", "reasoning_effort": "max", "api_key": secret,
        })
        assert response.status_code == 200, response.text
        config = response.json()
        assert config["provider_id"] == "deepseek"
        assert config["provider_label"] == "DeepSeek"
        assert config["has_key"] is True and config["credential_source"] == "session"
        with client.app.state.repository.connection() as db:
            stored = db.execute("SELECT data FROM ai_settings WHERE id=1").fetchone()[0]
        assert secret not in stored and "api_key" not in stored

    with TestClient(create_app(tmp_path)) as reopened:
        config = reopened.get("/api/ai/config").json()
        assert config["provider_id"] == "deepseek"
        assert config["base_url"] == "https://api.deepseek.com/v1"
        assert config["has_key"] is False and config["credential_source"] == "missing"


def test_diagnose_connection_reset_is_safe_and_sends_no_business_data_or_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = NoCallProvider()
    app = create_app(tmp_path, advisory_provider=spy)
    seen: list[httpx.Request] = []

    async def reset(_client: httpx.AsyncClient, request: httpx.Request, **_: Any) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("connection reset by peer", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", reset)
    with TestClient(app) as client:
        configured = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "provider_id": "custom", "base_url": "http://127.0.0.1:19991/v1",
            "model": "diagnostic-model", "allow_local": True, "api_key": "business-secret",
        })
        assert configured.status_code == 200, configured.text
        response = client.post("/api/ai/diagnose", json={"provider_id": "custom"}, headers=HEADERS)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "unreachable"
        assert result["model_call"] is False and result["business_data_sent"] is False
        assert result["provider_id"] == "custom"
        assert "connection reset by peer" not in response.text
        assert "business-secret" not in response.text
        assert spy.calls == []
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert "authorization" not in seen[0].headers
    assert seen[0].content == b""


def test_custom_request_does_not_assume_gpt_reasoning_parameters(protocol_fixture: tuple[str, list[dict[str, Any]]]) -> None:
    base, requests = protocol_fixture
    response = asyncio.run(ChatCompletionsProvider().consult(
        {"base_url": base, "allow_local": True, "model": "protocol-fixture"},
        "protocol-key", {"evidence_ids": [], "targets": []}, [],
    ))
    assert response["usage"]["total_tokens"] == 2
    assert len(requests) == 1 and requests[0]["method"] == "POST"
    payload = requests[0]["body"]
    assert "reasoning_effort" not in payload
    assert payload["max_tokens"] == 4096 and "max_completion_tokens" not in payload
    assert payload["model"] == "protocol-fixture"
    assert requests[0]["headers"]["Authorization"] == "Bearer protocol-key"


@pytest.mark.parametrize(("provider", "effort", "budget_field"), [
    ("openai_compatible", "max", "max_completion_tokens"),
    ("deepseek", "high", "max_tokens"), ("deepseek", "none", "max_tokens"),
    ("custom", "default", "max_completion_tokens"),
])
def test_provider_specific_payload_preserves_explicit_selection(
    protocol_fixture: tuple[str, list[dict[str, Any]]], provider: str, effort: str, budget_field: str,
) -> None:
    base, requests = protocol_fixture
    asyncio.run(ChatCompletionsProvider().consult(
        {"base_url": base, "allow_local": True, "model": "explicit-model", "provider_id": provider,
         "reasoning_effort": effort, "token_limit_field": budget_field}, "fixture-only-key", {}, [],
    ))
    payload = requests[0]["body"]
    assert payload[budget_field] == 4096
    assert ("max_tokens" in payload) != ("max_completion_tokens" in payload)
    assert payload.get("reasoning_effort") == (None if effort == "default" else effort)
    assert len(requests) == 1


@pytest.mark.parametrize(("base", "expected"), [
    ("https://api.deepseek.com/v1", "deepseek"), ("https://API.OPENAI.COM./v1", "openai_compatible"),
    ("https://api.deepseek.com.attacker.invalid/v1", "custom"),
    ("https://attacker.invalid/api.openai.com", "custom"), ("https://[broken", "custom"),
])
def test_provider_inference_uses_hostname_not_substrings(base: str, expected: str) -> None:
    assert infer_provider(base) == expected


def test_provider_presets_return_defensive_copies() -> None:
    original = presets()
    original[1]["models"].append("mutated")
    original[1]["reasoning_efforts"].append("unknown")
    assert "mutated" not in presets()[1]["models"]
    assert "unknown" not in presets()[1]["reasoning_efforts"]


@pytest.mark.parametrize("payload", [
    {"provider_id": []}, {"provider_id": {}}, {"provider_id": 7}, {"provider_id": "unsupported"},
    {"provider_id": "custom", "api_key": "do-not-reflect-this-key"},
    {"base_url": "http://127.0.0.1:19991", "allow_local": "true"},
])
def test_diagnostic_contract_rejects_malformed_values_without_reflecting_secrets(tmp_path: Path, payload: Any) -> None:
    with TestClient(create_app(tmp_path)) as client:
        result = client.post("/api/ai/diagnose", headers=HEADERS, json=payload)
        assert result.status_code == 422
        assert "do-not-reflect-this-key" not in result.text


def test_diagnostic_uses_unsaved_draft_and_never_mutates_config(
    tmp_path: Path, protocol_fixture: tuple[str, list[dict[str, Any]]],
) -> None:
    base, requests = protocol_fixture
    with TestClient(create_app(tmp_path)) as client:
        original = client.get("/api/ai/config").json()
        result = client.post("/api/ai/diagnose", headers=HEADERS, json={
            "provider_id": "deepseek", "base_url": base, "allow_local": True,
        })
        assert result.status_code == 200, result.text
        diagnosis = result.json()
        assert diagnosis["base_url"] == base and diagnosis["status"] == "reachable_auth_required"
        assert diagnosis["model_call"] is False and diagnosis["business_data_sent"] is False
        assert client.get("/api/ai/config").json() == original
    assert len(requests) == 1 and requests[0]["method"] == "GET"
    assert not any(key.lower() == "authorization" for key in requests[0]["headers"])


@pytest.mark.parametrize(("changed", "expected_key"), [
    ({"base_url": "https://second.example.invalid/v1"}, False),
    ({"base_url": "https://first.example.invalid/other-api"}, False),
    ({"provider_id": "openai_compatible"}, False),
    ({"model": "a-different-model"}, True),
])
def test_session_key_does_not_follow_provider_or_endpoint_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: dict[str, Any], expected_key: bool,
) -> None:
    monkeypatch.delenv("REACHSCOPE_AI_API_KEY", raising=False)
    settings = {"enabled": True, "provider_id": "custom", "base_url": "https://first.example.invalid/v1", "model": "example"}
    with TestClient(create_app(tmp_path)) as client:
        first = client.put("/api/ai/config", headers=HEADERS, json={**settings, "api_key": "first-endpoint-only"})
        assert first.status_code == 200 and first.json()["has_key"] is True
        second = client.put("/api/ai/config", headers=HEADERS, json={**settings, **changed})
        assert second.status_code == 200, second.text
        assert second.json()["has_key"] is expected_key


def test_environment_key_is_scoped_to_startup_endpoint_and_clear_masks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REACHSCOPE_AI_API_KEY", "environment-for-startup-only")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/ai/config").json()["credential_source"] == "environment"
        cleared = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": False, "provider_id": "openai_compatible", "base_url": "https://api.openai.com/v1",
            "model": "example", "clear_key": True,
        })
        assert cleared.status_code == 200 and cleared.json()["has_key"] is False
    with TestClient(create_app(tmp_path)) as client:
        changed = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash",
        })
        assert changed.status_code == 200 and changed.json()["has_key"] is False
        replacement = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash",
            "api_key": "new-explicit-deepseek-key",
        })
        assert replacement.status_code == 200 and replacement.json()["credential_source"] == "session"


@pytest.mark.parametrize("change", [{"reasoning_effort": "xhigh"}, {"token_limit_field": "max_completion_tokens"}])
def test_deepseek_rejects_incompatible_gpt_options(tmp_path: Path, change: dict[str, str]) -> None:
    with TestClient(create_app(tmp_path)) as client:
        result = client.put("/api/ai/config", headers=HEADERS, json={
            "enabled": True, "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash", **change,
        })
        assert result.status_code == 400 and result.json()["error"]["code"] == "AI_INVALID_CONFIG"


async def test_diagnostic_dns_failure_returns_bounded_safe_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_args: Any) -> list[str]:
        raise WorkbenchError("AI_NETWORK_ERROR", "untrusted resolver details")

    monkeypatch.setattr(ai_provider, "_addresses", fail)
    result = await ai_provider.diagnose_endpoint({"base_url": "https://api.example.invalid/v1"})
    assert result["status"] == "unreachable" and result["error_code"] == "dns_failed"
    assert "untrusted resolver details" not in str(result)


async def test_diagnostic_deadline_includes_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stall(*_args: Any) -> list[str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(ai_provider, "_addresses", stall)
    monkeypatch.setattr(ai_provider, "_DIAGNOSTIC_TIMEOUT", 0.01)
    result = await asyncio.wait_for(ai_provider.diagnose_endpoint({"base_url": "https://api.example.invalid/v1"}), 1)
    assert result["status"] == "unreachable" and result["error_code"] == "timeout" and result["stage"] == "dns"


async def test_shutdown_waits_for_durable_acceptance_before_cancelling_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(tmp_path, advisory_provider=NoCallProvider())
    service = app.state.advisory
    job = service.jobs.create("web", "fixture", {"mode": "probe"})
    entered, release = threading.Event(), threading.Event()
    reserve = service.records.reserve

    def gated_reserve(*args: Any) -> dict[str, Any]:
        entered.set()
        if not release.wait(3):
            raise AssertionError("test release was not signalled")
        result: dict[str, Any] = reserve(*args)
        return result

    async def preview(_job: str) -> dict[str, Any]:
        return {"eligible": True, "context_sha256": "a" * 64, "context": {}, "controls": [], "disclosure": {}}

    monkeypatch.setattr(service.records, "reserve", gated_reserve)
    monkeypatch.setattr(service, "preview", preview)
    await service.start()
    await service.configure({"enabled": True, "provider_id": "custom", "base_url": "https://fixture.example.invalid/v1",
                             "model": "fixture", "reasoning_effort": "default", "allow_local": False}, key="fixture-key")
    submitted = asyncio.create_task(service.submit(job["id"], "a" * 64, True, "local test", "shutdown-race"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        stopped = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        assert not stopped.done(), "shutdown must wait for the in-flight durable reservation"
        release.set()
        accepted = await asyncio.wait_for(submitted, 3)
        await asyncio.wait_for(stopped, 3)
        assert not service.started and not service.tasks
        assert service.records.get(accepted["id"])["status"] in {"interrupted", "failed"}
        assert service.records.list(job["id"])["total"] == 1
    finally:
        release.set()
        await service.stop()


async def test_cancelled_configure_finishes_accepted_settings_and_key_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = create_app(tmp_path).state.advisory
    entered, release = threading.Event(), threading.Event()
    save = service.records.save_settings

    def gated_save(settings: dict[str, Any]) -> None:
        entered.set()
        if not release.wait(3):
            raise AssertionError("test release was not signalled")
        save(settings)

    monkeypatch.setattr(service.records, "save_settings", gated_save)
    task = asyncio.create_task(service.configure({
        "enabled": True, "provider_id": "custom", "base_url": "https://new.example.invalid/v1",
        "model": "fixture", "reasoning_effort": "default", "allow_local": False,
    }, key="new-explicit-key"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.settings == service.records.settings()
        assert service.config()["has_key"] is True
        assert "new-explicit-key" not in str(service.records.settings())
    finally:
        release.set()
        await service.stop()


def test_advisory_history_rejects_sqlite_integer_overflow(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    job = app.state.repository.create("web", "fixture", {"mode": "probe"})
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job['id']}/advisories?offset={2 ** 63}")
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_PAGE"


def test_legacy_configuration_does_not_reset_existing_profile_or_budget(tmp_path: Path) -> None:
    settings = {"enabled": True, "provider_id": "openai_compatible", "base_url": "https://proxy.example.invalid/v1",
                "model": "explicit-gpt-model", "reasoning_effort": "max", "token_limit_field": "max_completion_tokens"}
    with TestClient(create_app(tmp_path)) as client:
        first = client.put("/api/ai/config", headers=HEADERS, json={**settings, "api_key": "profile-scoped-key"})
        assert first.status_code == 200, first.text
        legacy = client.put("/api/ai/config", headers=HEADERS, json={
            name: value for name, value in settings.items() if name not in {"provider_id", "token_limit_field"}
        })
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["provider_id"] == "openai_compatible"
        assert legacy.json()["token_limit_field"] == "max_completion_tokens"
        assert legacy.json()["reasoning_effort"] == "max"
        assert legacy.json()["has_key"] is True

