"""Public pagination rejects values that cannot be bound to SQLite integers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.workbench.test_redblue_api import add_network_case, saved_cloud, workspace

from reachscope_workbench.api.app import create_app

HEADERS = {"X-ReachScope-Client": "workbench"}
SQLITE_MAX_INTEGER = 2**63 - 1


@pytest.mark.parametrize("value", [SQLITE_MAX_INTEGER + 1, 10**100])
def test_all_persisted_lists_and_cursors_reject_overflow(tmp_path: Path, value: int) -> None:
    app = create_app(tmp_path)
    asset, job = saved_cloud(app.state.repository)
    with TestClient(app, headers=HEADERS) as client:
        engagement = workspace(client, asset["id"])
        case = add_network_case(client, engagement, job["id"])
        paths = [
            "/api/assets?offset=",
            f"/api/assets/{asset['id']}/jobs?offset=",
            "/api/jobs?offset=",
            f"/api/jobs/{job['id']}/events?after=",
            "/api/engagements?offset=",
            f"/api/engagements/{engagement}/cases?offset=",
            f"/api/cases/{case['id']}/events?after=",
            f"/api/cases/{case['id']}/retest-jobs?offset=",
        ]
        for path in paths:
            response = client.get(f"{path}{value}")
            assert response.status_code == 400, (path, response.text)
            assert response.json()["error"]["code"] == "INVALID_PAGE"
        assert client.get("/api/health").json()["ready"]


def test_largest_sqlite_cursor_is_a_valid_empty_page(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    asset, job = saved_cloud(app.state.repository)
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job['id']}/events?after={SQLITE_MAX_INTEGER}")
        assert response.status_code == 200 and response.json() == {"items": [], "next_cursor": SQLITE_MAX_INTEGER}
        response = client.get(f"/api/assets/{asset['id']}/jobs?offset={SQLITE_MAX_INTEGER}")
        assert response.status_code == 200 and response.json()["items"] == []

