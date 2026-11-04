"""Parallel or corrupt historical results cannot substantiate remediation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.workbench.test_redblue_api import add_network_case, saved_cloud, workspace

from reachscope_workbench.api.app import create_app

HEADERS = {"X-ReachScope-Client": "workbench"}


def test_retest_completed_before_baseline_cannot_close_case(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    _, parallel = saved_cloud(app.state.repository, revision_of=asset, mitigated=True)
    with app.state.repository.connection() as connection:
        connection.execute("UPDATE jobs SET created_at=?,updated_at=? WHERE id=?", (
            "2026-11-01T12:00:00+00:00", "2026-11-01T12:05:00+00:00", baseline["id"],
        ))
        connection.execute("UPDATE jobs SET created_at=?,updated_at=? WHERE id=?", (
            "2026-11-01T12:01:00+00:00", "2026-11-01T12:02:00+00:00", parallel["id"],
        ))
    with TestClient(app, headers=HEADERS) as client:
        case = add_network_case(client, workspace(client, asset["id"]), baseline["id"])
        response = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": parallel["id"]})
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_RETEST"
        response = client.patch(f"/api/cases/{case['id']}", json={
            "expected_version": case["version"], "status": "resolved", "note": "An earlier collection is not a fix",
            "retest_job_id": parallel["id"],
        })
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_RETEST"
        current = client.get(f"/api/cases/{case['id']}").json()
        assert current["status"] == "open" and current["version"] == case["version"]
        assert client.get(f"/api/cases/{case['id']}/retest-jobs").json()["items"] == []


@pytest.mark.parametrize("created,completed", [
    ("2026-11-01T12:00:00", "2026-11-01T12:01:00+00:00"),
    ("2026-11-01T12:00:00+00:00", "2026-11-01T12:01:00"),
    ("2026-11-01T12:05:00+00:00", "2026-11-01T12:00:00+00:00"),
    ("not-a-date", "2026-11-01T12:01:00+00:00"),
])
def test_invalid_baseline_time_is_a_safe_retest_error(tmp_path: Path, created: str, completed: str) -> None:
    app = create_app(tmp_path)
    asset, baseline = saved_cloud(app.state.repository)
    _, retest = saved_cloud(app.state.repository, revision_of=asset, mitigated=True)
    with app.state.repository.connection() as connection:
        connection.execute("UPDATE jobs SET created_at=?,updated_at=? WHERE id=?", (created, completed, baseline["id"]))
    with TestClient(app, headers=HEADERS) as client:
        case = add_network_case(client, workspace(client, asset["id"]), baseline["id"])
        response = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": retest["id"]})
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_RETEST"

