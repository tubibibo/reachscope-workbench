"""Real saved-asset workflow, prerequisite failures and response-loss retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app

HEADERS = {"X-ReachScope-Client": "workbench"}


def asset(client: TestClient, *, key: str | None = None) -> dict[str, Any]:
    response = client.post("/api/assets", json={"kind": "cloud", "name": "Saved cloud sample",
                                               "source": {"profile_id": "cloud-demo", "mode": "demo"}},
                           headers={**HEADERS, **({"Idempotency-Key": key} if key else {})})
    assert response.status_code == 201, response.text
    return response.json()


def wait(client: TestClient, identifier: str) -> dict[str, Any]:
    until = time.monotonic() + 15
    while time.monotonic() < until:
        result: dict[str, Any] = client.get("/api/jobs/" + identifier).json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(.03)
    raise AssertionError("Job did not reach a terminal state")


def test_preflight_does_not_create_task_and_inspection_uses_saved_input(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = asset(client)
        preview = client.post(f"/api/assets/{saved['id']}/preflight", json={"checks": ["network"]}, headers=HEADERS)
        assert preview.status_code == 200
        result = preview.json()
        assert result["ready"] and result["network"] is False and result["module"] == "cloud"
        assert result["scope"]["selected_checks"] == [{"id": "network", "label": "网络访问规则"}]
        assert client.get("/api/jobs").json()["total"] == 0
        inspected = client.post(f"/api/assets/{saved['id']}/inspections", json={"checks": ["network"]}, headers=HEADERS)
        assert inspected.status_code == 201, inspected.text
        finished = wait(client, inspected.json()["id"])
        assert finished["status"] == "completed" and finished["asset_id"] == saved["id"]
        assert finished["config"]["checks"] == ["network"]
        assert next(row for row in finished["result"]["details"]["execution"] if row["id"] == "iam")["status"] == "skipped"


def test_asset_and_job_requests_replay_across_server_restart(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = asset(client, key="asset-attempt")
        assert asset(client, key="asset-attempt")["id"] == saved["id"]
        assert client.get("/api/assets").json()["total"] == 1
        endpoint = f"/api/assets/{saved['id']}/inspections"
        headers = {**HEADERS, "Idempotency-Key": "inspection-attempt"}
        payload = {"checks": ["network"], "name": "A precise inspection"}
        first = client.post(endpoint, json=payload, headers=headers)
        assert first.status_code == 201, first.text
        identifier = first.json()["id"]
        assert client.post(endpoint, json=payload, headers=headers).json()["id"] == identifier
        assert client.get("/api/jobs").json()["total"] == 1
        conflict = client.post(endpoint, json={**payload, "checks": ["iam"]}, headers=headers)
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        assert conflict.json()["error"]["request_id"] == conflict.headers["x-request-id"]
        assert wait(client, identifier)["status"] == "completed"
        retry_headers = {**HEADERS, "Idempotency-Key": "retry-attempt"}
        retried = client.post(f"/api/jobs/{identifier}/retry", headers=retry_headers)
        assert retried.status_code == 201
        assert client.post(f"/api/jobs/{identifier}/retry", headers=retry_headers).json()["id"] == retried.json()["id"]
        assert client.get("/api/jobs").json()["total"] == 2
    with TestClient(create_app(tmp_path)) as reopened:
        assert asset(reopened, key="asset-attempt")["id"] == saved["id"]
        assert reopened.post(endpoint, json=payload, headers=headers).json()["id"] == identifier
        assert reopened.get("/api/jobs").json()["total"] == 2


def test_deleted_and_changed_upload_block_new_run_but_do_not_break_replay(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        data = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}).encode()
        uploaded = client.post("/api/uploads", files={"file": ("policy.json", data)}, headers=HEADERS).json()
        response = client.post("/api/assets", json={"kind": "cloud", "name": "Uploaded policy", "source": {
            "profile_id": "cloud-config", "mode": "import", "upload_id": uploaded["id"], "filename": uploaded["filename"]}}, headers=HEADERS)
        assert response.status_code == 201, response.text
        saved = response.json()
        endpoint = f"/api/assets/{saved['id']}/inspections"
        preview = f"/api/assets/{saved['id']}/preflight"
        headers = {**HEADERS, "Idempotency-Key": "file-inspection"}
        first = client.post(endpoint, json={"checks": ["iam"]}, headers=headers)
        assert first.status_code == 201, first.text
        assert wait(client, first.json()["id"])["status"] == "completed"
        path = tmp_path / "uploads" / uploaded["id"]
        path.write_bytes(data.replace(b"Allow", b"Deny "))
        blocked = client.post(preview, json={"checks": ["iam"]}, headers=HEADERS).json()
        assert not blocked["ready"] and next(row for row in blocked["items"] if row["id"] == "upload")["status"] == "blocked"
        # Same size but different contents must be caught by hash validation.
        assert path.stat().st_size == len(data) and hashlib.sha256(path.read_bytes()).hexdigest() != uploaded["sha256"]
        response = client.post(endpoint, json={"checks": ["iam"]}, headers=HEADERS)
        assert response.status_code == 409 and response.json()["error"]["code"] == "PREFLIGHT_BLOCKED"
        path.unlink()
        assert client.post(endpoint, json={"checks": ["iam"]}, headers=headers).json()["id"] == first.json()["id"]
        assert client.get("/api/jobs").json()["total"] == 1


def test_apk_environment_preflight_is_local_and_blocked_without_decoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.core import inspections

    monkeypatch.setattr(inspections.shutil, "which", lambda _: None)
    monkeypatch.delenv("APKTOOL_JAR", raising=False)
    with TestClient(create_app(tmp_path)) as client:
        uploaded = client.post("/api/uploads", files={"file": ("example.apk", b"not-decoded-yet")}, headers=HEADERS).json()
        saved = client.post("/api/assets", json={"kind": "android", "name": "APK", "source": {
            "profile_id": "android-apk", "mode": "apk", "upload_id": uploaded["id"], "filename": uploaded["filename"]}}, headers=HEADERS).json()
        result = client.post(f"/api/assets/{saved['id']}/preflight", json={"checks": ["manifest"]}, headers=HEADERS).json()
        assert not result["ready"]
        assert {row["id"] for row in result["items"] if row["status"] == "blocked"} == {"java", "decoder"}
        assert client.get("/api/jobs").json()["total"] == 0


@pytest.mark.parametrize("payload", [{"checks": []}, {"checks": ["unknown"]},
                                     {"checks": ["network"], "options": {"timeout": 2}},
                                     {"checks": ["network"], "options": {"credentials": "not-allowed"}},
                                     {"checks": ["network"], "module": "web"}])
def test_inspection_contract_rejects_unsupported_fields_without_tasks(tmp_path: Path, payload: dict[str, Any]) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = asset(client)
        response = client.post(f"/api/assets/{saved['id']}/inspections", json=payload, headers=HEADERS)
        assert response.status_code in {400, 422}, response.text
        assert response.json()["error"]["request_id"]
        assert client.get("/api/jobs").json()["total"] == 0


def test_structured_failures_have_request_ids_without_echoing_secrets(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").headers["x-request-id"]
        missing = client.get("/api/not-a-route")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "ROUTE_NOT_FOUND"
        assert missing.json()["error"]["request_id"] == missing.headers["x-request-id"]
        wrong_method = client.delete("/api/assets", headers=HEADERS)
        assert wrong_method.status_code == 405 and wrong_method.headers["allow"]
        malformed = client.post("/api/jobs", json={"module": "web", "config": {"mode": "demo"}, "extra": "PRIVATE_INPUT"}, headers=HEADERS)
        assert malformed.status_code == 422 and "PRIVATE_INPUT" not in malformed.text
        bad_key = client.post("/api/assets", json={"kind": "cloud", "name": "Example", "source": {"profile_id": "cloud-demo"}},
                              headers={**HEADERS, "Idempotency-Key": "invalid key with spaces"})
        assert bad_key.status_code == 400 and bad_key.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
        invalid_unicode = client.post("/api/jobs", content=json.dumps({"module": "web", "name": "\ud800", "config": {"mode": "demo"}}),
                                      headers={**HEADERS, "Content-Type": "application/json"})
        assert invalid_unicode.status_code == 422
        non_finite = client.post("/api/jobs", content='{"module":"web","config":{"mode":"demo","number":NaN}}',
                                 headers={**HEADERS, "Content-Type": "application/json"})
        assert non_finite.status_code == 422
        bad_field = client.post("/api/jobs", content=json.dumps({"module": "web", "config": {"mode": "demo"}, "\ud800" + "x" * 1000: "secret"}),
                                headers={**HEADERS, "Content-Type": "application/json"})
        assert bad_field.status_code == 422 and len(bad_field.json()["error"]["details"][0]["field"][-1]) <= 80


def test_storage_lock_is_retryable_but_arbitrary_internal_errors_are_not_exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                              caplog: pytest.LogCaptureFixture) -> None:
    from reachscope_workbench.core.assets import AssetRepository

    app = create_app(tmp_path)
    with TestClient(app) as client:
        def locked(*_: Any, **__: Any) -> Any:
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(AssetRepository, "list", locked)
        response = client.get("/api/assets")
        assert response.status_code == 503 and response.headers["retry-after"] == "2"
        assert response.json()["error"]["retryable"]
        def broken(*_: Any, **__: Any) -> Any:
            raise RuntimeError("private internal path or secret")
        monkeypatch.setattr(AssetRepository, "list", broken)
        with caplog.at_level(logging.ERROR):
            failed = client.get("/api/assets")
        assert failed.status_code == 500 and failed.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private internal" not in failed.text
        assert failed.headers["x-request-id"] in caplog.text


def test_busy_workspace_is_not_migrated_before_lifespan(tmp_path: Path) -> None:
    from reachscope_workbench.core.locking import WorkspaceLock
    from reachscope_workbench.core.models import WorkbenchError
    from reachscope_workbench.core.repository import JobRepository

    path = tmp_path / "workbench.sqlite3"
    repository = JobRepository(path)
    with repository.connection() as connection:
        connection.execute("UPDATE schema_meta SET version=2")
    with repository.connection() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = path.read_bytes()
    owner = WorkspaceLock(tmp_path)
    owner.acquire()
    try:
        with pytest.raises(WorkbenchError) as error:
            create_app(tmp_path)
        assert error.value.code == "WORKSPACE_BUSY" and path.read_bytes() == before
    finally:
        owner.release()
    app = create_app(tmp_path)
    with app.state.repository.connection() as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 7


def test_health_remains_available_during_a_real_submission_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.core.runner import JobRunner

    entered = threading.Event()
    original = JobRunner._persist

    def persist(self: JobRunner, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(JobRunner, "_persist", persist)
    with TestClient(create_app(tmp_path)) as client:
        connection = sqlite3.connect(tmp_path / "workbench.sqlite3")
        try:
            connection.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=2) as threads:
                submission = threads.submit(client.post, "/api/jobs", json={"module": "cloud", "config": {"mode": "demo"}}, headers=HEADERS)
                try:
                    assert entered.wait(timeout=3), "The submission never reached persistence"
                    health = threads.submit(client.get, "/api/health")
                    response = health.result(timeout=2)
                    assert response.status_code == 200 and response.json()["status"] == "ok"
                    assert not submission.done(), "Expected SQLite writer to remain pending while health completes"
                finally:
                    connection.rollback()
                assert submission.result(timeout=5).status_code == 201
        finally:
            connection.close()


def test_health_does_not_claim_ready_when_a_worker_stops(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ready"]

        async def stop_one() -> None:
            worker = app.state.runner.workers[0]
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        assert client.portal is not None
        client.portal.call(stop_one)
        health = client.get("/api/health").json()
        assert health["status"] == "degraded" and not health["ready"] and health["tasks"]["alive_workers"] == 1
