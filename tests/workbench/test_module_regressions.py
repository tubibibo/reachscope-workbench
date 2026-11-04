"""Boundary regressions from the real-input review; all active targets are loopback."""

from __future__ import annotations

import asyncio
import gzip
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.android import AndroidModule
from reachscope_workbench.modules.cloud import CloudModule
from reachscope_workbench.modules.cloud.input import parse_input
from reachscope_workbench.modules.web import WebModule
from reachscope_workbench.modules.web.audit import audit_response
from reachscope_workbench.modules.web.importer import parse_import
from reachscope_workbench.modules.web.probe import probe_url
from reachscope_workbench.modules.web.scope import normalize_url


@pytest.mark.parametrize("module", [AndroidModule(), WebModule(), CloudModule()])
@pytest.mark.parametrize("value", [{}, [], 1, True, None])
def test_bad_mode_types_are_domain_errors(module: Any, value: Any) -> None:
    with pytest.raises(WorkbenchError) as error:
        module.validate({"mode": value})
    assert error.value.code == "INVALID_CONFIG"


@pytest.mark.parametrize("value", ["\u00b200", "999", "200x", "2" * 10000, {}, [], True])
def test_bad_imported_http_status_does_not_discard_usable_assets(value: Any) -> None:
    assets, records, warnings = parse_import(json.dumps([
        {"host": "first.example", "status_code": value},
        {"host": "second.example", "status_code": "204"},
    ]).encode(), "assets.json")
    assert len(assets) == len(records) == 2
    assert records[0]["status_code"] is None and not records[0]["reachable"]
    assert records[1]["status_code"] == 204 and warnings == [
        "Record 1: invalid HTTP status; preserved asset without a historical response status",
    ]


@pytest.mark.parametrize("payload", [
    b'{"host":"one.test","host":"other.test"}',
    b'{"host":"one.test","status_code":NaN}',
    b'{"host":"one.test","title":"\\ud800"}',
    b'{"host":"one.test","\\udfff":"value"}',
])
@pytest.mark.parametrize("filename", ["assets.json", "assets.jsonl"])
def test_ambiguous_or_unsavable_imports_have_structured_errors(payload: bytes, filename: str) -> None:
    with pytest.raises(WorkbenchError) as error:
        parse_import(payload, filename)
    assert error.value.code == "INVALID_IMPORT"


def test_excessively_nested_import_is_bounded_before_stringifying_fields() -> None:
    nested: Any = "value"
    for _ in range(40):
        nested = {"child": nested}
    with pytest.raises(WorkbenchError) as error:
        parse_import(json.dumps({"host": "one.test", "title": nested}).encode(), "assets.json")
    assert error.value.code == "IMPORT_LIMIT"


@pytest.mark.parametrize("url", ["https://example.test/\ud800", "https://example.test/?q=\udfff"])
def test_invalid_unicode_url_is_rejected_before_storage_or_network(url: str) -> None:
    with pytest.raises(WorkbenchError) as error:
        normalize_url(url)
    assert error.value.code == "INVALID_TARGET"
    assert normalize_url("https://example.test/\U0001f4c4") == "https://example.test/\U0001f4c4"


@pytest.mark.parametrize("url", ["http://./", "https://.../", "http://example.test/\x7f"])
def test_normalization_never_produces_an_empty_host_or_accepts_del(url: str) -> None:
    with pytest.raises(WorkbenchError) as error:
        normalize_url(url)
    assert error.value.code == "INVALID_TARGET"


@pytest.mark.parametrize("field", ["value", "key"])
def test_cloud_invalid_unicode_is_not_left_for_sqlite_encoding_to_fail(field: str) -> None:
    document = {"Statement": [], "ignored_field": "\ud800"} if field == "value" else {"Statement": [], "\udfff": "text"}
    with pytest.raises(WorkbenchError) as error:
        parse_input(json.dumps(document).encode())
    assert error.value.code == "INVALID_CLOUD_INPUT"


@pytest.mark.parametrize("statement", [[], [{"Effect": "Allow", "Action": "*", "Resource": "*"}]])
def test_standalone_iam_evidence_pointer_resolves_to_uploaded_document(statement: Any) -> None:
    policy = {"Version": "2012-10-17", "Statement": statement}
    result = CloudModule._analyze(json.dumps(policy).encode(), {"mode": "import", "checks": ["iam"]}, "policy.json")
    assert result.details["resources"][0]["source_pointer"] == ""
    assert result.details["checks"][0]["evidence"]["pointer"] == ""
    assert result.evidence[0].data["pointer"] == ""


@pytest.fixture
def edge_http() -> Iterator[tuple[str, list[str]]]:
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            visited.append(self.path)
            if self.path == "/long-location":
                self.send_response(302)
                self.send_header("Location", "/" + "x" * 5000)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"<html><title>Boundary response</title></html>"
            if self.path == "/compressed":
                body = gzip.compress(body)
            self.send_response(200)
            charset = "base64_codec" if self.path == "/bad-charset" else "utf-8"
            self.send_header("Content-Type", "text/html; charset=" + charset)
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
            self.send_header("Content-Security-Policy-Report-Only", "script-src 'none'")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            if self.path == "/compressed":
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body) + (100 if self.path == "/incomplete" else 0)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
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


def test_redirect_prefix_is_never_followed_as_an_invented_destination(edge_http: tuple[str, list[str]]) -> None:
    base, visited = edge_http
    result = asyncio.run(probe_url(base + "/long-location", allow_private=True, timeout=3))
    assert result["reachable"] and result["status_code"] == 302
    assert result["redirect_stopped"] == "location_truncated"
    assert result["headers_truncated"] == ["location"] and result["redirects"] == []
    assert visited == ["/long-location"]


def test_compressed_html_keeps_header_review_independent_from_page_decoding(edge_http: tuple[str, list[str]]) -> None:
    base, _ = edge_http
    with_page = asyncio.run(probe_url(base + "/compressed", allow_private=True, timeout=3))
    headers_only = asyncio.run(probe_url(base + "/compressed", allow_private=True, timeout=3, checks=["http", "headers"]))
    assert with_page["reachable"] and not with_page["page"]["analyzed"]
    left = {item["id"]: item for item in with_page["checks"]}
    right = {item["id"]: item for item in headers_only["checks"]}
    for rule in ("csp", "frame_protection", "referrer_policy"):
        assert left[rule]["status"] == right[rule]["status"] == "pass"
    assert left["csp"]["evidence"]["report_only_present"] is True
    assert left["password_forms"]["status"] == "not_applicable"
    json_result = audit_response({"reachable": True, "content_type": "application/json", "page": {"analyzed": False}})
    assert next(row for row in json_result if row["id"] == "csp")["status"] == "not_applicable"


def test_nontext_charset_does_not_turn_a_real_response_into_a_connection_error(edge_http: tuple[str, list[str]]) -> None:
    base, _ = edge_http
    result = asyncio.run(probe_url(base + "/bad-charset", allow_private=True, timeout=3))
    assert result["reachable"] and result["status_code"] == 200
    assert result["title"] == "Boundary response" and "Boundary response" in result["body_preview"]
    assert result["page"]["analyzed"]


def test_incomplete_response_body_is_a_visible_collection_failure(edge_http: tuple[str, list[str]]) -> None:
    base, visited = edge_http
    result = asyncio.run(probe_url(base + "/incomplete", allow_private=True, timeout=3))
    assert not result["reachable"] and result["error"]["code"] == "HTTP_ERROR"
    assert result["checks"][0]["id"] == "response_unavailable"
    assert visited == ["/incomplete"]
