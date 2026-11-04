"""T1.2 单测：manifest 解析（exported 推断、权限级别、data 展开、autoVerify）。

输入是 `tests/fixtures/manifests/*.xml`，不依赖 apktool。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reachscope.ingest.apk import IngestError
from reachscope.ingest.manifest import (
    ManifestInfo,
    normalize_protection_level,
    parse_manifest,
    resolve_permission_protection,
)
from reachscope.ir.model import ComponentType

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "manifests"


def fixture(name: str) -> Path:
    """取一个 manifest fixture 的路径。"""
    return FIXTURES / name


def by_name(info: ManifestInfo, name: str):
    """按组件名取组件（未找到则断言失败）。"""
    for component in info.components:
        if component.name == name:
            return component
    raise AssertionError(f"找不到组件 {name}，现有：{[c.name for c in info.components]}")


# --- exported 推断三分支 ---------------------------------------------------


def test_exported_explicit_true_and_false() -> None:
    info = parse_manifest(fixture("exported_explicit.xml"))
    assert by_name(info, ".ExportedTrue").exported is True
    assert by_name(info, ".ExportedTrue").exported_inferred is False
    assert by_name(info, ".ExportedFalse").exported is False
    assert by_name(info, ".ExportedFalse").exported_inferred is False


def test_exported_default_without_filter_is_false() -> None:
    """分支三：无 intent-filter → false，且不算“推断”。"""
    info = parse_manifest(fixture("exported_explicit.xml"))
    main = by_name(info, ".MainActivity")
    assert main.exported is False
    assert main.exported_inferred is False


def test_exported_inferred_false_when_target_sdk_31() -> None:
    info = parse_manifest(fixture("exported_inferred_target31.xml"))
    activity = by_name(info, ".DeepLinkActivity")
    assert activity.exported is False
    assert activity.exported_inferred is True
    assert info.target_sdk == 31


def test_exported_inferred_true_when_target_sdk_below_31() -> None:
    info = parse_manifest(fixture("exported_inferred_below31.xml"))
    activity = by_name(info, ".LegacyDeepLinkActivity")
    assert activity.exported is True
    assert activity.exported_inferred is True


def test_no_filter_components_are_not_exported() -> None:
    info = parse_manifest(fixture("exported_no_filter.xml"))
    assert len(info.components) == 3
    assert all(component.exported is False for component in info.components)
    assert [component.exported_inferred for component in info.components] == [False, False, True]


def test_missing_target_sdk_is_explicitly_flagged() -> None:
    """targetSdk 缺失不能静默猜测：推断为 true 并写警告（D-022）。"""
    info = parse_manifest(fixture("no_target_sdk.xml"))
    activity = by_name(info, ".NoSdkActivity")
    assert info.target_sdk is None
    assert activity.exported is True
    assert activity.exported_inferred is True
    assert any("targetSdkVersion" in warning for warning in info.warnings)


# --- 权限保护级别 ----------------------------------------------------------


def test_declared_signature_permission_is_resolved() -> None:
    info = parse_manifest(fixture("permission_signature.xml"))
    assert by_name(info, ".InternalActivity").permission_protection == "signature"
    assert by_name(info, ".InternalActivity").permission == "com.example.app.SIGNATURE_PERM"


def test_unknown_third_party_permission_is_unknown() -> None:
    info = parse_manifest(fixture("permission_signature.xml"))
    assert by_name(info, ".UnknownPermActivity").permission_protection == "unknown"


def test_combo_protection_level_is_signature() -> None:
    """`signature|privileged` 只要含 signature 就是签名级。"""
    info = parse_manifest(fixture("permission_signature_combo.xml"))
    assert by_name(info, ".PrivActivity").permission_protection == "signature"


def test_numeric_protection_level_is_signature() -> None:
    info = parse_manifest(fixture("permission_signature_combo.xml"))
    assert by_name(info, ".NumericActivity").permission_protection == "signature"


def test_builtin_permission_table() -> None:
    info = parse_manifest(fixture("permission_builtin.xml"))
    assert by_name(info, ".CameraActivity").permission_protection == "dangerous"
    assert by_name(info, ".InternetActivity").permission_protection == "normal"
    assert by_name(info, ".UnlistedActivity").permission_protection == "unknown"


def test_component_without_permission_has_null_protection() -> None:
    info = parse_manifest(fixture("exported_explicit.xml"))
    assert by_name(info, ".MainActivity").permission is None
    assert by_name(info, ".MainActivity").permission_protection is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("normal", "normal"),
        ("dangerous", "dangerous"),
        ("signature", "signature"),
        ("signature|privileged", "signature"),
        ("dangerous|signature", "signature"),
        ("0x2", "signature"),
        ("2", "signature"),
        ("3", "signature"),
        ("0", "normal"),
        ("1", "dangerous"),
        ("", "unknown"),
        ("bogus", "unknown"),
        # AOSP 基础级别 = protectionLevel & 0xf（D-037）：
        # 0x12 = privileged|signature → 2 → signature（不是 unknown）
        ("0x12", "signature"),
        ("0x10", "normal"),
        ("0x11", "dangerous"),
    ],
)
def test_normalize_protection_level(raw: str, expected: str) -> None:
    assert normalize_protection_level(raw) == expected


def test_resolve_permission_protection_prefers_declared() -> None:
    declared = {"com.example.app.P": "dangerous"}
    assert resolve_permission_protection("com.example.app.P", declared) == "dangerous"
    assert resolve_permission_protection("android.permission.CAMERA", declared) == "dangerous"
    assert resolve_permission_protection("other.PERM", declared) == "unknown"
    assert resolve_permission_protection(None, declared) is None


# --- intent-filter 展开 ----------------------------------------------------


def test_multiple_data_elements_merge_within_the_same_filter() -> None:
    """Android merges data siblings within each intent-filter."""
    info = parse_manifest(fixture("data_multi.xml"))
    filters = by_name(info, ".MultiDataActivity").intent_filters
    assert len(filters) == 2
    assert filters[0].schemes == ["myapp", "https"]
    assert filters[0].hosts == ["open.example.com", "shop.example.com", "api.example.com"]
    assert filters[0].paths == ["/p/"]
    assert filters[0].path_patterns == ["/v/.*"]


def test_filter_without_data_keeps_actions_and_categories() -> None:
    info = parse_manifest(fixture("data_multi.xml"))
    no_data = by_name(info, ".MultiDataActivity").intent_filters[1]
    assert no_data.actions == ["android.intent.action.SEND"]
    assert no_data.categories == ["android.intent.category.DEFAULT"]
    assert no_data.schemes == []


def test_data_and_combination_within_one_element() -> None:
    info = parse_manifest(fixture("data_multi.xml"))
    first = by_name(info, ".MultiDataActivity").intent_filters[0]
    assert first.schemes == ["myapp", "https"]
    assert first.hosts == ["open.example.com", "shop.example.com", "api.example.com"]
    assert first.actions == ["android.intent.action.VIEW"]
    assert first.categories == [
        "android.intent.category.DEFAULT",
        "android.intent.category.BROWSABLE",
    ]


def test_auto_verify_is_read_from_intent_filter() -> None:
    info = parse_manifest(fixture("auto_verify.xml"))
    assert by_name(info, ".VerifiedActivity").intent_filters[0].auto_verify is True
    assert by_name(info, ".UnverifiedActivity").intent_filters[0].auto_verify is False


def test_expand_intent_filters_returns_empty_for_plain_component() -> None:
    info = parse_manifest(fixture("exported_no_filter.xml"))
    assert by_name(info, ".SilentActivity").intent_filters == []


# --- 组件类型与包信息 ------------------------------------------------------


def test_all_component_types_are_parsed() -> None:
    info = parse_manifest(fixture("all_component_types.xml"))
    assert [component.type for component in info.components] == [
        ComponentType.ACTIVITY,
        ComponentType.ACTIVITY_ALIAS,
        ComponentType.SERVICE,
        ComponentType.RECEIVER,
        ComponentType.PROVIDER,
    ]


def test_package_and_sdk_and_version() -> None:
    info = parse_manifest(fixture("all_component_types.xml"))
    assert info.package == "com.example.app"
    assert info.version_code == "42"
    assert info.version_name == "4.2"
    assert info.min_sdk == 24
    assert info.target_sdk == 34


def test_activity_alias_with_explicit_exported() -> None:
    info = parse_manifest(fixture("all_component_types.xml"))
    alias = by_name(info, "com.example.app.MainAlias")
    assert alias.type == ComponentType.ACTIVITY_ALIAS
    assert alias.exported is True
    assert alias.exported_inferred is False


def test_declared_permissions_are_collected() -> None:
    info = parse_manifest(fixture("permission_signature.xml"))
    assert info.permissions == {"com.example.app.SIGNATURE_PERM": "signature"}


def test_impl_present_is_true_until_t2_1() -> None:
    """TASKS T1.2：`impl_present` 本卡恒 True，由 T2.1 回填。"""
    info = parse_manifest(fixture("all_component_types.xml"))
    assert all(component.impl_present for component in info.components)


def test_source_loc_file_is_relative_filename() -> None:
    """§9.3 确定性：`SourceLoc.file` 不能是绝对临时路径（D-036）。"""
    info = parse_manifest(fixture("all_component_types.xml"))
    source = by_name(info, "com.example.app.MainActivity").source
    assert source is not None
    assert source.file == "all_component_types.xml"
    assert "<activity" in source.snippet
    assert len(source.snippet) <= 200


def test_activity_alias_exposes_target_activity() -> None:
    """D-032b：alias 的实现存在性依赖 `android:targetActivity`。"""
    info = parse_manifest(fixture("activity_alias.xml"))
    alias = by_name(info, ".LauncherAlias")
    assert alias.type.value == "activity-alias"
    assert alias.target_activity == ".MainActivity"
    assert by_name(info, ".MainActivity").target_activity is None


# --- SDK 版本：manifest > apktool.yml > None（D-054） ----------------------


def workdir_with(tmp_path: Path, manifest: str, yml: str | None) -> Path:
    """把 manifest（可带 `uses-sdk`）与可选的 apktool.yml 摆进同一个临时目录。"""
    path = tmp_path / "AndroidManifest.xml"
    path.write_text((FIXTURES / manifest).read_text(encoding="utf-8"), encoding="utf-8")
    if yml is not None:
        (tmp_path / "apktool.yml").write_text(yml, encoding="utf-8")
    return path


APKTOOL_YML_OK = """version: 2.11.1
apkFileName: k9mail-24.0.apk
sdkInfo:
  minSdkVersion: 23
  targetSdkVersion: 36
"""


def test_manifest_uses_sdk_wins_over_apktool_yml(tmp_path: Path) -> None:
    """优先级：manifest 显式值 > apktool.yml。"""
    path = workdir_with(tmp_path, "exported_inferred_target31.xml", APKTOOL_YML_OK)
    info = parse_manifest(path)
    assert info.target_sdk == 31  # 不是 yml 的 36
    assert info.min_sdk == 23


def test_sdk_falls_back_to_apktool_yml(tmp_path: Path) -> None:
    """manifest 里没有 `<uses-sdk>`（真实 apktool 输出）→ 回退 apktool.yml。"""
    path = workdir_with(tmp_path, "no_uses_sdk.xml", APKTOOL_YML_OK)
    info = parse_manifest(path)
    assert info.target_sdk == 36
    assert info.min_sdk == 23
    # 拿到 targetSdk 后，D-022 才能走“>=31 → 默认不导出”这条真机规则
    activity = by_name(info, ".DeepLinkActivity")
    assert activity.exported is False
    assert activity.exported_inferred is True
    assert not any("未声明 targetSdkVersion" in w for w in info.warnings)


def test_sdk_is_none_when_both_sources_missing(tmp_path: Path) -> None:
    """两者都没有 → None，保持 D-022 的“未声明”路径 + 告警。"""
    path = workdir_with(tmp_path, "no_uses_sdk.xml", None)
    info = parse_manifest(path)
    assert info.target_sdk is None
    assert info.min_sdk is None
    assert any("未声明 targetSdkVersion" in w for w in info.warnings)


def test_broken_apktool_yml_is_reported_and_ignored(tmp_path: Path) -> None:
    """yml 损坏 / 值非法 → 按“未解析”处理，记 warning，不抛异常。"""
    broken = "sdkInfo:\n  minSdkVersion: 'not-a-number'\n  targetSdkVersion: ??\n"
    path = workdir_with(tmp_path, "no_uses_sdk.xml", broken)
    info = parse_manifest(path)
    assert info.target_sdk is None
    assert info.min_sdk is None
    assert any("无法解析" in w for w in info.warnings)


def test_apktool_yml_without_sdk_block_is_ignored(tmp_path: Path) -> None:
    """有 yml 但没有 sdkInfo 块 → 静默忽略，不加 warning。"""
    path = workdir_with(tmp_path, "no_uses_sdk.xml", "version: 2.11.1\ndoNotCompress:\n  - arsc\n")
    info = parse_manifest(path)
    assert info.target_sdk is None
    # 没有 sdkInfo 块本身不算“未解析”，不该额外刷 warning（D-022 的告警仍在）
    assert not any("apktool.yml" in w or "无法解析" in w for w in info.warnings)


# --- 异常与边界 ------------------------------------------------------------


def test_broken_xml_raises_ingest_error() -> None:
    with pytest.raises(IngestError) as excinfo:
        parse_manifest(fixture("broken.xml"))
    assert excinfo.value.reason == "manifest parse failed"


def test_missing_file_raises_ingest_error(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        parse_manifest(tmp_path / "nope.xml")


def test_non_manifest_root_raises_ingest_error(tmp_path: Path) -> None:
    path = tmp_path / "other.xml"
    path.write_text("<resources />", encoding="utf-8")
    with pytest.raises(IngestError) as excinfo:
        parse_manifest(path)
    assert excinfo.value.reason == "manifest parse failed"


def test_missing_application_is_reported_not_silently_empty() -> None:
    info = parse_manifest(fixture("no_application.xml"))
    assert info.components == []
    assert any("application" in warning for warning in info.warnings)


def test_non_component_children_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "AndroidManifest.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"'
        ' package="com.example.app">\n'
        '  <uses-sdk android:targetSdkVersion="33" />\n'
        "  <application>\n"
        '    <meta-data android:name="x" android:value="1" />\n'
        '    <activity android:name=".A" android:exported="true" />\n'
        "  </application>\n"
        "</manifest>\n",
        encoding="utf-8",
    )
    info = parse_manifest(path)
    assert [component.name for component in info.components] == [".A"]
