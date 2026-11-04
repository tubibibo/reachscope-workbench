"""Independent Android semantics regressions against documented platform behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from reachscope.extract.deeplinks import MAX_DEEPLINKS, extract_deeplinks
from reachscope.ingest.apk import IngestError
from reachscope.ingest.manifest import parse_manifest
from reachscope_workbench.modules.android.posture import inspect_security_review


def manifest(tmp_path: Path, body: str, *, sdk: int | None = 34,
             application: str = "", declarations: str = "") -> Path:
    path = tmp_path / "AndroidManifest.xml"
    uses = f'<uses-sdk android:minSdkVersion="23" android:targetSdkVersion="{sdk}"/>' if sdk is not None else ""
    path.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="example.audit">'
        + uses + declarations + f'<application {application}>' + body + '</application></manifest>',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("sdk,exported", [(16, True), (17, False), (34, False)])
def test_provider_without_filter_has_sdk_specific_default(tmp_path: Path, sdk: int, exported: bool) -> None:
    info = parse_manifest(manifest(tmp_path, '<provider android:name=".Data" android:authorities="example.audit"/>', sdk=sdk))
    assert info.components[0].exported is exported
    assert info.components[0].exported_inferred is True


def test_unknown_provider_sdk_is_visible_not_silently_private(tmp_path: Path) -> None:
    info = parse_manifest(manifest(tmp_path, '<provider android:name=".Data"/>', sdk=None))
    assert info.components[0].exported is True
    assert any("provider" in warning and "targetSdk" in warning for warning in info.warnings)


def test_target31_missing_exported_is_install_requirement_not_safe_default(tmp_path: Path) -> None:
    info = parse_manifest(manifest(tmp_path, '<activity android:name=".Main"><intent-filter><action android:name="example.VIEW"/></intent-filter></activity>'))
    # The inherited IR is bool-only. Its warning MUST disclose that false here
    # is not proof of an installable private activity.
    assert info.components[0].exported_inferred is True
    assert any("Android 12+" in warning and "android:exported" in warning for warning in info.warnings)


@pytest.mark.parametrize("value", ["@bool/exported", "maybe", "1"])
def test_unresolved_exported_value_does_not_hide_a_candidate(tmp_path: Path, value: str) -> None:
    info = parse_manifest(manifest(tmp_path, f'<activity android:name=".Main" android:exported="{value}"/>'))
    assert info.components[0].exported is True
    assert info.components[0].exported_inferred is True
    assert info.warnings


def test_components_inherit_application_permission_but_empty_explicit_value_clears_it(tmp_path: Path) -> None:
    info = parse_manifest(manifest(tmp_path,
        '<activity android:name=".Inherited" android:exported="true"/>'
        '<service android:name=".Cleared" android:exported="true" android:permission=""/>',
        application='android:permission="example.audit.SIGNATURE"',
        declarations='<permission android:name="example.audit.SIGNATURE" android:protectionLevel="signature"/>',
    ))
    assert info.components[0].permission == "example.audit.SIGNATURE"
    assert info.components[0].permission_protection == "signature"
    assert info.components[1].permission is None and info.components[1].permission_protection is None


def test_alias_does_not_borrow_target_activity_permission(tmp_path: Path) -> None:
    info = parse_manifest(manifest(tmp_path,
        '<activity android:name=".Main" android:exported="false" android:permission="example.audit.SIGNATURE"/>'
        '<activity-alias android:name=".Alias" android:targetActivity=".Main" android:exported="true"/>',
        application='android:permission="example.audit.SIGNATURE"',
        declarations='<permission android:name="example.audit.SIGNATURE" android:protectionLevel="signature"/>',
    ))
    assert info.components[1].permission is None
    assert info.components[1].permission_protection is None


@pytest.mark.parametrize("override", ['android:readPermission=""', 'android:writePermission="example.audit.OTHER"', 'android:grantUriPermissions="true"'])
def test_provider_overrides_do_not_borrow_one_signature_gate_as_complete_proof(tmp_path: Path, override: str) -> None:
    info = parse_manifest(manifest(tmp_path, f'<provider android:name=".Data" android:exported="true" {override}/>',
        application='android:permission="example.audit.SIGNATURE"',
        declarations='<permission android:name="example.audit.SIGNATURE" android:protectionLevel="signature"/>',
    ))
    assert info.components[0].permission_protection == "unknown"
    assert info.warnings


def test_custom_permission_without_protection_uses_normal_default(tmp_path: Path) -> None:
    info = parse_manifest(manifest(tmp_path, '<activity android:name=".Main" android:permission="example.audit.P"/>',
        declarations='<permission android:name="example.audit.P"/>'))
    assert info.components[0].permission_protection == "normal"


def links_manifest(tmp_path: Path, data: str) -> Path:
    return manifest(tmp_path, '<activity android:name=".Main" android:exported="true"><intent-filter>'
        '<action android:name="android.intent.action.VIEW"/><category android:name="android.intent.category.BROWSABLE"/>'
        + data + '</intent-filter></activity>')


def test_data_siblings_contribute_shared_scheme_host_and_path_sets(tmp_path: Path) -> None:
    info = parse_manifest(links_manifest(tmp_path,
        '<data android:scheme="https"/><data android:scheme="custom"/>'
        '<data android:host="one.example"/><data android:host="two.example"/><data android:pathPrefix="/open"/>'))
    assert len(info.components[0].intent_filters) == 1
    links = extract_deeplinks(info.components, info.package)
    assert {(link.scheme, link.host, link.path) for link in links} == {
        (scheme, host, "/open") for scheme in ("https", "custom") for host in ("one.example", "two.example")
    }


def test_path_without_host_is_ignored_in_candidate_url(tmp_path: Path) -> None:
    info = parse_manifest(links_manifest(tmp_path, '<data android:scheme="custom" android:path="/ignored"/>'))
    assert [(link.host, link.path) for link in extract_deeplinks(info.components, info.package)] == [("", "")]


def test_large_declaration_crossproduct_is_bounded_and_discloses_incomplete_coverage(tmp_path: Path) -> None:
    data = ''.join(f'<data android:scheme="app{i}"/>' for i in range(50))
    data += ''.join(f'<data android:host="h{i}.example"/>' for i in range(50))
    info = parse_manifest(links_manifest(tmp_path, data))
    assert len(extract_deeplinks(info.components, info.package)) == MAX_DEEPLINKS
    assert any("2000" in warning for warning in info.warnings)


@pytest.mark.parametrize("data", ['<data android:mimeType="image/png"/>', '<data android:pathSuffix=".pdf"/>', '<data android:pathAdvancedPattern="/v/[0-9]+"/>'])
def test_unsupported_matcher_semantics_are_not_silently_complete(tmp_path: Path, data: str) -> None:
    info = parse_manifest(links_manifest(tmp_path, '<data android:scheme="https" android:host="example.test"/>' + data))
    assert any("完整系统匹配" in warning for warning in info.warnings)


def review_check(path: Path, identifier: str, *, sdk: int | None = 34,
                 minimum: int | None = 23) -> dict[str, object]:
    review = inspect_security_review(path, target_sdk=sdk, min_sdk=minimum)
    return next(row for row in review["checks"] if row["id"] == identifier)  # type: ignore[no-any-return]


def test_posture_rejects_utf16_document_entity_declarations(tmp_path: Path) -> None:
    path = tmp_path / "AndroidManifest.xml"
    path.write_bytes('<!DOCTYPE manifest [<!ENTITY flag "false">]><manifest><application/></manifest>'.encode("utf-16"))
    with pytest.raises(IngestError):
        inspect_security_review(path)


@pytest.mark.parametrize("attribute", ["debuggable", "testOnly", "usesCleartextTraffic"])
def test_unresolved_boolean_does_not_become_a_safe_default(tmp_path: Path, attribute: str) -> None:
    path = manifest(tmp_path, "", application=f'android:{attribute}="@bool/unresolved"')
    identifier = {"debuggable": "debuggable", "testOnly": "test_only", "usesCleartextTraffic": "cleartext"}[attribute]
    check = review_check(path, "android." + identifier)
    assert check["status"] == "unknown" and check["complete"] is False


def test_explicit_private_provider_cannot_prove_private_on_supported_api16(tmp_path: Path) -> None:
    path = manifest(tmp_path, '<provider android:name=".Data" android:exported="false"/>')
    check = review_check(path, "android.exported_components", minimum=16)
    assert check["status"] == "unknown" and check["complete"] is False


def test_missing_network_resource_cannot_clear_manifest_flag(tmp_path: Path) -> None:
    path = manifest(tmp_path, "", application='android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/missing"')
    for identifier in ("android.cleartext", "android.trust_anchors"):
        check = review_check(path, identifier, minimum=24)
        assert check["status"] == "unknown" and check["complete"] is False


def test_qualified_resource_exception_is_not_hidden_by_safe_base_variant(tmp_path: Path) -> None:
    path = manifest(tmp_path, "", application='android:networkSecurityConfig="@xml/security"')
    base = tmp_path / "res" / "xml"
    variant = tmp_path / "res" / "xml-v28"
    base.mkdir(parents=True)
    variant.mkdir()
    (base / "security.xml").write_text('<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>', encoding="utf-8")
    (variant / "security.xml").write_text('<network-security-config><domain-config cleartextTrafficPermitted="true"><domain>legacy.example</domain></domain-config></network-security-config>', encoding="utf-8")
    check = review_check(path, "android.cleartext")
    assert check["status"] == "review"
    assert any(fact["source"] == "res/xml-v28/security.xml" for fact in check["facts"])  # type: ignore[union-attr,index]


def test_resource_scope_overflow_cannot_report_complete_safe_configuration(tmp_path: Path) -> None:
    path = manifest(tmp_path, "", application='android:networkSecurityConfig="@xml/security"')
    for index in range(18):
        folder = tmp_path / "res" / ("xml" if index == 0 else f"xml-v{index + 20}")
        folder.mkdir(parents=True)
        (folder / "security.xml").write_text('<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>', encoding="utf-8")
    check = review_check(path, "android.cleartext")
    assert check["status"] == "unknown" and check["complete"] is False


def test_autoverify_only_declares_request_not_successful_domain_ownership(tmp_path: Path) -> None:
    path = manifest(tmp_path, '<activity android:name=".Main" android:exported="true"><intent-filter android:autoVerify="true">'
        '<action android:name="android.intent.action.VIEW"/><category android:name="android.intent.category.BROWSABLE"/>'
        '<data android:scheme="https" android:host="example.test"/></intent-filter></activity>')
    check = review_check(path, "android.deeplinks")
    assert check["status"] != "pass"
    assert "未验证" in str(check["description"])
