"""T2.4 单测：@JavascriptInterface 识别、注册点、impl_class 回溯、revoked 全 APK 匹配。

真实场景用 `cases/01`（单桥）与 `cases/06`（双桥只撤销一个）；
两个退化场景（未注册、obj 来自字段）用 `tests/fixtures/smali/` 的新 fixture。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reachscope.extract.bridge import extract_bridges
from reachscope.ingest.smali import SmaliIndex, build_index, index_smali_file
from reachscope.ir.model import ExposedTo

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"
CASES = FIXTURES / "cases"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def by_class(bridges, impl_class: str):
    return next(b for b in bridges if b.impl_class == impl_class)


# --- 真实 fixture ----------------------------------------------------------


def test_case01_single_bridge() -> None:
    warnings: list[str] = []
    bridges = extract_bridges(build_index(CASES / "01_positive_deeplink_bridge_sink"), warnings)
    assert len(bridges) == 1
    bridge = bridges[0]
    assert bridge.impl_class == "com.example.app.JsBridge"
    assert bridge.revoked is False
    assert bridge.revoke_at is None
    assert bridge.exposed_to is ExposedTo.ALL_PAGES  # v0.1 恒为 all_pages（D-044）
    assert bridge.registered_in is not None
    assert bridge.registered_in.file == "smali/com/example/app/MainActivity.smali"
    assert bridge.registered_in.line == 40
    assert bridge.registered_in.snippet.startswith("invoke-virtual")
    assert len(bridge.id) == 8
    assert warnings == []


def test_case01_bridge_methods_and_params() -> None:
    bridges = extract_bridges(build_index(CASES / "01_positive_deeplink_bridge_sink"), [])
    methods = bridges[0].methods
    assert [m.name for m in methods] == ["getVersion", "readFile"]
    read_file = next(m for m in methods if m.name == "readFile")
    assert read_file.params == ["Ljava/lang/String;"]
    assert read_file.source is not None
    assert read_file.source.file == "smali/com/example/app/JsBridge.smali"


def test_case06_partial_revoke() -> None:
    """两个桥，只撤销 debug → DebugBridge.revoked=True，JsBridge 仍为 False。"""
    bridges = extract_bridges(build_index(CASES / "06_bridge_partial_revoke"), [])
    assert len(bridges) == 2

    native = by_class(bridges, "com.example.app.JsBridge")
    debug = by_class(bridges, "com.example.app.DebugBridge")
    assert native.revoked is False
    assert debug.revoked is True
    assert debug.revoke_at is not None
    assert debug.revoke_at.file == "smali/com/example/app/MainActivity.smali"
    assert debug.revoke_at.line == 52


def test_bridge_ids_are_stable_and_unique() -> None:
    case = CASES / "06_bridge_partial_revoke"
    first = extract_bridges(build_index(case), [])
    second = extract_bridges(build_index(case), [])
    assert [b.id for b in first] == [b.id for b in second]
    assert len({b.id for b in first}) == len(first)


# --- 退化场景（D-043） ------------------------------------------------------


def test_unregistered_annotated_class_is_not_a_bridge() -> None:
    """只有注解、从未注册 → 不产出 Bridge，但必须记 warning（进 Meta.warnings）。"""
    warnings: list[str] = []
    bridges = extract_bridges(index_of("UnregisteredBridge.smali"), warnings)
    assert bridges == []
    assert len(warnings) == 1
    assert "com.example.app.UnregisteredBridge" in warnings[0]
    assert "未被注册" in warnings[0]


def test_unregistered_class_still_reported_when_another_bridge_exists() -> None:
    warnings: list[str] = []
    bridges = extract_bridges(
        index_of("WebViewCallsites.smali", "JsBridge.smali", "UnregisteredBridge.smali"),
        warnings,
    )
    assert [b.impl_class for b in bridges] == ["com.example.app.JsBridge"]
    assert any("UnregisteredBridge" in w for w in warnings)


def test_obj_from_field_leaves_impl_class_empty() -> None:
    """obj 回溯不到 new-instance → impl_class 留空 + warning，不猜类名。"""
    warnings: list[str] = []
    bridges = extract_bridges(index_of("BridgeObjFromField.smali"), warnings)
    assert len(bridges) == 1
    assert bridges[0].impl_class == ""
    assert bridges[0].methods == []
    assert any("new-instance" in w for w in warnings)


def test_no_warnings_container_is_allowed() -> None:
    """不传 warnings 列表时只写日志，不能崩。"""
    assert extract_bridges(index_of("UnregisteredBridge.smali")) == []


def test_no_bridge_at_all() -> None:
    assert extract_bridges(index_of("AbstractBase.smali"), []) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
