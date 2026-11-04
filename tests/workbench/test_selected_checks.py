"""Selections control execution rather than hiding fields from a full analysis."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.modules.android import AndroidModule
from reachscope_workbench.modules.android import module as android
from reachscope_workbench.modules.android.manifest_worker import inspect_manifest
from reachscope_workbench.modules.web import WebModule
from reachscope_workbench.modules.web import audit as audit_module
from reachscope_workbench.modules.web import module as web
from reachscope_workbench.modules.web import probe as probe_module
from reachscope_workbench.modules.web.audit import audit_response
from reachscope_workbench.modules.web.comparison import compare_jobs


def context(tmp_path: Path) -> RunContext:
    uploads, workspace = tmp_path / "uploads", tmp_path / "job"
    uploads.mkdir(exist_ok=True)
    workspace.mkdir(exist_ok=True)
    return RunContext("selected", workspace, uploads, lambda *_: None)


def forbidden(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("An unselected analysis was executed")


@pytest.fixture
def local_page() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'<html><title>Swagger fixture</title><form><input name="password" type="password"></form><script src="/app.js"></script></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "session=DO_NOT_CAPTURE; HttpOnly; Secure; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("value", [[], "manifest", ["unknown"], [1], ["manifest"] * 3])
def test_android_rejects_invalid_check_selection(value: Any) -> None:
    with pytest.raises(WorkbenchError):
        AndroidModule().validate({"checks": value})


@pytest.mark.parametrize("value", [[], "http", ["unknown"], [1], ["http"] * 5])
def test_web_rejects_invalid_check_selection(value: Any) -> None:
    with pytest.raises(WorkbenchError):
        WebModule().validate({"mode": "probe", "targets": ["https://example.test/"], "checks": value})


def test_dependencies_are_normalized_and_offline_modes_do_not_accept_live_checks() -> None:
    assert AndroidModule().validate({"checks": ["code_paths"]})["checks"] == ["manifest", "code_paths"]
    assert AndroidModule().validate({"checks": ["manifest"]})["checks"] == ["manifest"]
    assert WebModule().validate({"mode": "probe", "targets": ["https://example.test/"], "checks": ["page"]})["checks"] == ["http", "page"]
    assert WebModule().validate({"mode": "demo"})["checks"] == ["fingerprints"]
    with pytest.raises(WorkbenchError):
        WebModule().validate({"mode": "demo", "checks": ["headers"]})
    with pytest.raises(WorkbenchError):
        WebModule().validate({"mode": "import", "checks": ["http"]})


@pytest.mark.asyncio
async def test_manifest_only_creates_real_configuration_without_code_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(android, "_assemble_result", forbidden)
    execution = context(tmp_path)
    result = await AndroidModule().run({"mode": "demo", "sample": "cross_component", "checks": ["manifest"]}, execution)
    assert result.summary["components"] == 2 and result.summary["deeplinks"] == 1
    assert result.summary["exported"] == 1
    assert "chains" not in result.summary and "methods" not in result.summary
    assert "artifact_id" not in result.details and not (execution.workspace / "artifacts").exists()
    assert result.details["query_operations"] == []
    assert all(item["impl_present"] is None for item in result.details["components"])
    assert result.evidence[0].sha256 and result.details["chains"] == []
    assert [item["status"] for item in result.details["execution"]] == ["completed", "skipped"]


def test_manifest_inspection_does_not_import_code_analyzer_and_bounds_input(tmp_path: Path) -> None:
    path = tmp_path / "AndroidManifest.xml"
    path.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="example.app">
      <uses-permission android:name="android.permission.CAMERA"/><application>
      <activity android:name=".Entry" android:exported="true"/>
      </application></manifest>''', encoding="utf-8")
    loaded = set(sys.modules)
    result = inspect_manifest(path)
    assert result["permissions"] == ["android.permission.CAMERA"]
    assert result["components"][0]["name"] == "example.app.Entry"
    assert not any(name.startswith("reachscope.graph") for name in set(sys.modules) - loaded)
    path.write_text('<!DOCTYPE a [<!ENTITY x "bad">]><manifest/>', encoding="utf-8")
    with pytest.raises(Exception, match="declarations"):
        inspect_manifest(path)


@pytest.mark.asyncio
async def test_http_only_does_not_run_parser_cookies_audit_or_fingerprint_rules(
    tmp_path: Path, local_page: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("page_inventory", "cookie_metadata", "audit_response", "html_title", "_tls_info"):
        monkeypatch.setattr(probe_module, name, forbidden)
    for name in ("classify_assets", "build_surfaces", "build_paths", "load_transition_rules"):
        monkeypatch.setattr(web, name, forbidden)
    result = await WebModule().run({"mode": "probe", "targets": [local_page], "allow_private": True, "checks": ["http"]}, context(tmp_path))
    record = result.details["assets"][0]
    assert record["status_code"] == 200 and record["title"] == ""
    assert not any(key in record for key in ("cookies", "page", "checks", "tls"))
    assert result.summary["checks"] == result.summary["paths"] == 0
    assert [item["status"] for item in result.details["execution"]] == ["completed", "skipped", "skipped", "skipped"]


@pytest.mark.asyncio
async def test_headers_only_checks_html_headers_without_parsing_forms_or_resources(
    tmp_path: Path, local_page: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe_module, "page_inventory", forbidden)
    monkeypatch.setattr(probe_module, "html_title", forbidden)
    monkeypatch.setattr(audit_module, "_page_checks", forbidden)
    monkeypatch.setattr(web, "classify_assets", forbidden)
    result = await WebModule().run({"mode": "probe", "targets": [local_page], "allow_private": True, "checks": ["headers"]}, context(tmp_path))
    record = result.details["assets"][0]
    ids = {check["id"] for check in record["checks"]}
    assert "csp" in ids and not ids & {"mixed_content", "password_forms"}
    assert "page" not in record and record["cookies"][0]["http_only"]
    assert "DO_NOT_CAPTURE" not in json.dumps(result.to_dict())


@pytest.mark.asyncio
async def test_page_only_does_not_run_header_or_cookie_rules(
    tmp_path: Path, local_page: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("cookie_metadata", "_tls_info"):
        monkeypatch.setattr(probe_module, name, forbidden)
    for name in ("_csp", "_cookies", "_hsts", "_cors", "_tls"):
        monkeypatch.setattr(audit_module, name, forbidden)
    monkeypatch.setattr(web, "classify_assets", forbidden)
    result = await WebModule().run({"mode": "probe", "targets": [local_page], "allow_private": True, "checks": ["page"]}, context(tmp_path))
    record = result.details["assets"][0]
    assert record["page"]["analyzed"] and record["page"]["counts"]["forms"] == 1
    assert {check["id"] for check in record["checks"]} == {"password_forms", "mixed_content"}
    assert "cookies" not in record and "tls" not in record


@pytest.mark.asyncio
async def test_fingerprint_only_retains_title_based_rules_without_page_or_configuration_audit(
    tmp_path: Path, local_page: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("page_inventory", "cookie_metadata", "audit_response"):
        monkeypatch.setattr(probe_module, name, forbidden)
    result = await WebModule().run({"mode": "probe", "targets": [local_page], "allow_private": True, "checks": ["fingerprints"]}, context(tmp_path))
    record = result.details["assets"][0]
    assert record["title"] == "Swagger fixture" and record["tech"] == "swagger"
    assert result.details["paths"] and result.summary["checks"] == 0


def test_no_audit_groups_has_no_evaluation() -> None:
    assert audit_response({}, groups=set()) == []


@pytest.mark.asyncio
async def test_failed_probe_marks_selected_execution_as_failed(tmp_path: Path) -> None:
    result = await WebModule().run({"mode": "probe", "targets": ["http://127.0.0.1:1/"], "checks": ["page"], "timeout": .2}, context(tmp_path))
    assert result.summary["errors"] == 1
    assert [row["status"] for row in result.details["execution"]] == ["failed", "skipped", "failed", "skipped"]


def test_comparison_does_not_interpret_unselected_fields_as_configuration_removal() -> None:
    old = {"url": "https://example.test/", "reachable": True, "title": "A page", "status_code": 200,
           "headers": {"content-security-policy": "default-src 'self'"}, "selected_checks": ["http", "headers", "page"]}
    new = {**old, "title": "", "headers": {}, "selected_checks": ["http"]}
    def job(identity: str, record: dict[str, Any]) -> dict[str, Any]:
        return {"id": identity, "status": "completed", "module": "web", "result": {
            "module": "web", "summary": {"mode": "probe"}, "details": {"assets": [record]}}}
    result = compare_jobs(job("old", old), job("new", new))
    assert result["summary"]["unchanged"] == 1
    assert any("检查项不同" in note for note in result["assets"][0]["notes"])
