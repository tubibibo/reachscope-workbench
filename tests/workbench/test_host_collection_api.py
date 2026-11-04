"""Real collector downloads and v2 uploads, never server-side capture execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.registry import ModuleRegistry

HEADERS = {"X-ReachScope-Client": "workbench"}


def document(*, failed: bool = False) -> dict[str, Any]:
    components = {key: {"state": "collected", "complete": True, "exit_code": 0, "reason_code": "ok"} for key in ("ssh", "nginx")}
    if failed:
        components["nginx"] = {"state": "unavailable", "complete": False, "exit_code": None, "reason_code": "missing_executable"}
    return {"schema_version": "reachscope-host/2", "host_id": "api-v2-host", "collected_at": "2026-11-02T00:00:00Z",
            "collector": {"version": "0.14.0", "projection": "reachscope-minimal/1", "plan_sha256": "a" * 64, "components": components},
            "ssh": {"effective_config": "permitrootlogin yes\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n", "connection_context": "global"},
            "nginx": {"config_dump": "http { autoindex off; server_tokens off; server { listen 80; server_name alias.invalid; } }"}}


def upload(client: TestClient, value: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/uploads", files={"file": ("host-snapshot.json", json.dumps(value).encode())}, headers=HEADERS)
    assert response.status_code == 201
    file = response.json()
    response = client.post("/api/assets", json={"kind": "host", "name": "Operator v2 input", "source": {
        "profile_id": "host-baseline", "mode": "baseline", "host_id": "api-v2-host", "upload_id": file["id"], "filename": file["filename"]}}, headers=HEADERS)
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def test_artifact_downloads_are_reviewable_deterministic_and_never_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.collectors.host import collector

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("HTTP request tried to collect host data")

    monkeypatch.setattr(collector, "collect_snapshot", forbidden)
    with TestClient(create_app(tmp_path / "workspace")) as client:
        one, two = client.get("/api/host/collector"), client.get("/api/host/collector/source")
        assert one.status_code == two.status_code == 200
        assert one.content == two.content == client.get("/api/host/collector").content
        assert one.headers["x-content-sha256"] == hashlib.sha256(one.content).hexdigest()
        assert one.headers["content-disposition"].endswith('.pyz"')
        assert two.headers["content-disposition"].endswith('.zip"')
        with zipfile.ZipFile(io.BytesIO(one.content)) as archive:
            paths = archive.namelist()
            assert "__main__.py" in paths and all(".." not in path.split("/") for path in paths)
            assert not any("core/" in path or "api/" in path or "node_modules" in path for path in paths)
        assert client.get("/api/jobs").json()["total"] == 0
        assert client.get("/api/assets").json()["total"] == 0
    bundle = tmp_path / "reachscope-host-collector.pyz"
    bundle.write_bytes(one.content)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH" and not key.startswith("REACHSCOPE_AI_")}
    result = subprocess.run([sys.executable, "-I", str(bundle), "--host-id", "preview-host", "--ssh-context", "global",
                             "--output", str(tmp_path / "snapshot.json")],
                            cwd=tmp_path, capture_output=True, check=False, timeout=10, env=env)
    assert result.returncode == 0, "Standalone plan failed (raw output deliberately not echoed)"
    plan = json.loads(result.stdout)
    assert "plan_sha256" in plan
    assert not list(tmp_path.glob("*.json")), "Preview unexpectedly wrote output"


def test_disabled_host_module_has_no_collector_or_template_side_effects(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, registry=ModuleRegistry([]))) as client:
        for path in ("/api/host/template", "/api/host/collector", "/api/host/collector/source"):
            response = client.get(path)
            assert response.status_code in {400, 404}
            assert response.json()["error"]["code"] == "MODULE_NOT_FOUND"


@pytest.mark.parametrize("failed", [False, True])
def test_actual_v2_file_preview_and_selected_job_keep_capture_metadata(tmp_path: Path, failed: bool) -> None:
    with TestClient(create_app(tmp_path)) as client:
        asset = upload(client, document(failed=failed))
        endpoint = "/api/assets/" + asset["id"]
        preview = client.post(endpoint + "/preflight", json={"checks": ["ssh", "nginx"]}, headers=HEADERS)
        assert preview.status_code == 200
        capture = preview.json()["input_preview"]["collection_metadata"]
        assert capture["format_version"] == 2 and capture["components"]["nginx"]["complete"] is not failed
        assert client.get("/api/jobs").json()["total"] == 0
        response = client.post(endpoint + "/inspections", json={"checks": ["ssh", "nginx"]}, headers=HEADERS)
        assert response.status_code == 201
        job = response.json()
        until = time.monotonic() + 10
        while job["status"] in {"queued", "running"} and time.monotonic() < until:
            time.sleep(.02)
            job = client.get("/api/jobs/" + job["id"]).json()
        assert job["status"] == "completed"
        details = job["result"]["details"]
        assert details["collection_metadata"] == capture
        assert details["live_state_verified"] is False
        if failed:
            assert all(row["status"] == "unknown" for row in details["checks"] if row["id"].startswith("host.nginx."))
        assert client.get("/api/jobs/" + job["id"] + "/advisory/preview").json()["eligible"] is False
