"""Opt-in local teaching HTTP is real evidence, never a production safety claim."""

from __future__ import annotations

import hashlib
import http.client
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.integrations import local_lab
from reachscope_workbench.integrations.local_lab import LocalLab
from reachscope_workbench.modules.web.probe import probe_url

HEADERS = {"X-ReachScope-Client": "workbench"}


@pytest.fixture
def lab() -> Iterator[LocalLab]:
    instance = LocalLab()
    try:
        yield instance
    finally:
        instance.stop()


def test_lab_is_opt_in_exact_loopback_and_start_is_idempotent(lab: LocalLab) -> None:
    before = lab.status()
    assert before["status"] == "stopped" and before["url"] is None and before["asset_template"] is None
    assert not before["automatic_scan"] and not before["automatic_ai"]
    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(lambda _: lab.start(), range(8)))
    assert len({item["url"] for item in statuses}) == len({item["session_id"] for item in statuses}) == 1
    started = statuses[0]
    assert started["profile"] == "baseline" and started["generation"] != before["generation"]
    assert urlsplit(started["url"]).hostname == "127.0.0.1"
    with httpx.Client(trust_env=False, timeout=2) as client:
        response = client.get(started["url"])
    assert response.status_code == 200 and "not a production target" in response.text
    assert "Python" not in response.headers["server"]
    assert response.headers["x-reachscope-lab-session"] == started["session_id"]
    assert response.headers["x-reachscope-lab-generation"] == started["generation"]
    assert response.headers["x-reachscope-lab-profile"] == "baseline"
    assert "strict-transport-security" not in response.headers
    assert started["asset_template"]["source"] == {
        "profile_id": "website-probe", "mode": "probe", "targets": [started["url"]], "allow_private": True,
    }


def test_profiles_are_cas_guarded_and_keep_the_same_url(lab: LocalLab) -> None:
    initial = lab.start()
    assert lab.configure(initial["generation"], "baseline") == initial
    changed = lab.configure(initial["generation"], "hardened")
    assert changed["url"] == initial["url"] and changed["session_id"] == initial["session_id"]
    assert changed["generation"] != initial["generation"]
    assert lab.start() == changed, "Start must not reset the explicitly selected profile"
    with pytest.raises(WorkbenchError) as failure:
        lab.configure(initial["generation"], "baseline")
    assert failure.value.code == "LAB_CONFLICT" and lab.status() == changed
    with httpx.Client(trust_env=False, timeout=2) as client:
        response = client.get(changed["url"])
    assert response.status_code == 200 and "Profile: hardened" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers, "HTTP teaching must not claim TLS/HSTS hardening"


@pytest.mark.parametrize("path", ["/unknown", "/?profile=hardened", "/../README.md", "/favicon.ico"])
def test_lab_never_serves_user_files_or_query_configuration(lab: LocalLab, path: str) -> None:
    started = lab.start()
    with httpx.Client(trust_env=False, timeout=2) as client:
        response = client.get(started["url"].rstrip("/") + path)
    assert response.status_code == 404 and not response.content
    assert lab.status()["profile"] == "baseline"


def test_lab_rejects_unowned_host_duplicate_host_and_state_changing_methods(lab: LocalLab) -> None:
    started = lab.start()
    with httpx.Client(trust_env=False, timeout=2) as client:
        assert client.get(started["url"], headers={"Host": "outside.example"}).status_code == 421
        for method in ("HEAD", "POST", "PUT", "DELETE"):
            assert client.request(method, started["url"]).status_code == 405
    parsed = urlsplit(started["url"])
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=2)
    try:
        connection.putrequest("GET", "/", skip_host=True)
        connection.putheader("Host", parsed.netloc)
        connection.putheader("Host", "outside.example")
        connection.endheaders()
        assert connection.getresponse().status == 421
    finally:
        connection.close()


def test_only_owned_live_exact_url_has_managed_session_provenance(lab: LocalLab) -> None:
    initial = lab.start()
    assert lab.provenance_for(initial["url"]) == {
        "kind": "local_training", "label": initial["source"]["label"], "session_id": initial["session_id"],
    }
    for url in ("http://127.0.0.1:1/", "https://example.test/", initial["url"] + "?fake=1",
                initial["url"].replace("127.0.0.1", "localhost")):
        assert lab.provenance_for(url) is None
    stopped = lab.stop()
    assert stopped["status"] == "stopped" and stopped["session_id"] is None and stopped["url"] is None
    assert stopped == lab.stop()
    assert lab.provenance_for(initial["url"]) is None
    with httpx.Client(trust_env=False, timeout=.5) as client, pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
        client.get(initial["url"])
    restarted = lab.start()
    assert restarted["session_id"] != initial["session_id"] and restarted["profile"] == "baseline"
    assert restarted["generation"] != initial["generation"]


def test_stopped_configuration_and_start_failure_are_visible(lab: LocalLab, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(WorkbenchError) as failure:
        lab.configure(lab.status()["generation"], "hardened")
    assert failure.value.code == "LAB_NOT_RUNNING"

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("Private OS/socket detail must not be returned")

    monkeypatch.setattr(local_lab, "_LabHTTPServer", fail)
    with pytest.raises(WorkbenchError) as failure:
        lab.start()
    assert failure.value.code == "LAB_UNAVAILABLE" and "Private" not in failure.value.message
    assert lab.status()["status"] == "stopped"


def test_failed_worker_start_releases_the_bound_socket(lab: LocalLab, monkeypatch: pytest.MonkeyPatch) -> None:
    servers: list[local_lab._LabHTTPServer] = []
    original = local_lab._LabHTTPServer

    class ObservedServer(original):
        def __init__(self, manager: LocalLab) -> None:
            super().__init__(manager)
            servers.append(self)

    def fail_start(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Thread creation failed")

    monkeypatch.setattr(local_lab, "_LabHTTPServer", ObservedServer)
    monkeypatch.setattr(local_lab.threading.Thread, "start", fail_start)
    with pytest.raises(WorkbenchError) as failure:
        lab.start()
    assert failure.value.code == "LAB_UNAVAILABLE"
    assert len(servers) == 1 and servers[0].socket.fileno() == -1
    assert lab.status()["status"] == "stopped"


@pytest.mark.asyncio
async def test_teaching_site_remains_subject_to_normal_private_target_consent(lab: LocalLab) -> None:
    started = lab.start()
    response = await probe_url(started["url"], allow_private=False, timeout=1)
    assert not response["reachable"] and response["error"]["code"] == "OUT_OF_SCOPE"


def _wait_job(client: TestClient, job_id: str) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            assert job["status"] == "completed", job
            return job
        time.sleep(.02)
    raise AssertionError("Local teaching inspection did not finish")


def test_real_local_baseline_to_hardened_evidence_case_and_retest(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app, headers=HEADERS) as client:
        assert client.get("/api/lab").json()["status"] == "stopped"
        started = client.post("/api/lab/start").json()
        assert started["status"] == "running" and client.get("/api/jobs").json()["total"] == 0
        assert client.post("/api/lab/start").json() == started
        response = client.post("/api/assets", json=started["asset_template"], headers={"Idempotency-Key": "teaching-asset"})
        assert response.status_code == 201, response.text
        asset = response.json()
        assert asset["provenance"]["kind"] == "local_training"
        assert asset["provenance"]["session_id"] == started["session_id"]
        assert "profile" not in asset["provenance"], "Asset identity must not mutate when live responses change"

        def inspect(name: str) -> dict[str, Any]:
            response = client.post(f"/api/assets/{asset['id']}/inspections", json={"name": name, "checks": ["http", "headers", "page"]},
                                   headers={"Idempotency-Key": name})
            assert response.status_code == 201, response.text
            return _wait_job(client, response.json()["id"])

        baseline = inspect("teaching-baseline")
        record = baseline["result"]["details"]["assets"][0]
        checks = {row["id"]: row for row in record["checks"]}
        assert all(checks[rule]["status"] == "review" for rule in ("csp", "nosniff", "frame_protection", "referrer_policy"))
        assert baseline["asset_snapshot"]["provenance"] == asset["provenance"]
        assert baseline["result"]["evidence"], "The lab must use actual saved HTTP evidence"
        headers = record["headers"]
        assert headers["x-reachscope-lab-session"] == started["session_id"]
        assert headers["x-reachscope-lab-profile"] == "baseline"
        baseline_hash = record["body_sha256"]
        assert len(baseline_hash) == len(hashlib.sha256().hexdigest())
        response = client.post("/api/engagements", json={"name": "Local teaching / response headers", "asset_ids": [asset["id"]],
                               "authorization_note": "Managed loopback teaching session, fixed content only"})
        assert response.status_code == 201, response.text
        engagement = response.json()
        sources = client.get(f"/api/engagements/{engagement['id']}/candidates", params={"job_id": baseline["id"]}).json()["items"]
        source = next(row for row in sources if row["category"] == "nosniff")
        response = client.post(f"/api/engagements/{engagement['id']}/cases", json={"job_id": baseline["id"],
                               "source_kind": source["source_kind"], "source_ref": source["source_ref"]})
        assert response.status_code == 201, response.text
        case = response.json()
        changed = client.post("/api/lab/configure", json={"generation": started["generation"], "profile": "hardened"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["url"] == started["url"] and client.get("/api/jobs").json()["total"] == 1
        hardened = inspect("teaching-hardened")
        after = hardened["result"]["details"]["assets"][0]
        after_checks = {row["id"]: row for row in after["checks"]}
        assert all(after_checks[rule]["status"] == "pass" for rule in ("csp", "nosniff", "frame_protection", "referrer_policy"))
        assert after["body_sha256"] != baseline_hash and after["headers"]["x-reachscope-lab-profile"] == "hardened"
        assert "strict-transport-security" not in after["headers"]
        assessed = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": hardened["id"]})
        assert assessed.status_code == 200 and assessed.json()["outcome"] == "not_observed_in_scope"
        closed = client.patch(f"/api/cases/{case['id']}", json={"expected_version": case["version"], "status": "resolved",
                              "retest_job_id": hardened["id"], "note": "The same managed local URL now returns nosniff; teaching scope only"})
        assert closed.status_code == 200 and closed.json()["status"] == "resolved"
        assert client.get(f"/api/jobs/{baseline['id']}").json()["result"] == baseline["result"]
        assert client.get(f"/api/assets/{asset['id']}").json()["provenance"] == asset["provenance"]
        assert client.get(f"/api/jobs/{baseline['id']}/advisories").json()["items"] == []
        assert client.get(f"/api/jobs/{hardened['id']}/advisories").json()["items"] == []
        assert client.post("/api/lab/stop").json()["status"] == "stopped"
        assert client.get(f"/api/jobs/{baseline['id']}").status_code == 200
    assert app.state.lab.status()["status"] == "stopped"
    with TestClient(create_app(tmp_path)) as reopened:
        assert reopened.get("/api/lab").json()["status"] == "stopped"
        assert reopened.get(f"/api/assets/{asset['id']}").json()["provenance"] == asset["provenance"]
        assert reopened.get(f"/api/jobs/{baseline['id']}").json()["asset_snapshot"]["provenance"] == asset["provenance"]


def test_arbitrary_asset_name_url_or_client_provenance_cannot_forge_teaching_origin(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path), headers=HEADERS) as client:
        started = client.post("/api/lab/start").json()
        forged = {**started["asset_template"], "provenance": {"kind": "local_training", "session_id": started["session_id"]}}
        assert client.post("/api/assets", json=forged).status_code == 422
        other = {"kind": "website", "name": "本地教学站点 / User-written label is not proof",
                 "source": {**started["asset_template"]["source"], "targets": [started["url"] + "unowned"]}}
        response = client.post("/api/assets", json=other)
        assert response.status_code == 201 and response.json()["provenance"] is None
        assert client.post("/api/lab/stop").status_code == 200
        response = client.post("/api/assets", json=started["asset_template"])
        assert response.status_code == 201 and response.json()["provenance"] is None


def test_lab_api_validation_boundary_and_lifespan_cleanup(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/lab/start").status_code == 403
        assert client.post("/api/lab/start", headers={**HEADERS, "Origin": "https://outside.example"}).status_code == 403
        for body in ({"url": "https://example.test"}, {"port": 1234}, {"html": "<script>ignored</script>"}):
            assert client.post("/api/lab/start", json=body, headers=HEADERS).status_code == 422
        started = client.post("/api/lab/start", headers=HEADERS).json()
        for body in ({"generation": started["generation"], "profile": "custom"},
                     {"generation": [], "profile": "hardened"},
                     {"generation": started["generation"], "profile": "hardened", "headers": {"X-Fake": "yes"}}):
            assert client.post("/api/lab/configure", json=body, headers=HEADERS).status_code == 422
        changed = client.post("/api/lab/configure", json={"generation": started["generation"], "profile": "hardened"}, headers=HEADERS)
        assert changed.status_code == 200
        stale = client.post("/api/lab/configure", json={"generation": started["generation"], "profile": "baseline"}, headers=HEADERS)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "LAB_CONFLICT"
    assert app.state.lab.status()["status"] == "stopped"
    with httpx.Client(trust_env=False, timeout=.5) as probe, pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
        probe.get(started["url"])
