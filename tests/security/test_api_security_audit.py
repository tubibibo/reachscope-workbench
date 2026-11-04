"""Security regressions use temporary workspaces and local protocol fixtures only."""

from __future__ import annotations

import logging
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.integrations.ai_provider import ChatCompletionsProvider, diagnose_models
from reachscope_workbench.modules.web import probe as probe_module
from reachscope_workbench.modules.web import scope as scope_module


@pytest.mark.parametrize("suffix", ["%0aCRITICAL%20forged_security_event", "%0dforged", "%1b%5b31mforged", "%E2%80%AEforged"])
def test_sec_api_01_untrusted_paths_cannot_forge_application_log_records(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                                     suffix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REACHSCOPE_AI_API_KEY", raising=False)
    caplog.set_level(logging.INFO, logger="reachscope_workbench.api.app")
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/no-such-route/" + suffix)
        assert response.status_code == 404
    entries = [record.getMessage() for record in caplog.records
               if record.name == "reachscope_workbench.api.app" and record.getMessage().startswith("request_completed")]
    assert len(entries) == 1
    assert all(ord(char) >= 32 and ord(char) < 127 for char in entries[0]), entries[0]
    assert response.headers["X-Request-ID"] in entries[0]


@contextmanager
def redirecting_provider():
    """Two loopback peers expose actual credential-forwarding, without AI."""
    source_requests: list[dict[str, str | None]] = []
    destination_requests: list[str] = []

    class Sink(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            destination_requests.append(self.command)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *_args: Any) -> None:
            pass

    sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            source_requests.append({"method": self.command, "path": self.path, "authorization": self.headers.get("Authorization")})
            if self.command == "POST":
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(307)
            self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/must-not-receive-a-key")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *_args: Any) -> None:
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threads = [threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
               for server in (provider, sink)]
    for thread in threads:
        thread.start()
    try:
        yield f"http://127.0.0.1:{provider.server_port}/v1", source_requests, destination_requests
    finally:
        for server in (provider, sink):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["consult", "models"])
async def test_provider_credential_redirects_are_rejected_on_real_loopback_wire(operation: str) -> None:
    # This is a negative security-control verification, not an additional finding.
    with redirecting_provider() as (base, source_requests, destination_requests):
        settings = {"provider_id": "custom", "base_url": base, "allow_local": True, "model": "fixture-model",
                    "reasoning_effort": "default", "token_limit_field": "max_tokens"}
        if operation == "consult":
            with pytest.raises(WorkbenchError) as failure:
                await ChatCompletionsProvider().consult(settings, "fixture-only-credential", {}, [])
            assert failure.value.code == "AI_PROVIDER_ERROR"
        else:
            response = await diagnose_models(settings, "fixture-only-credential")
            assert response["status"] == "redirect_blocked" and response["authentication"] == "unknown"
        assert source_requests == [{"method": "POST" if operation == "consult" else "GET",
                                    "path": "/v1/chat/completions" if operation == "consult" else "/v1/models",
                                    "authorization": "Bearer fixture-only-credential"}]
        assert destination_requests == []


@pytest.mark.asyncio
async def test_same_host_redirect_revalidates_dns_and_never_requests_rebound_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    # DNS and the public response are local fixtures; neither IP is contacted.
    dns_calls: list[str] = []
    requests: list[httpx.Request] = []
    original_client = httpx.AsyncClient

    def resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        dns_calls.append(host)
        address = "93.184.216.34" if len(dns_calls) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": "/private-after-rebind"}, stream=httpx.ByteStream(b""))

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["verify"] is True
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(scope_module.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(probe_module.httpx, "AsyncClient", client)
    result = await probe_module.probe_url("https://rebind.example.invalid/", allow_private=False, timeout=2)
    assert dns_calls == ["rebind.example.invalid", "rebind.example.invalid"]
    assert not result["reachable"] and result["error"]["code"] == "OUT_OF_SCOPE"
    assert len(requests) == 1 and requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["Host"] == "rebind.example.invalid"
