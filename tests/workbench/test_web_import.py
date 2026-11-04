"""Legacy-rule preservation and strict imported evidence semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.modules.web import WebModule
from reachscope_workbench.modules.web.importer import MAX_IMPORT_BYTES, parse_import
from reachscope_workbench.modules.web.legacy.classify import (
    classify_asset,
    classify_assets,
    load_rules,
)
from reachscope_workbench.modules.web.legacy.demo import demo_assets, demo_rows
from reachscope_workbench.modules.web.legacy.models import Asset


@pytest.mark.parametrize("filename,data", [
    ("httpx.jsonl", b'{"url":"https://api.example.com:8443/docs","title":"Swagger UI","webserver":"nginx","status_code":200}\n'),
    ("assets.csv", b'host,port,title,server\napi.example.com,443,Swagger UI,nginx\n'),
    ("fofa.json", b'{"results":[["api.example.com","203.0.113.1","443","Swagger UI","nginx"]]}'),
    ("single.json", b'{"url":"https://api.example.com/","title":"Swagger UI"}'),
])
def test_import_formats(filename: str, data: bytes) -> None:
    assets, records, warnings = parse_import(data, filename)
    assert len(assets) == len(records) == 1
    assert assets[0].host == "api.example.com"
    assert assets[0].title == "Swagger UI"
    assert not warnings
    assert records[0]["reachability_source"] == "imported_unverified"


def test_nuclei_findings_are_explicitly_unverified() -> None:
    payload = [{"matched-at": "https://example.com/docs", "template-id": "example-check",
                "info": {"name": "Swagger UI", "severity": "high"}, "matcher-name": "swagger"}]
    assets, records, _ = parse_import(json.dumps(payload).encode(), "nuclei.json")
    assert assets[0].title == "Swagger UI"
    assert records[0]["imported_finding"]["verified"] is False
    assert not records[0]["reachable"]


def test_import_invalid_ipv6_record_is_reported() -> None:
    _, _, warnings = parse_import(b'[{"host":"[broken"},{"host":"good.example"}]', "assets.json")
    assert len(warnings) == 1


@pytest.mark.parametrize("data,filename", [
    (b'not-json', "assets.json"), (b'[]', "assets.json"),
    (b'{"host":"a.example"}\nnoise\n', "assets.jsonl"),
    (b'["not-an-object"]', "assets.json"), (b'{}', "assets.txt"),
    (b'\xff', "assets.json"),
])
def test_bad_import_is_visible(data: bytes, filename: str) -> None:
    with pytest.raises(WorkbenchError):
        parse_import(data, filename)


def test_partial_bad_records_have_warnings_not_silent_success() -> None:
    assets, records, warnings = parse_import(json.dumps([
        {"title": "missing host"}, {"host": "good.example", "port": "443"},
        {"host": "bad.example:99999"},
    ]).encode(), "assets.json")
    assert len(assets) == len(records) == 1
    assert len(warnings) == 2 and "Record 1" in warnings[0]


def test_import_bytes_and_record_count_are_bounded() -> None:
    with pytest.raises(WorkbenchError, match="2 MiB"):
        parse_import(b"x" * (MAX_IMPORT_BYTES + 1), "assets.json")
    with pytest.raises(WorkbenchError, match="5000"):
        parse_import(json.dumps([{"host": "example.com"}] * 5001).encode(), "assets.json")


def test_legacy_golden_dataset_is_preserved() -> None:
    assets = demo_assets()
    classify_assets(assets)
    assert [(asset.category, asset.tech) for asset in assets] == [(row[5], row[6]) for row in demo_rows()]
    rule = classify_asset(Asset(host="db.example", title="phpMyAdmin", server="nginx"), load_rules())
    assert rule.tech == "phpmyadmin"
    assert classify_asset(Asset(host="x.example", port="8080"), load_rules()).tech != "ftp"


@pytest.mark.parametrize("config", [
    {"mode": "bad"}, {"mode": "probe", "targets": []},
    {"mode": "probe", "targets": ["https://example.com"], "allow_private": "true"},
    {"mode": "probe", "targets": ["https://example.com"], "timeout": float("nan")},
    {"mode": "probe", "targets": ["https://example.com"], "concurrency": 99},
    {"mode": "import", "upload_id": "../escape", "filename": "data.json"},
])
def test_config_validation(config: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError):
        WebModule().validate(config)


def test_demo_is_offline_and_preserves_real_rule_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.modules.web import module

    async def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("demo must not probe")

    monkeypatch.setattr(module, "probe_url", no_network)
    result = asyncio.run(WebModule().run({"mode": "demo"}, RunContext("id", tmp_path, tmp_path, lambda p, m: None)))
    assert result.summary["assets"] == 20 and result.summary["online"] == 0
    assert result.details["paths"] and all(path["status"] == "candidate_investigation" for path in result.details["paths"])
    assert all(item.confidence == "heuristic" for item in result.observations)


def test_upload_import_and_duplicate_hosts_keep_correct_evidence(tmp_path: Path) -> None:
    upload_id = "a" * 32
    data = [{"url": "https://example.com/docs", "title": "Swagger UI"},
            {"url": "https://example.com:8443/", "title": "Spring Boot Actuator"}]
    (tmp_path / upload_id).write_text(json.dumps(data), encoding="utf-8")
    result = asyncio.run(WebModule().run(
        {"mode": "import", "upload_id": upload_id, "filename": "assets.json"},
        RunContext("id", tmp_path, tmp_path, lambda p, m: None),
    ))
    assert result.summary["assets"] == 2
    sources = {item.id: item.source for item in result.evidence}
    paths = result.details["paths"]
    assert len({path["id"] for path in paths}) == len(paths)
    assert any(sources[path["evidence_ids"][0]] == "https://example.com/docs" for path in paths)
    assert any(sources[path["evidence_ids"][0]] == "https://example.com:8443/" for path in paths)
    assert all(item.sha256 for item in result.evidence)
    assert all(item.data["asset"]["host"] == "example.com" for item in result.evidence)


def test_imported_status_is_not_claimed_as_this_runs_online_probe(tmp_path: Path) -> None:
    upload_id = "b" * 32
    (tmp_path / upload_id).write_text('{"url":"https://example.com/","status_code":200}', encoding="utf-8")
    result = asyncio.run(WebModule().run(
        {"mode": "import", "upload_id": upload_id, "filename": "assets.json"},
        RunContext("id", tmp_path, tmp_path, lambda p, m: None),
    ))
    assert result.summary["online"] == 0 and result.summary["imported_responses"] == 1
    assert result.details["assets"][0]["status_code"] == 200
    assert result.details["assets"][0]["reachability_source"] == "imported_unverified"


def test_import_missing_upload_is_a_structured_error(tmp_path: Path) -> None:
    with pytest.raises(WorkbenchError, match="missing"):
        asyncio.run(WebModule().run({"mode": "import", "upload_id": "a" * 32, "filename": "a.json"},
                                   RunContext("id", tmp_path, tmp_path, lambda p, m: None)))
