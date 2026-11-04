"""Input profiles preserve asset intent and synthetic websites stay HTTP-only."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.catalog import profile_by_id, validate_binding
from reachscope_workbench.core.inspections import InspectionService
from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.core.registry import ModuleRegistry
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.modules.android import AndroidModule
from reachscope_workbench.modules.cloud import CloudModule
from reachscope_workbench.modules.web import WebModule
from reachscope_workbench.modules.web import module as web
from reachscope_workbench.modules.web.importer import parse_import
from reachscope_workbench.modules.web.legacy.demo import demo_assets, website_demo_assets

_SOURCES: dict[str, dict[str, Any]] = {
    "android-apk": {"upload_id": "a" * 32, "filename": "sample.apk"},
    "android-demo": {"sample": "cross_component"},
    "website-probe": {"targets": ["https://website.example.test/"]},
    "website-import": {"upload_id": "b" * 32, "filename": "websites.json"},
    "website-demo": {},
    "cloud-external": {"targets": ["https://cloud.example.test:8443/service"]},
    "cloud-config": {"upload_id": "b" * 32, "filename": "websites.json"},
    "cloud-demo": {},
}


@pytest.fixture
def inspections(tmp_path: Path) -> InspectionService:
    jobs = JobRepository(tmp_path / "workspace.sqlite3")
    jobs.add_upload("a" * 32, "sample.apk", 10, "0" * 64)
    jobs.add_upload("b" * 32, "websites.json", 10, "1" * 64)
    return InspectionService(AssetRepository(jobs), ModuleRegistry([AndroidModule(), WebModule(), CloudModule()]), tmp_path / "uploads")


@pytest.mark.parametrize("profile_id", _SOURCES)
def test_every_profile_normalizes_and_roundtrips_its_actual_fields(
    inspections: InspectionService, profile_id: str,
) -> None:
    profile = profile_by_id(profile_id)
    raw = {"profile_id": profile_id, **_SOURCES[profile_id]}
    name, normalized = inspections.prepare_asset(profile["asset_kind"], " Example ", raw)
    assert name == "Example" and normalized["mode"] == profile["mode"]
    assert set(normalized) <= set(profile["source_fields"])
    assert inspections.prepare_asset(profile["asset_kind"], name, normalized) == (name, normalized)
    saved = inspections.inventory.create(profile["asset_kind"], name, normalized)
    selected = [check["id"] for check in profile["checks"]]
    asset, prepared_profile, configuration = inspections.prepare_inspection(saved["id"], selected)
    validate_binding(asset, profile["module"], configuration)
    assert asset["source"] == normalized and prepared_profile["id"] == profile_id
    if profile_id == "cloud-external":
        assert asset["kind"] == "cloud" and prepared_profile["module"] == "web"
        assert configuration["targets"] == raw["targets"]


@pytest.mark.parametrize("profile_id,extra", [
    ("website-probe", {"upload_id": "a" * 32}), ("website-probe", {"filename": "local.json"}),
    ("website-probe", {"sample": "cross_component"}),
    ("website-import", {"targets": ["https://other.test/"]}), ("website-import", {"sample": "cross_component"}),
    ("website-import", {"allow_private": True}), ("website-import", {"timeout": 8}),
    ("website-demo", {"targets": ["https://other.test/"]}), ("website-demo", {"upload_id": "b" * 32}),
    ("website-demo", {"filename": "local.json"}),
    ("android-apk", {"sample": "cross_component"}), ("android-apk", {"targets": ["https://other.test/"]}),
    ("android-apk", {"allow_private": True}), ("android-apk", {"concurrency": 3}),
    ("android-demo", {"upload_id": "a" * 32}), ("android-demo", {"filename": "local.apk"}),
    ("android-demo", {"targets": ["https://other.test/"]}), ("android-demo", {"apktool": "local.jar"}),
    ("cloud-external", {"upload_id": "b" * 32}), ("cloud-external", {"sample": "cross_component"}),
    ("cloud-external", {"filename": "local.json"}),
    ("cloud-config", {"targets": ["https://other.test/"]}), ("cloud-config", {"sample": "cross_component"}),
    ("cloud-config", {"allow_private": True}), ("cloud-config", {"timeout": 8}),
    ("cloud-demo", {"targets": ["https://other.test/"]}), ("cloud-demo", {"upload_id": "b" * 32}),
    ("cloud-demo", {"filename": "local.json"}), ("cloud-demo", {"sample": "cross_component"}),
])
def test_meaningful_fields_from_other_input_profiles_are_not_silently_discarded(
    inspections: InspectionService, profile_id: str, extra: dict[str, Any],
) -> None:
    profile = profile_by_id(profile_id)
    raw = {"profile_id": profile_id, **_SOURCES[profile_id], **extra}
    before = copy.deepcopy(raw)
    with pytest.raises(WorkbenchError) as error:
        inspections.prepare_asset(profile["asset_kind"], "Example", raw)
    assert error.value.code == "ASSET_MISMATCH" and raw == before
    assert inspections.inventory.list()["total"] == 0


def test_empty_inactive_controls_remain_compatible_without_storing_wrong_inputs(inspections: InspectionService) -> None:
    _, normalized = inspections.prepare_asset("website", "Example", {
        "profile_id": "website-demo", "targets": [], "upload_id": None, "filename": "", "allow_private": False})
    assert normalized == {"profile_id": "website-demo", "mode": "demo"}
    with pytest.raises(WorkbenchError) as error:
        inspections.prepare_asset("website", "Example", {"profile_id": "website-demo", "unknown": None})
    assert error.value.code == "INVALID_ASSET"


@pytest.mark.parametrize("profile_id,kind,source", [
    ("android-apk", "android", {"upload_id": "b" * 32, "filename": "websites.json"}),
    ("website-import", "website", {"upload_id": "a" * 32, "filename": "sample.apk"}),
    ("cloud-config", "cloud", {"upload_id": "a" * 32, "filename": "sample.apk"}),
])
def test_file_profiles_reject_different_artifact_types(
    inspections: InspectionService, profile_id: str, kind: str, source: dict[str, Any],
) -> None:
    with pytest.raises(WorkbenchError):
        inspections.prepare_asset(kind, "Wrong file", {"profile_id": profile_id, **source})


@pytest.mark.parametrize("config", [
    {"mode": "probe", "targets": ["https://example.test/"], "upload_id": "a" * 32},
    {"mode": "probe", "targets": ["https://example.test/"], "sample": "cross_component"},
    {"mode": "import", "upload_id": "a" * 32, "filename": "site.json", "targets": ["https://example.test/"]},
    {"mode": "demo", "targets": ["https://example.test/"]},
    {"mode": "demo", "upload_id": "a" * 32},
])
def test_direct_web_configuration_also_rejects_meaningful_mode_mismatches(config: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError) as error:
        WebModule().validate(config)
    assert error.value.code == "INVALID_CONFIG"


@pytest.mark.parametrize("record", [
    {"url": "redis://cache.example.test:6379/"}, {"host": "mysql.example.test", "port": "3306"},
    {"host": "cache.example.test", "protocol": "redis", "port": "6379"},
    {"url": "ftp://files.example.test/"}, {"host": "unknown.example.test", "port": "9999"},
    {"url": "https://example.test/", "scheme": "ftp"},
    {"url": "https://example.test:8443/", "port": "443"},
    {"url": "https://example.test:0/"},
    {"url": "file:///private/input.apk"},
])
def test_imports_do_not_relabel_non_http_services_as_websites(record: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError) as error:
        parse_import(json.dumps(record).encode(), "assets.json")
    assert error.value.code == "INVALID_IMPORT"
    assets, records, warnings = parse_import(json.dumps([record, {"url": "https://valid.example.test/"}]).encode(), "assets.json")
    assert len(assets) == len(records) == len(warnings) == 1
    assert records[0]["url"] == "https://valid.example.test/" and "Record 1" in warnings[0]


@pytest.mark.parametrize("record,expected,inferred", [
    ({"host": "example.test"}, "http://example.test/", True),
    ({"host": "example.test", "port": "443"}, "https://example.test:443/", True),
    ({"host": "example.test", "port": "8443"}, "https://example.test:8443/", True),
    ({"url": "https://example.test:8443/docs?q=1#view"}, "https://example.test:8443/docs?q=1", False),
    ({"url": "http://example.test:6379/"}, "http://example.test:6379/", False),
    ({"host": "example.test", "port": "7001", "status_code": 200}, "http://example.test:7001/", True),
    ({"host": "example.test", "port": "7001", "scheme": "https"}, "https://example.test:7001/", False),
])
def test_legal_website_imports_preserve_http_semantics_and_inference_provenance(
    record: dict[str, Any], expected: str, inferred: bool,
) -> None:
    assets, records, warnings = parse_import(json.dumps(record).encode(), "sites.json")
    assert not warnings and assets[0].protocol in {"http", "https"}
    assert records[0]["url"] == expected and records[0]["url_inferred"] is inferred
    assert records[0]["reachability_source"] == "imported_unverified"


@pytest.mark.asyncio
async def test_website_demo_is_marked_synthetic_uses_urls_and_preserves_legacy_golden_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Synthetic website examples must remain offline")

    monkeypatch.setattr(web, "probe_url", no_network)
    assert len(demo_assets()) == 25 and len(website_demo_assets()) == 20
    result = await WebModule().run({"mode": "demo"}, RunContext("website-demo", tmp_path, tmp_path, lambda *_: None))
    assert result.summary["assets"] == 20 and result.summary["synthetic"] is True and result.summary["online"] == 0
    assert all(record["synthetic"] and record["reachability_source"] == "synthetic_offline" for record in result.details["assets"])
    assert all(urlsplit(record["url"]).scheme in {"http", "https"} for record in result.details["assets"])
    assert all(record["category"] not in {"exposed_service", "unknown"} for record in result.details["assets"])
    assert any(record["url"] == "https://admin.example.com:8443/" for record in result.details["assets"])
    assert any(record["url"] == "http://console.example.com:7001/" for record in result.details["assets"])
    assert all(evidence.kind == "synthetic_asset" for evidence in result.evidence)
