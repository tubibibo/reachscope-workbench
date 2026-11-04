"""HTTP acceptance with actual modules and a local-only probe server."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app

HEADERS = {"X-ReachScope-Client": "workbench"}


def wait_job(client: TestClient, job_id: str, timeout: float = 25) -> dict[str, Any]:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job: dict[str, Any] = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(.05)
    raise AssertionError("Task did not finish")


def submit(client: TestClient, module: str, config: dict[str, Any]) -> str:
    response = client.post("/api/jobs", json={"module": module, "name": "API acceptance", "config": config}, headers=HEADERS)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_android_end_to_end_query_export_and_restart(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["modules"] == 4
        assert {item["id"] for item in client.get("/api/modules").json()["items"]} == {"android", "web", "cloud", "host"}
        job_id = submit(client, "android", {"mode": "demo", "sample": "cross_component"})
        job = wait_job(client, job_id)
        assert job["status"] == "completed", job
        assert job["result"]["summary"]["chains"] >= 1
        methods = client.get(f"/api/jobs/{job_id}/methods", params={"search": "CrossTarget"})
        assert methods.status_code == 200, methods.text
        ref = methods.json()["data"][0]["method_ref"]
        code = client.get(f"/api/jobs/{job_id}/method", params={"ref": ref}).json()["data"]["code"]
        assert "getStringExtra" in code and "loadUrl" in code
        exported = client.get(f"/api/jobs/{job_id}/export?format=json")
        assert exported.status_code == 200
        assert exported.json()["result"]["module"] == "android"
        html = client.get(f"/api/jobs/{job_id}/export?format=html")
        assert html.status_code == 200 and "text/html" in html.headers["content-type"]
        evidence_id = job["result"]["evidence"][0]["id"]
        assert client.get(f"/api/jobs/{job_id}/evidence/{evidence_id}").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/events").json()["items"]
        assert client.post(f"/api/jobs/{job_id}/cancel", headers=HEADERS).status_code == 409
    with TestClient(create_app(tmp_path)) as reopened:
        assert reopened.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
        assert reopened.get("/api/jobs?module=android").json()["total"] == 1


def test_local_boundary_validation_and_upload(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/jobs", json={}).status_code == 403
        assert client.post("/api/jobs", json={}, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert client.post("/api/jobs", json={}, headers=HEADERS).status_code == 422
        assert client.post("/api/jobs", content=b"x" * 140000, headers=HEADERS).status_code == 413
        streamed = client.post("/api/jobs", content=iter([b"x" * 100000, b"x" * 50000]),
                               headers={**HEADERS, "Content-Type": "application/json"})
        assert streamed.status_code == 413 and streamed.json()["error"]["code"] == "REQUEST_LIMIT"
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/api/jobs/../oops").status_code == 404
        assert client.get("/api/jobs/not-valid").status_code == 400
        assert client.get("/api/jobs?limit=1000").status_code == 400
        bad = client.post("/api/uploads", files={"file": ("evil.exe", b"data")}, headers=HEADERS)
        assert bad.status_code == 400
        empty = client.post("/api/uploads", files={"file": ("assets.json", b"")}, headers=HEADERS)
        assert empty.status_code == 400
        uploaded = client.post("/api/uploads", files={"file": ("assets.json", b'[{"host":"test.example","title":"Swagger UI"}]')}, headers=HEADERS)
        assert uploaded.status_code == 201, uploaded.text
        stored = uploaded.json()
        assert (tmp_path / "uploads" / stored["id"]).is_file()
        job_id = submit(client, "web", {"mode": "import", "upload_id": stored["id"], "filename": stored["filename"]})
        job = wait_job(client, job_id)
        assert job["status"] == "completed", job
        assert job["result"]["summary"]["assets"] == 1
        assert "application/json" in client.get(f"/api/jobs/{job_id}/export").headers["content-type"]


def test_web_probe_real_loopback_and_failed_upload(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'<html><title>Workbench &lt;safe&gt;</title><body>local test</body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = f"http://127.0.0.1:{server.server_port}/"
        with TestClient(create_app(tmp_path)) as client:
            job_id = submit(client, "web", {"mode": "probe", "targets": [target], "allow_private": True})
            job = wait_job(client, job_id)
            assert job["status"] == "completed", job
            assert job["result"]["details"]["assets"][0]["status_code"] == 200
            assert job["result"]["summary"]["online"] == 1
            upload = client.post("/api/uploads", files={"file": ("broken.apk", b"not a zip")}, headers=HEADERS).json()
            apk = submit(client, "android", {"mode": "apk", "upload_id": upload["id"]})
            failed = wait_job(client, apk)
            assert failed["status"] == "failed" and failed["error"]["code"] == "INVALID_APK"
            assert client.get(f"/api/jobs/{apk}/export").status_code == 409
    finally:
        server.shutdown()
        server.server_close()


def test_html_export_escapes_external_titles(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        uploaded = client.post("/api/uploads", files={"file": ("assets.json", json.dumps([
            {"host": "example.test", "title": '<script>alert("xss")</script>'}
        ]).encode())}, headers=HEADERS).json()
        job_id = submit(client, "web", {"mode": "import", "upload_id": uploaded["id"], "filename": "assets.json"})
        assert wait_job(client, job_id)["status"] == "completed"
        report = client.get(f"/api/jobs/{job_id}/export?format=html").text
        assert '<script>alert("xss")</script>' not in report
        assert "\\u003cscript\\u003e" in report or "&lt;script&gt;" in report
