"""Acceptance regressions found while reviewing public API boundaries."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app


def test_streamed_json_request_budget_returns_domain_error(tmp_path: Path) -> None:
    body = json.dumps({"module": "android", "name": "oversized",
                       "config": {"mode": "demo", "padding": "x" * 150_000}}).encode()
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/jobs", content=iter((body[:100_000], body[100_000:])),
            headers={"X-ReachScope-Client": "workbench", "Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_LIMIT"
        assert client.get("/api/jobs").json()["total"] == 0


def test_api_documentation_is_disabled_or_works_without_external_scripts(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        docs = client.get("/docs")
        assert docs.status_code in {200, 404}
        if docs.status_code == 200:
            sources = re.findall(r'<script[^>]+src=["\']([^"\']+)', docs.text)
            assert all(not source.startswith(("http://", "https://", "//")) for source in sources)
        assert client.get("/openapi.json").status_code == 200
