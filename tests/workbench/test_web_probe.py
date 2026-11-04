"""Real local HTTP behavior plus scope/DNS checks; no external targets are contacted."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.modules.web import WebModule
from reachscope_workbench.modules.web import probe as probe_module
from reachscope_workbench.modules.web.probe import BODY_LIMIT, probe_url
from reachscope_workbench.modules.web.scope import (
    normalize_url,
    permitted_address,
    redirect_in_scope,
    resolve_target,
)


@pytest.fixture
def local_http() -> Iterator[tuple[str, list[str]]]:
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            visited.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/html")
                self.end_headers()
                return
            if self.path == "/outside":
                self.send_response(302)
                self.send_header("Location", "http://other.example/secret")
                self.end_headers()
                return
            if self.path == "/loop":
                self.send_response(302)
                self.send_header("Location", "/loop")
                self.end_headers()
                return
            if self.path == "/slow":
                time.sleep(0.6)
            body = b"z" * (BODY_LIMIT + 100) if self.path == "/large" else b"<html><title>Swagger &amp; Local</title>probe</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", visited
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_exact_url_real_get_and_bounded_evidence(local_http: tuple[str, list[str]]) -> None:
    base, visited = local_http
    result = asyncio.run(probe_url(base + "/html", allow_private=True, timeout=3))
    assert result["reachable"] and result["status_code"] == 200
    assert result["title"] == "Swagger & Local"
    assert result["ip"] == "127.0.0.1"
    assert result["body_sha256"] == hashlib.sha256(b"<html><title>Swagger &amp; Local</title>probe</html>").hexdigest()
    assert result["tls"] is None
    assert result["headers"]["x-content-type-options"] == "nosniff"
    assert visited == ["/html"]


def test_redirects_are_bounded_and_cross_host_not_contacted(local_http: tuple[str, list[str]]) -> None:
    base, visited = local_http
    same = asyncio.run(probe_url(base + "/redirect", allow_private=True, timeout=3))
    assert same["final_url"] == base + "/html"
    assert same["redirects"][0]["status_code"] == 302
    assert visited == ["/redirect", "/html"]
    visited.clear()
    outside = asyncio.run(probe_url(base + "/outside", allow_private=True, timeout=3))
    assert outside["redirect_stopped"] == "out_of_scope"
    assert visited == ["/outside"]
    visited.clear()
    loop = asyncio.run(probe_url(base + "/loop", allow_private=True, timeout=3))
    assert loop["redirect_stopped"] == "limit"
    assert len(visited) == 4


def test_large_response_is_prefix_and_timeout_is_visible(local_http: tuple[str, list[str]]) -> None:
    base, _ = local_http
    large = asyncio.run(probe_url(base + "/large", allow_private=True, timeout=3))
    assert large["body_bytes"] == BODY_LIMIT and large["body_truncated"]
    assert large["hash_scope"] == "captured_prefix"
    slow = asyncio.run(probe_url(base + "/slow", allow_private=True, timeout=0.2))
    assert not slow["reachable"]
    assert slow["error"]["code"] in {"TIMEOUT", "HTTP_ERROR"}


def test_private_default_does_not_send_request(local_http: tuple[str, list[str]]) -> None:
    base, visited = local_http
    result = asyncio.run(probe_url(base + "/html", allow_private=False, timeout=1))
    assert result["error"]["code"] == "OUT_OF_SCOPE"
    assert visited == []


@pytest.mark.parametrize("url", ["ftp://example.com", "file:///tmp/test", "http://u:p@example.com", "http://[::1", "http://example.com/a b", "http://metadata.google.internal/", "http://example.com:99999"])
def test_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(WorkbenchError):
        normalize_url(url)


def test_scope_includes_port_and_metadata_is_never_allowed() -> None:
    assert normalize_url("HTTPS://Example.COM./a#fragment") == "https://example.com/a"
    assert redirect_in_scope("http://example.com/", "https://example.com/")
    assert not redirect_in_scope("http://example.com/", "http://example.com:8080/")
    assert not redirect_in_scope("https://example.com/", "http://example.com/")
    assert not permitted_address("169.254.169.254", True)
    assert not permitted_address("::ffff:169.254.169.254", True)
    assert not permitted_address("100.100.100.200", True)
    assert not permitted_address("224.0.0.1", True)
    assert not permitted_address("0.0.0.0", True)
    assert permitted_address("127.0.0.1", True)
    assert not permitted_address("127.0.0.1", False)
    assert permitted_address("8.8.8.8", False)


def test_dns_pins_checked_address_and_retains_host_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    dns_calls = 0
    original_client = httpx.AsyncClient

    async def resolver(url: str, allow_private: bool, timeout: float) -> list[str]:
        nonlocal dns_calls
        dns_calls += 1
        return ["93.184.216.34"]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"<title>local mock</title>"

        return httpx.Response(200, headers={"Content-Type": "text/html"}, stream=Body())

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["verify"] is True
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(probe_module, "resolve_target", resolver)
    monkeypatch.setattr(probe_module.httpx, "AsyncClient", client)
    result = asyncio.run(probe_url("https://example.com/test", allow_private=False, timeout=2))
    assert result["reachable"]
    assert dns_calls == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].extensions["sni_hostname"] == "example.com"


def test_mixed_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
    ])
    with pytest.raises(WorkbenchError, match="network scope"):
        asyncio.run(resolve_target("https://example.com", False, 1))


def test_web_module_real_probe_has_observations_and_progress(
    tmp_path: Path, local_http: tuple[str, list[str]],
) -> None:
    base, _ = local_http
    progress: list[int] = []
    result = asyncio.run(WebModule().run(
        {"mode": "probe", "targets": [base + "/html"], "allow_private": True},
        RunContext("test", tmp_path, tmp_path, lambda percent, message: progress.append(percent)),
    ))
    assert result.summary["online"] == result.summary["assets"] == 1
    assert result.details["assets"][0]["tech"] == "swagger"
    assert {item.category for item in result.observations} >= {"security_headers", "cleartext_http", "fingerprint"}
    assert any("候选" in path["interpretation"] or "调查" in path["interpretation"] for path in result.details["paths"])
    ids = {item.id for item in result.evidence}
    assert all(set(item.evidence_ids) <= ids for item in result.observations)
    assert progress[0] == 5 and progress[-1] == 100
    json.dumps(result.to_dict())


def test_cancellation_propagates() -> None:
    entered, release = threading.Event(), threading.Event()

    class WaitingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            entered.set()
            # Synchronize the actual pending I/O rather than racing a short sleep
            # against certificate/context setup and Windows scheduler load.
            release.wait(timeout=5)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), WaitingHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    async def cancel() -> None:
        task = asyncio.create_task(probe_url(f"http://127.0.0.1:{server.server_port}/", allow_private=True, timeout=4))
        try:
            assert await asyncio.to_thread(entered.wait, 3), "The real request did not reach the fixture"
            assert not task.done(), "Expected a pending response read"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(cancel())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
