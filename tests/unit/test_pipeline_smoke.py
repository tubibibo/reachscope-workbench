"""工程规范化：9 个 case 端到端冒烟 + 序列化确定性。

不加载 expected.json（那是 T5.1），只断言：
1. 对每个 fixture case 跑一次完整提取管线不抛异常；
2. 同一 case 连续两次跑，逐字段（去 dict）序列化结果完全相同；
3. 所有 `id` 是 8 位十六进制；
4. 所有 `SourceLoc.file` 相对路径（无绝对前缀、无反斜杠）。
"""

from __future__ import annotations

import re
from pathlib import Path

from reachscope.extract.bridge import extract_bridges
from reachscope.extract.components import resolve_components
from reachscope.extract.deeplinks import extract_deeplinks
from reachscope.extract.origin import attach_origin_checks, collect_origin_checks
from reachscope.extract.sinks import attach_bridge_sinks
from reachscope.extract.webview import extract_webviews
from reachscope.ingest.manifest import parse_manifest
from reachscope.ingest.smali import build_index

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"

ID_RE = re.compile(r"^[0-9a-f]{8}$")
ABSOLUTE_WINDOWS = re.compile(r"^[A-Za-z]:[\\/]")
ABSOLUTE_POSIX = re.compile(r"^/")
BACKSLASH = re.compile(r"\\")


def case_dirs() -> list[Path]:
    return sorted(d for d in CASES.iterdir() if d.is_dir())


def snapshot(case: Path) -> dict:
    """完整跑一次提取管线并序列化（用于确定性对比）。"""
    manifest = parse_manifest(case / "AndroidManifest.xml")
    index = build_index(case)
    components = resolve_components(manifest, index)
    deeplinks = extract_deeplinks(components, manifest.package)
    webviews = extract_webviews(index)
    warnings: list[str] = []
    bridges = extract_bridges(index, warnings)
    bridges = attach_origin_checks(bridges, collect_origin_checks(index))
    bridges = attach_bridge_sinks(bridges, index, package=manifest.package)
    return {
        "manifest": manifest.to_dict(),
        "components": [c.to_dict() for c in components],
        "deeplinks": [d.to_dict() for d in deeplinks],
        "webviews": [w.to_dict() for w in webviews],
        "bridges": [b.to_dict() for b in bridges],
        "index_warnings": index.warnings,
        "bridge_warnings": warnings,
    }


# --- 不抛异常：纯冒烟 ---------------------------------------------------


def test_all_nine_cases_smoke() -> None:
    for case in case_dirs():
        snapshot(case)  # 不抛 = 通过


# --- 序列化确定性：同一 case 跑两次必须逐字段相同 -------------------------


def test_pipeline_is_deterministic_per_case() -> None:
    for case in case_dirs():
        first = snapshot(case)
        second = snapshot(case)
        assert first == second, f"{case.name} 两次快照不一致"


# --- ID 格式稳定：stable_id 的 8 位 sha1 前缀 ------------------------------


def test_all_ids_are_eight_hex_chars() -> None:
    """§4.7 的 IR（Deeplink / WebView / Bridge）必须有稳定 8 位 hex id；Component 不带 id。"""
    for case in case_dirs():
        snap = snapshot(case)
        for key in ("deeplinks", "webviews", "bridges"):
            for item in snap[key]:
                assert ID_RE.match(item["id"]), f"{case.name}.{key} id 非法：{item['id']!r}"


# --- SourceLoc.file 必须是相对路径（D-036） ------------------------------


def test_source_loc_files_are_relative() -> None:
    for case in case_dirs():
        snap = snapshot(case)
        # components 走 manifest 解析（SourceLoc.file = manifest 文件名，恒为相对）；
        # 其它带 source 字段的也要走相对路径
        for component in snap["components"]:
            assert component["source"]["file"] == "AndroidManifest.xml", case.name
        for key in ("deeplinks", "webviews", "bridges"):
            for item in snap[key]:
                source = item.get("source") or {}
                file = source.get("file") if isinstance(source, dict) else None
                if not file:
                    continue
                assert not ABSOLUTE_WINDOWS.match(file), f"{case.name}.{key} 绝对路径：{file}"
                assert not ABSOLUTE_POSIX.match(file), f"{case.name}.{key} 绝对路径：{file}"
                assert not BACKSLASH.search(file), f"{case.name}.{key} 含反斜杠：{file}"
