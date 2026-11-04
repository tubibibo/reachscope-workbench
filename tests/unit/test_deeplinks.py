"""T2.2 单测：VIEW+BROWSABLE 过滤、自定义 scheme、path/pathPrefix/pathPattern、id 稳定性。

manifest fixture 在 `tests/fixtures/manifests/`，另用 `cases/03_missing_impl` 的真实产物。
"""

from __future__ import annotations

from pathlib import Path

from reachscope.extract.components import resolve_components
from reachscope.extract.deeplinks import extract_deeplinks
from reachscope.ingest.manifest import parse_manifest
from reachscope.ingest.smali import build_index
from reachscope.ir.model import Deeplink
from reachscope.ir.serialize import stable_id

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"
MANIFESTS = Path(__file__).resolve().parent.parent / "fixtures" / "manifests"
PACKAGE = "com.example.app"


def resolved(name: str):
    """解析一个 manifest fixture 并做 T2.1 的规范化（组件名 → 全限定）。"""
    manifest = parse_manifest(MANIFESTS / name)
    return resolve_components(manifest, build_index(CASES / "01_positive_deeplink_bridge_sink"))


def as_set(deeplinks: list[Deeplink]) -> set[tuple[str, str, str, str]]:
    return {(d.component, d.scheme, d.host, d.path) for d in deeplinks}


# --- 真实 fixture（03） ----------------------------------------------------


def test_case03_custom_scheme_deeplink() -> None:
    """03：只有 HiddenActivity 有 BROWSABLE 的 VIEW filter。"""
    case = CASES / "03_missing_impl"
    manifest = parse_manifest(case / "AndroidManifest.xml")
    components = resolve_components(manifest, build_index(case))
    deeplinks = extract_deeplinks(components, manifest.package)

    assert as_set(deeplinks) == {
        ("com.example.app.HiddenActivity", "myapp", "hidden.example.com", "")
    }
    assert deeplinks[0].component == "com.example.app.HiddenActivity"  # 已规范化
    assert deeplinks[0].params == []
    assert deeplinks[0].auto_verify is False


# --- 过滤条件 --------------------------------------------------------------


def test_only_view_plus_browsable_produce_deeplinks() -> None:
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert as_set(deeplinks) == {
        ("com.example.app.DeepLinkActivity", "https", "a.example.com", "/open"),
        ("com.example.app.DeepLinkActivity", "https", "b.example.com", "/open"),
        ("com.example.app.DeepLinkActivity", "myapp", "x.example.com", "/detail/.*"),
        ("com.example.app.DeepLinkActivity", "http", "c.example.com", "/pre"),
    }


def test_missing_browsable_is_skipped() -> None:
    """缺 BROWSABLE 的 VIEW filter（ftp）不产出深链。"""
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert all(d.scheme != "ftp" for d in deeplinks)


def test_missing_scheme_is_skipped() -> None:
    """有 BROWSABLE 但无 <data>（无 scheme）→ 不产出，不默认 http（D-038）。"""
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert all(d.scheme for d in deeplinks)
    assert all(d.host != "" or d.path != "" or d.scheme == "https" for d in deeplinks)


def test_path_pattern_is_preserved_verbatim() -> None:
    """pathPattern 原样保留，不当字面量改写。"""
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    pattern = next(d for d in deeplinks if d.scheme == "myapp")
    assert pattern.path == "/detail/.*"
    assert pattern.auto_verify is True  # autoVerify 随 filter 传递


def test_path_prefix_becomes_path() -> None:
    """pathPrefix 已按 D-023 归入 paths，这里直接成为深链 path。"""
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert any(d.path == "/pre" for d in deeplinks)


def test_no_filters_means_no_deeplinks() -> None:
    components = resolved("all_component_types.xml")
    assert extract_deeplinks(components, PACKAGE) == []


# --- 确定性与 ID -----------------------------------------------------------


def test_ids_are_stable_and_unique() -> None:
    first = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    second = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert [d.id for d in first] == [d.id for d in second]
    assert len({d.id for d in first}) == len(first)
    assert all(len(d.id) == 8 for d in first)


def test_id_key_format() -> None:
    deeplink = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)[0]
    expected = stable_id(
        "deeplink", f"{deeplink.component}|{deeplink.scheme}://{deeplink.host}{deeplink.path}"
    )
    assert deeplink.id == expected


def test_result_is_sorted() -> None:
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    keys = [(d.component, d.scheme, d.host, d.path) for d in deeplinks]
    assert keys == sorted(keys)


def test_source_points_at_manifest() -> None:
    deeplinks = extract_deeplinks(resolved("deeplink_variants.xml"), PACKAGE)
    assert all(d.source is not None and d.source.file == "deeplink_variants.xml" for d in deeplinks)
