"""Saved assets remain tied to the actual immutable inputs of each execution."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.catalog import catalog, profile_by_id, validate_binding
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository

HEADERS = {"X-ReachScope-Client": "workbench"}


def test_existing_workspace_adds_assets_without_changing_legacy_jobs(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    old = JobRepository(path)
    legacy = old.create("web", "Legacy", {"mode": "demo"})
    # Simulate an earlier workspace that has never had inventory tables.
    with old.connection() as connection:
        connection.execute("DROP TABLE job_assets")
        connection.execute("DROP TABLE assets")
        connection.execute("UPDATE schema_meta SET version=1")
    current = JobRepository(path)
    assert current.get(legacy["id"])["asset_id"] is None
    with current.connection() as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 7
    assert current.list()["total"] == 1
    asset = AssetRepository(current).create("website", "Example", {"profile_id": "website-demo", "mode": "demo"})
    run = current.create("web", "Bound", {"mode": "demo"}, asset=asset)
    assert run["asset_id"] == asset["id"] and run["asset_snapshot"]["source"] == asset["source"]
    assert current.list(asset_id=asset["id"])["total"] == 1
    assert AssetRepository(current).get(asset["id"])["job_count"] == 1
    assert AssetRepository(JobRepository(path)).list()["items"][0]["id"] == asset["id"]


def test_catalog_is_independent_copy_and_profiles_match_asset_kinds() -> None:
    first = catalog()
    assert len(first["profiles"]) == 12
    first["profiles"][0]["checks"].clear()
    assert profile_by_id("android-apk")["checks"]
    with pytest.raises(WorkbenchError):
        profile_by_id("not-present")
    asset = {"kind": "cloud", "source": {"profile_id": "cloud-external", "mode": "probe", "targets": ["https://example.test/"]}}
    validate_binding(asset, "web", {"mode": "probe", "targets": ["https://example.test/"]})
    for module, configuration in [("cloud", {"mode": "probe"}), ("web", {"mode": "import"}),
                                  ("web", {"mode": "probe", "targets": ["https://different.test/"]})]:
        with pytest.raises(WorkbenchError) as failure:
            validate_binding(asset, module, configuration)
        assert failure.value.code == "ASSET_MISMATCH"


def test_inventory_pagination_and_unknown_id_are_explicit(tmp_path: Path) -> None:
    inventory = AssetRepository(JobRepository(tmp_path / "db.sqlite3"))
    for index in range(3):
        inventory.create("website", f"Item {index}", {"profile_id": "website-demo", "mode": "demo"})
    assert inventory.list(limit=2)["total"] == 3 and len(inventory.list(limit=2)["items"]) == 2
    assert len(inventory.list(limit=2, offset=2)["items"]) == 1
    assert inventory.list(kind="android")["total"] == 0
    for parameters in ({"limit": 0}, {"offset": -1}, {"kind": "unknown"}):
        with pytest.raises(WorkbenchError):
            inventory.list(**parameters)
    with pytest.raises(WorkbenchError) as failure:
        inventory.get("0" * 32)
    assert failure.value.code == "ASSET_NOT_FOUND"


def test_asset_api_binding_retry_and_restart(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        described = client.get("/api/catalog").json()
        assert {item["id"] for item in described["asset_kinds"]} == {"android", "website", "cloud", "host"}
        payload = {"kind": "website", "name": "Saved example", "source": {"profile_id": "website-demo", "mode": "demo"}}
        assert client.post("/api/assets", json=payload).status_code == 403
        created = client.post("/api/assets", json=payload, headers=HEADERS)
        assert created.status_code == 201, created.text
        asset = created.json()
        response = client.post("/api/jobs", json={"module": "web", "name": "Bound", "asset_id": asset["id"],
                                                "config": {"mode": "demo"}}, headers=HEADERS)
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["asset_id"] == asset["id"]
        until = time.monotonic() + 15
        while client.get(f"/api/jobs/{run['id']}").json()["status"] in {"queued", "running"} and time.monotonic() < until:
            time.sleep(.05)
        assert client.get(f"/api/jobs/{run['id']}").json()["status"] == "completed"
        retried = client.post(f"/api/jobs/{run['id']}/retry", headers=HEADERS)
        assert retried.status_code == 201 and retried.json()["asset_id"] == asset["id"]
        assert client.get(f"/api/assets/{asset['id']}/jobs").json()["total"] == 2
        assert client.get(f"/api/assets/{asset['id']}").json()["job_count"] == 2
        mismatch = client.post("/api/jobs", json={"module": "android", "asset_id": asset["id"], "config": {"mode": "demo"}}, headers=HEADERS)
        assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "ASSET_MISMATCH"
        assert client.get("/api/jobs").json()["total"] == 2
    with TestClient(create_app(tmp_path)) as reopened:
        assert reopened.get(f"/api/assets/{asset['id']}/jobs").json()["total"] == 2


@pytest.mark.parametrize("update", [
    {"name": "   "}, {"kind": "cloud"},
    {"source": {"profile_id": "website-demo", "mode": "probe"}},
    {"source": {"profile_id": "website-demo", "secret_key": "do-not-store"}},
])
def test_invalid_asset_inputs_do_not_create_records(tmp_path: Path, update: dict[str, Any]) -> None:
    with TestClient(create_app(tmp_path)) as client:
        payload = {"kind": "website", "name": "test", "source": {"profile_id": "website-demo", "mode": "demo"}, **update}
        assert client.post("/api/assets", json=payload, headers=HEADERS).status_code == 400
        assert client.get("/api/assets").json()["total"] == 0


def test_file_asset_uses_uploaded_metadata_and_never_accepts_arbitrary_paths(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        uploaded = client.post("/api/uploads", files={"file": ("policy.json", json.dumps({"Version": "2012-10-17", "Statement": []}).encode())}, headers=HEADERS).json()
        payload = {"kind": "cloud", "name": "Local policy", "source": {"profile_id": "cloud-config", "mode": "import",
                                                                            "upload_id": uploaded["id"], "filename": uploaded["filename"]}}
        response = client.post("/api/assets", json=payload, headers=HEADERS)
        assert response.status_code == 201, response.text
        assert response.json()["source"]["upload_id"] == uploaded["id"]
        payload["source"]["filename"] = "other.json"
        assert client.post("/api/assets", json=payload, headers=HEADERS).status_code == 400
        payload["source"] = {"profile_id": "cloud-config", "mode": "import", "path": "C:/private.json"}
        assert client.post("/api/assets", json=payload, headers=HEADERS).status_code == 400
        large = client.post("/api/uploads", files={"file": ("large.json", b"x" * (2 * 1024 * 1024 + 1))}, headers=HEADERS).json()
        payload["source"] = {"profile_id": "cloud-config", "mode": "import", "upload_id": large["id"], "filename": large["filename"]}
        oversized = client.post("/api/assets", json=payload, headers=HEADERS)
        assert oversized.status_code == 400 and oversized.json()["error"]["code"] == "UPLOAD_LIMIT"
