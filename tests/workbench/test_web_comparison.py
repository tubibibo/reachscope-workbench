"""Historical diffs distinguish changed observations from missing/failed collection."""

from __future__ import annotations

import copy
import csv
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.web.comparison import compare_jobs
from reachscope_workbench.modules.web.export import inventory_csv, spreadsheet_cell


def asset(url: str = "https://example.test/") -> dict[str, Any]:
    return {
        "url": url, "reachable": True, "status_code": 200, "title": "First title", "server": "fixture",
        "ip": "192.0.2.1", "final_url": url, "content_type": "text/html", "headers": {}, "redirects": [],
        "body_sha256": "a" * 64, "body_truncated": False, "hash_scope": "captured_body", "content_encoding": "identity",
        "tls": None, "evidence_ids": ["record-1"], "cookies": [],
        "checks": [{"id": "csp", "status": "review"}],
        "page": {"analyzed": True, "language": "en", "description": "Example", "canonical": url,
                 "counts": {"forms": 1, "scripts": 1}, "scripts": [{"url": url + "a.js"}],
                 "stylesheets": [], "links": [], "truncated": False},
    }


def job(job_id: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": job_id, "name": job_id, "module": "web", "status": "completed",
            "result": {"module": "web", "summary": {"mode": "probe"}, "details": {"assets": assets}}}


def test_changed_added_removed_failed_and_evidence_are_distinct() -> None:
    before = asset()
    after = copy.deepcopy(before)
    after.update(title="Changed title", evidence_ids=["record-2"])
    after["headers"]["content-security-policy"] = "default-src 'self'"
    after["checks"][0]["status"] = "pass"
    unavailable = asset("https://failed.test/")
    unavailable.update(reachable=False, status_code=None)
    baseline = job("before", [before, asset("https://removed.test/"), asset("https://failed.test/")])
    current = job("after", [after, asset("https://added.test/"), unavailable])
    original = copy.deepcopy((baseline, current))
    result = compare_jobs(baseline, current)
    assert result["summary"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 0, "not_comparable": 1}
    changed = next(row for row in result["assets"] if row["status"] == "changed")
    assert {row["field"] for row in changed["changes"]} == {"title", "headers.content-security-policy", "checks.csp"}
    assert changed["before_evidence_ids"] == ["record-1"] and changed["after_evidence_ids"] == ["record-2"]
    failed = next(row for row in result["assets"] if row["status"] == "not_comparable")
    assert failed["notes"] and all(row["field"] in {"reachable", "status_code"} for row in failed["changes"])
    assert (baseline, current) == original


def test_old_results_and_new_rules_do_not_appear_as_site_improvement() -> None:
    before, after = asset(), asset()
    for field in ("checks", "cookies", "page"):
        before.pop(field)
    result = compare_jobs(job("old", [before]), job("new", [after]))
    assert result["summary"]["unchanged"] == 1
    assert len(result["assets"][0]["notes"]) == 3
    before = asset()
    after["checks"].append({"id": "new-rule", "status": "review"})
    result = compare_jobs(job("old", [before]), job("new", [after]))
    assert result["summary"]["unchanged"] == 1 and result["assets"][0]["notes"]


@pytest.mark.parametrize("field,value", [("body_truncated", True), ("hash_scope", "captured_prefix"), ("content_encoding", "gzip")])
def test_incomplete_or_differently_encoded_bodies_are_not_compared(field: str, value: object) -> None:
    before, after = asset(), asset()
    after["body_sha256"] = "b" * 64
    after[field] = value
    result = compare_jobs(job("old", [before]), job("new", [after]))
    assert result["summary"]["unchanged"] == 1 and result["assets"][0]["notes"]


def test_complete_body_hash_and_cookie_attributes_change_without_cookie_values() -> None:
    before, after = asset(), asset()
    after.update(body_sha256="b" * 64, cookies=[{"name": "session", "secure": True, "value": "never-return-me"}])
    result = compare_jobs(job("old", [before]), job("new", [after]))
    changes = result["assets"][0]["changes"]
    assert {row["field"] for row in changes} == {"body_sha256", "cookies"}
    assert "never-return-me" not in str(result)


def test_cookie_and_resource_order_alone_is_unchanged() -> None:
    before, after = asset(), asset()
    before["cookies"] = [{"name": "b", "secure": True}, {"name": "a", "secure": False}]
    after["cookies"] = list(reversed(before["cookies"]))
    result = compare_jobs(job("old", [before]), job("new", [after]))
    assert result["summary"]["unchanged"] == 1


def test_partial_headers_and_cookie_inventories_are_not_compared_as_removed_configuration() -> None:
    before, after = asset(), asset()
    before["headers"]["content-security-policy"] = "a" * 4096
    after["headers"]["content-security-policy"] = "b" * 4096
    after.update(headers_truncated=["content-security-policy"], cookies_truncated=True,
                 cookies=[{"name": "session", "secure": True}])
    result = compare_jobs(job("old", [before]), job("new", [after]))
    assert result["summary"]["unchanged"] == 1 and len(result["assets"][0]["notes"]) == 2


@pytest.mark.parametrize("change,code", [({"module": "android"}, "MODULE_MISMATCH"), ({"status": "running"}, "RESULT_UNAVAILABLE")])
def test_incompatible_jobs_are_rejected(change: dict[str, Any], code: str) -> None:
    before = job("old", [asset()])
    before.update(change)
    with pytest.raises(WorkbenchError) as error:
        compare_jobs(before, job("new", [asset()]))
    assert error.value.code == code


def test_import_mode_same_job_and_duplicate_urls_are_rejected() -> None:
    before, after = job("old", [asset()]), job("new", [asset()])
    before["result"]["summary"]["mode"] = "import"
    with pytest.raises(WorkbenchError, match="实际 URL"):
        compare_jobs(before, after)
    with pytest.raises(WorkbenchError) as error:
        compare_jobs(after, after)
    assert error.value.code == "INVALID_COMPARISON"
    with pytest.raises(WorkbenchError) as error:
        compare_jobs(job("old", [asset(), asset()]), after)
    assert error.value.code == "INVALID_RESULT"


@pytest.mark.parametrize("value", ['=HYPERLINK("https://example.test")', " +SUM(1,2)", "\t@formula", "-2+3", "＝1+2", "\ufeff=1+1"])
def test_csv_formula_prefixes_are_neutralized(value: str) -> None:
    assert spreadsheet_cell(value) == "'" + value


def test_inventory_csv_quotes_untrusted_fields_and_keeps_provenance() -> None:
    record = asset()
    record["title"] = '=formula,"line\n二"'
    record["checks"].append({"status": "pass"})
    document = inventory_csv(job("current", [record]))
    assert document.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(document.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["title"] == "'" + record["title"]
    assert rows[0]["review_checks"] == "1" and rows[0]["forms"] == "1"
    assert rows[0]["evidence_ids"] == "record-1" and rows[0]["reachability_source"] == "active_probe"
    assert spreadsheet_cell("Ordinary site") == "Ordinary site"
    assert spreadsheet_cell(None) == ""
    with pytest.raises(WorkbenchError):
        inventory_csv({"module": "android"})


def test_compare_and_csv_api_persisted_results_and_scope(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    repository = app.state.repository

    def save(module: str, mode: str, rows: list[dict[str, Any]]) -> str:
        created = repository.create(module, "saved fixture", {"mode": mode})
        result = job(created["id"], rows)["result"]
        result.update(module=module)
        result["summary"]["mode"] = mode
        assert repository.transition(created["id"], {"queued"}, "completed", "saved", result=result)
        return str(created["id"])

    with TestClient(app) as client:
        before = save("web", "probe", [asset()])
        record = asset()
        record["title"] = "Changed"
        current = save("web", "probe", [record])
        comparison = client.get(f"/api/jobs/{current}/compare", params={"baseline": before})
        assert comparison.status_code == 200 and comparison.json()["summary"]["changed"] == 1
        response = client.get(f"/api/jobs/{current}/export?format=csv")
        assert response.status_code == 200 and "text/csv" in response.headers["content-type"]
        assert response.headers["content-disposition"].endswith('.csv"')
        assert client.get(f"/api/jobs/{current}/compare?baseline={current}").status_code == 400
        assert client.get(f"/api/jobs/{current}/compare?baseline={'0' * 32}").status_code == 404
        assert client.get(f"/api/jobs/{current}/compare?baseline={'x' * 32}").status_code == 400
        imported = save("web", "import", [asset()])
        assert client.get(f"/api/jobs/{current}/compare?baseline={imported}").status_code == 400
        android = save("android", "demo", [])
        assert client.get(f"/api/jobs/{android}/export?format=csv").status_code == 400
