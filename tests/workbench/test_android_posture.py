"""Configuration review proves bounded declarations, never runtime exploitability."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest

from reachscope.ingest.apk import IngestError
from reachscope_workbench.modules.android import code_worker
from reachscope_workbench.modules.android.manifest_worker import inspect_manifest
from reachscope_workbench.modules.android.posture import inspect_security_review

NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'


def manifest(tmp_path: Path, attributes: str = "", children: str = "", *, sdk: int = 30, minimum: int = 24) -> Path:
    path = tmp_path / "AndroidManifest.xml"
    path.write_text(f'<manifest {NS} package="test.app"><uses-sdk android:targetSdkVersion="{sdk}" android:minSdkVersion="{minimum}"/>'
                    f'<application {attributes}>{children}</application></manifest>', encoding="utf-8")
    return path


def checks(path: Path) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in inspect_manifest(path)["security_review"]["checks"]}


def resource(tmp_path: Path, name: str, contents: str, folder: str = "xml") -> None:
    target = tmp_path / "res" / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.xml").write_text(contents, encoding="utf-8")


@pytest.mark.parametrize(("attribute", "expected"), [("", "pass"), ('android:debuggable="false"', "pass"),
                                                      ('android:debuggable="true"', "review"), ('android:debuggable="@bool/debug"', "unknown")])
def test_debug_declaration_default_and_unresolved(tmp_path: Path, attribute: str, expected: str) -> None:
    result = checks(manifest(tmp_path, attribute))["android.debuggable"]
    assert result["status"] == expected
    assert result["complete"] is (expected != "unknown")
    assert result["evidence_ids"] == ["android-review:android.debuggable"]
    assert result["guidance"]["verification"] and result["guidance"]["rollback"]


@pytest.mark.parametrize(("sdk", "attribute", "expected"), [(30, 'android:allowBackup="false"', "pass"),
                                                            (31, 'android:allowBackup="false"', "unknown"),
                                                            (33, "", "review"), (30, 'android:allowBackup="@bool/backup"', "unknown")])
def test_backup_is_data_review_and_respects_modern_device_migration(tmp_path: Path, sdk: int, attribute: str, expected: str) -> None:
    assert checks(manifest(tmp_path, attribute, sdk=sdk))["android.backup"]["status"] == expected


def test_real_backup_rules_are_read_with_hashes_not_claimed_complete_exclusions(tmp_path: Path) -> None:
    resource(tmp_path, "backup", '<full-backup-content><exclude domain="database" path="credentials.db"/></full-backup-content>')
    resource(tmp_path, "extract", '<data-extraction-rules><cloud-backup><exclude domain="file" path="tokens"/></cloud-backup></data-extraction-rules>')
    result = checks(manifest(tmp_path, 'android:fullBackupContent="@xml/backup" android:dataExtractionRules="@xml/extract"'))["android.backup"]
    assert result["status"] == "review"
    assert any(item["source"] == "res/xml/backup.xml" and item["value"]["sha256"] for item in result["facts"])


def test_network_config_precedence_and_domain_inheritance(tmp_path: Path) -> None:
    resource(tmp_path, "network", '''<network-security-config><base-config cleartextTrafficPermitted="false"><trust-anchors><certificates src="system"/></trust-anchors></base-config>
      <domain-config><domain>safe.test</domain><domain-config cleartextTrafficPermitted="true"><domain>legacy.test</domain></domain-config></domain-config></network-security-config>''')
    result = checks(manifest(tmp_path, 'android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/network"'))
    assert result["android.cleartext"]["status"] == "review"
    assert result["android.trust_anchors"]["status"] == "pass"
    assert result["android.debug_overrides"]["status"] == "not_applicable"


@pytest.mark.parametrize(("sdk", "expected"), [(23, "review"), (24, "pass"), (38, "pass")])
def test_network_default_trust_uses_target_and_actual_resource(tmp_path: Path, sdk: int, expected: str) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>')
    result = checks(manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"', sdk=sdk))
    assert result["android.trust_anchors"]["status"] == expected


def test_custom_ca_is_unknown_user_ca_review_and_debug_only_ignored_on_release(tmp_path: Path) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config><trust-anchors><certificates src="@raw/company"/></trust-anchors></base-config><debug-overrides><trust-anchors><certificates src="user"/></trust-anchors></debug-overrides></network-security-config>')
    result = checks(manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"'))
    assert result["android.trust_anchors"]["status"] == "unknown"
    assert result["android.debug_overrides"]["status"] == "not_applicable"
    result = checks(manifest(tmp_path, 'android:debuggable="true" android:networkSecurityConfig="@xml/network"'))
    assert result["android.debug_overrides"]["status"] == "review"
    resource(tmp_path, "network", '<network-security-config><base-config><trust-anchors><certificates src="user"/></trust-anchors></base-config></network-security-config>')
    assert checks(manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"'))["android.trust_anchors"]["status"] == "review"


@pytest.mark.parametrize("reference", ["@xml/missing", "@other:xml/network", "@xml/../../outside", "@0x7f000001"])
def test_unavailable_resources_do_not_manufacture_safe_defaults(tmp_path: Path, reference: str) -> None:
    result = checks(manifest(tmp_path, f'android:networkSecurityConfig="{reference}"'))
    assert result["android.cleartext"]["status"] == "unknown"
    assert result["android.trust_anchors"]["status"] == "unknown"
    assert result["android.cleartext"]["complete"] is False
    assert result["android.debuggable"]["complete"] is True


@pytest.mark.parametrize("contents", ["broken XML", "<wrong-root/>", '<!DOCTYPE x [<!ENTITY a "x">]><network-security-config/>'])
def test_invalid_resource_is_unknown_without_failing_other_manifest_facts(tmp_path: Path, contents: str) -> None:
    resource(tmp_path, "network", contents)
    result = checks(manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"'))
    assert result["android.cleartext"]["status"] == "unknown"
    assert result["android.debuggable"]["status"] == "pass"


def test_qualified_resources_without_base_are_unknown(tmp_path: Path) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>', "xml-v30")
    result = checks(manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"'))
    assert result["android.cleartext"]["status"] == "unknown"


def test_legacy_supported_devices_are_not_hidden_by_new_target_sdk(tmp_path: Path) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>')
    result = checks(manifest(tmp_path, 'android:usesCleartextTraffic="true" android:networkSecurityConfig="@xml/network"', minimum=23))
    assert result["android.cleartext"]["status"] == "review"
    result = checks(manifest(tmp_path, 'android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/network"', minimum=22))
    assert result["android.cleartext"]["status"] == "unknown"
    assert result["android.cleartext"]["complete"] is False


def test_target31_missing_export_is_unknown_not_private(tmp_path: Path) -> None:
    path = manifest(tmp_path, children='<activity android:name=".Entry"><intent-filter><action android:name="test"/></intent-filter></activity>', sdk=31)
    data = inspect_manifest(path)
    assert data["components"][0]["effective_exported"] is None
    assert checks(path)["android.exported_components"]["status"] == "unknown"


@pytest.mark.parametrize(("minimum", "expected"), [(16, "unknown"), (17, "pass")])
def test_provider_explicit_false_is_not_proof_on_api16(tmp_path: Path, minimum: int, expected: str) -> None:
    path = manifest(tmp_path, children='<provider android:name=".Store" android:exported="false"/>', minimum=minimum)
    assert checks(path)["android.exported_components"]["status"] == expected


def test_signature_inheritance_and_provider_read_write_are_both_considered(tmp_path: Path) -> None:
    path = manifest(tmp_path, 'android:permission="test.app.SIG"', '<activity android:name=".Entry" android:exported="true"/>')
    text = path.read_text(encoding="utf-8").replace("<application", '<permission android:name="test.app.SIG" android:protectionLevel="signature"/><application')
    path.write_text(text, encoding="utf-8")
    assert checks(path)["android.exported_components"]["status"] == "pass"
    path.write_text(text.replace('<activity android:name=".Entry" android:exported="true"/>', '<provider android:name=".Store" android:exported="true" android:readPermission=""/>'), encoding="utf-8")
    assert checks(path)["android.exported_components"]["status"] == "review"


def test_deep_link_auto_verify_never_becomes_verified_domain(tmp_path: Path) -> None:
    path = manifest(tmp_path, children='''<activity android:name=".Entry" android:exported="true"><intent-filter android:autoVerify="true"><action android:name="android.intent.action.VIEW"/><category android:name="android.intent.category.BROWSABLE"/><data android:scheme="https"/><data android:host="app.test"/></intent-filter></activity>''')
    result = checks(path)["android.deeplinks"]
    assert result["status"] == "unknown"
    assert result["facts"][0]["value"]["domain_verification"] == "not_performed"
    assert result["facts"][0]["value"]["hosts"] == ["app.test"]


def test_component_fact_budget_does_not_turn_partial_capture_into_pass(tmp_path: Path) -> None:
    path = manifest(tmp_path, children="".join(f'<activity android:name=".Entry{index}" android:exported="false"/>' for index in range(230)))
    data = inspect_manifest(path)
    check = checks(path)["android.exported_components"]
    assert len(data["components"]) == 200 and data["security_review"]["coverage"]["truncated"]
    assert check["status"] == "unknown" and check["complete"] is False
    assert len(check["facts"]) == 80


def test_missing_application_and_target_sdk_are_unknown(tmp_path: Path) -> None:
    path = tmp_path / "AndroidManifest.xml"
    path.write_text(f'<manifest {NS} package="test.app"/>', encoding="utf-8")
    result = checks(path)
    assert all(check["status"] == "unknown" for check in result.values())


def test_xml_depth_and_utf16_declarations_are_rejected(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    path.write_text("<manifest>" + "<node>" * 45 + "</node>" * 45 + "</manifest>", encoding="utf-8")
    with pytest.raises(IngestError, match="depth"):
        inspect_security_review(path)
    path.write_bytes('<!DOCTYPE x [<!ENTITY a "x">]><manifest/>'.encode("utf-16"))
    with pytest.raises(IngestError, match="declarations"):
        inspect_manifest(path)


def test_manifest_and_full_module_share_saved_configuration(tmp_path: Path) -> None:
    from reachscope_workbench.core.models import ModuleResult
    from reachscope_workbench.modules.android.module import _apply_configuration

    configuration = inspect_manifest(manifest(tmp_path, 'android:debuggable="true"'))
    result = ModuleResult(module="android", target="sample", summary={}, details={"components": []})
    _apply_configuration(result, configuration)
    assert result.details["target_sdk"] == 30
    assert result.details["security_review"] == configuration["security_review"]
    assert len(result.evidence) == 8
    assert all(item.sha256 and item.kind == "android_configuration_review" for item in result.evidence)
    assert all(item.id.startswith("android-config:") and item.confidence != "confirmed" for item in result.observations)


def test_code_worker_reuses_actual_code_engine_and_preserves_sdk_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope import __file__ as engine_file

    assert engine_file
    source = Path(engine_file).parent / "samples" / "cross_component"
    apk = tmp_path / "input.apk"
    apk.write_bytes(b"fixture")
    monkeypatch.setattr(code_worker.ApkInput, "load", lambda path: type("Input", (), {"path": apk, "sha256": "a" * 64})())
    monkeypatch.setattr(code_worker, "resolve_apktool", lambda _: ["fake-java"])
    monkeypatch.setattr(code_worker, "check_apktool_version", lambda _: "2.11.1")

    def decode(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        destination = Path(command[command.index("-o") + 1])
        shutil.copytree(source, destination)
        path = destination / "AndroidManifest.xml"
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        sdk = root.find("uses-sdk")
        assert sdk is not None
        root.remove(sdk)
        path.write_bytes(ET.tostring(root))
        (destination / "apktool.yml").write_text("sdkInfo:\n  minSdkVersion: '24'\n  targetSdkVersion: '33'\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(code_worker.subprocess, "run", decode)
    monkeypatch.setattr(sys, "argv", ["code-worker", str(apk), "--out", str(tmp_path / "scan"), "--store", str(tmp_path / "artifacts"), "--no-apkid"])
    assert code_worker.main() == 0
    data = json.loads((tmp_path / "scan" / "manifest-result.json").read_text(encoding="utf-8"))
    identity = json.loads((tmp_path / "scan" / "artifact.json").read_text(encoding="utf-8"))["artifact_id"]
    report = json.loads((tmp_path / "artifacts" / identity / "report.json").read_text(encoding="utf-8"))
    assert data["target_sdk"] == report["meta"]["target_sdk"] == 33
    assert not list(tmp_path.glob("android-*"))


@pytest.mark.parametrize("payload", [None, "not json", "[]", '{"security_review":{}}'])
def test_missing_or_malformed_worker_configuration_is_rejected(tmp_path: Path, payload: str | None) -> None:
    from reachscope_workbench.modules.android.module import _read_configuration

    path = tmp_path / "manifest-result.json"
    if payload is not None:
        path.write_text(payload, encoding="utf-8")
    with pytest.raises((TypeError, ValueError, OSError)):
        _read_configuration(path)


def test_resource_budget_and_duplicate_base_never_imply_safe_network(tmp_path: Path) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config cleartextTrafficPermitted="false"/><base-config cleartextTrafficPermitted="true"/></network-security-config>')
    path = manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"')
    assert checks(path)["android.cleartext"]["status"] == "unknown"
    for index in range(17):
        resource(tmp_path, "network", '<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>', f"xml-v{index + 20}")
    review = inspect_manifest(path)["security_review"]
    assert review["coverage"]["resources_total"] == 18
    assert checks(path)["android.cleartext"]["complete"] is False


def test_empty_trust_anchor_declaration_is_unknown(tmp_path: Path) -> None:
    resource(tmp_path, "network", '<network-security-config><base-config><trust-anchors/></base-config></network-security-config>')
    path = manifest(tmp_path, 'android:networkSecurityConfig="@xml/network"')
    assert checks(path)["android.trust_anchors"]["status"] == "unknown"


def test_decoder_failure_is_visible_and_temporary_data_is_cleaned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apk = tmp_path / "input.apk"
    apk.write_bytes(b"fixture")
    monkeypatch.setattr(code_worker.ApkInput, "load", lambda path: type("Input", (), {"path": apk, "sha256": "a" * 64})())
    monkeypatch.setattr(code_worker, "resolve_apktool", lambda _: ["fake-java"])
    monkeypatch.setattr(code_worker, "check_apktool_version", lambda _: "2.11.1")
    monkeypatch.setattr(code_worker.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1))
    monkeypatch.setattr(sys, "argv", ["code-worker", str(apk), "--out", str(tmp_path / "scan"), "--store", str(tmp_path / "artifacts"), "--no-apkid"])
    assert code_worker.main() == 2
    assert not list(tmp_path.glob("android-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, "not json", '{"security_review":{}}'])
async def test_incomplete_apk_worker_fails_with_structured_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str | None) -> None:
    from reachscope_workbench.core.models import RunContext, WorkbenchError
    from reachscope_workbench.modules.android import module as android
    from reachscope_workbench.modules.android.process import ProcessResult

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    identity = "a" * 32
    with zipfile.ZipFile(uploads / identity, "w") as archive:
        archive.writestr("AndroidManifest.xml", "fixture")

    async def worker(command: list[str], **kwargs: Any) -> ProcessResult:
        output = Path(command[command.index("--out") + 1])
        output.mkdir()
        (output / "artifact.json").write_text(json.dumps({"artifact_id": "b" * 64}), encoding="utf-8")
        if payload is not None:
            (output / "manifest-result.json").write_text(payload, encoding="utf-8")
        return ProcessResult(0, "", "")

    monkeypatch.setattr(android, "run_process", worker)
    monkeypatch.setattr(android, "_apktool_path", lambda _: "fixture.jar")
    context = RunContext(job_id="fixture", workspace=tmp_path / "job", uploads=uploads, progress=lambda percent, message: None)
    with pytest.raises(WorkbenchError) as caught:
        await android.AndroidModule().run({"mode": "apk", "upload_id": identity}, context)
    assert caught.value.code == "WORKER_OUTPUT_INVALID"
