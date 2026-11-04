"""T2.6 单测：八类汇点、medium≡shared 映射、own/unknown 判定、桥方法回填。"""

from __future__ import annotations

from pathlib import Path

from reachscope.extract.bridge import extract_bridges
from reachscope.extract.sinks import attach_bridge_sinks, scan_method_sinks
from reachscope.ingest.smali import SmaliIndex, build_index, index_smali_file
from reachscope.ir.model import Ownership, SinkKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"
CASES = FIXTURES / "cases"
PACKAGE = "com.example.app"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def method_of(index: SmaliIndex, descriptor: str, name: str):
    class_info = index.get_class(descriptor)
    assert class_info is not None
    method = class_info.method(name)
    assert method is not None
    return method


# --- 八类全识别 ------------------------------------------------------------


def test_all_eight_kinds_are_recognized() -> None:
    index = index_of("SinksAll.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")
    sinks = scan_method_sinks(method, package=PACKAGE)
    kinds = {sink.kind for sink in sinks}
    assert kinds == set(SinkKind) - {SinkKind.UNKNOWN}  # unknown 是兜底值，不是一类汇点


def test_ownership_mapping() -> None:
    """§5.7 的 medium ≡ shared（D-050）；high/cross-app/own 各自到位。"""
    index = index_of("SinksAll.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")
    sinks = scan_method_sinks(method, package=PACKAGE)
    by_kind = {sink.kind: sink.ownership for sink in sinks}

    assert by_kind[SinkKind.FILE] is Ownership.OWN  # 方法内有 getCacheDir
    assert by_kind[SinkKind.EXTERNAL_STORAGE] is Ownership.SHARED
    assert by_kind[SinkKind.CONTENT_PROVIDER] is Ownership.CROSS_APP
    assert by_kind[SinkKind.COMMAND_EXEC] is Ownership.HIGH
    assert by_kind[SinkKind.CROSS_COMPONENT] is Ownership.SHARED  # medium ≡ shared
    assert by_kind[SinkKind.WEBVIEW] is Ownership.SHARED  # medium ≡ shared
    assert by_kind[SinkKind.CLIPBOARD] is Ownership.SHARED  # medium ≡ shared
    assert by_kind[SinkKind.RESULT_CALLBACK] is Ownership.HIGH


def test_own_authority_downgrades_provider() -> None:
    """URI 指向自身 authority → own（否则一律 cross-app，D-051）。"""
    index = index_of("SinksAll.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")
    sinks = scan_method_sinks(
        method,
        own_authorities=frozenset({"com.other.provider"}),
        package=PACKAGE,
    )
    provider = next(s for s in sinks if s.kind is SinkKind.CONTENT_PROVIDER)
    assert provider.ownership is Ownership.OWN


def test_package_prefix_counts_as_own_authority() -> None:
    index = index_of("SinksAll.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")
    sinks = scan_method_sinks(
        method,
        own_authorities=frozenset(),
        package="com.other",  # authority 以包名开头也算自身
    )
    provider = next(s for s in sinks if s.kind is SinkKind.CONTENT_PROVIDER)
    assert provider.ownership is Ownership.OWN


# --- 无法判定 → unknown ----------------------------------------------------


def test_file_without_directory_signal_is_unknown() -> None:
    """没有目录信号 → unknown，**不默认 own**（会把 impact 静默压低）。"""
    index = index_of("SinksUnknown.smali")
    method = method_of(index, "Lcom/example/app/SinkUnknownActivity;", "sinkUnknownFile()V")
    sinks = scan_method_sinks(method, package=PACKAGE)
    assert [s.ownership for s in sinks] == [Ownership.UNKNOWN]


def test_cross_component_without_intent_data_is_unknown() -> None:
    index = index_of("SinksUnknown.smali")
    method = method_of(index, "Lcom/example/app/SinkUnknownActivity;", "sinkNoData()V")
    sinks = scan_method_sinks(method, package=PACKAGE)
    cross = next(s for s in sinks if s.kind is SinkKind.CROSS_COMPONENT)
    assert cross.ownership is Ownership.UNKNOWN


# --- 真实 fixture（07 自身 cache） -----------------------------------------


def test_case07_cache_dir_is_own() -> None:
    case = CASES / "07_own_cache_only"
    index = build_index(case)
    bridges = extract_bridges(index, [])
    annotated = attach_bridge_sinks(bridges, index, package=PACKAGE)
    bridge = next(b for b in annotated if b.impl_class == "com.example.app.JsBridge")
    read_cache = next(m for m in bridge.methods if m.name == "readCache")
    assert read_cache.sinks
    assert all(s.kind is SinkKind.FILE for s in read_cache.sinks)
    assert all(s.ownership is Ownership.OWN for s in read_cache.sinks)


def test_case01_bridge_sinks() -> None:
    """01 的 readFile：路径直接来自 JS 实参（`new File(p1)`）→ cross-app（D-057）。"""
    case = CASES / "01_positive_deeplink_bridge_sink"
    index = build_index(case)
    bridges = extract_bridges(index, [])
    annotated = attach_bridge_sinks(bridges, index, package=PACKAGE)
    read_file = next(m for m in annotated[0].methods if m.name == "readFile")
    assert read_file.sinks
    assert all(s.kind is SinkKind.FILE for s in read_file.sinks)
    assert any(s.ownership is Ownership.CROSS_APP for s in read_file.sinks)
    # `File` 与 `FileInputStream` 是两个调用点，都要保留（否则链里丢掉 FileInputStream）
    assert len(read_file.sinks) >= 2


def test_bridge_param_path_is_cross_app() -> None:
    """桥方法（JS 实参可控）+ 路径直接是形参 → cross-app（D-057）。"""
    index = index_of("BridgeParamPath.smali")
    method = method_of(index, "Lcom/example/app/BridgeParamPath;", "read(Ljava/lang/String;)V")
    sinks = scan_method_sinks(method, attacker_controlled_params=True)
    # `File(p1)` → cross-app；`FileInputStream(v0)` 的实参不是形参，仍是 unknown（不猜）
    assert Ownership.CROSS_APP in [s.ownership for s in sinks]


def test_param_path_without_bridge_context_stays_unknown() -> None:
    """普通方法（形参不一定是攻击者输入）→ 仍然是 unknown，不放大（D-051）。"""
    index = index_of("BridgeParamPath.smali")
    method = method_of(index, "Lcom/example/app/BridgeParamPath;", "read(Ljava/lang/String;)V")
    sinks = scan_method_sinks(method)
    assert sinks
    assert all(s.ownership is Ownership.UNKNOWN for s in sinks)


def test_directory_signal_wins_over_param() -> None:
    """`new File(getCacheDir(), p1)`：有私有目录信号 → own（信号优先于形参）。"""
    index = index_of("BridgeParamPath.smali")
    method = method_of(index, "Lcom/example/app/BridgeParamPath;", "readCache(Ljava/lang/String;)V")
    sinks = scan_method_sinks(method, attacker_controlled_params=True)
    assert sinks
    assert all(s.ownership is Ownership.OWN for s in sinks)


def test_directory_signal_helper_returns_source_loc() -> None:
    from reachscope.extract.sinks import directory_signal

    index = index_of("BridgeParamPath.smali")
    method = method_of(index, "Lcom/example/app/BridgeParamPath;", "readCache(Ljava/lang/String;)V")
    location = directory_signal(method)
    assert location is not None
    assert "getCacheDir" in location.snippet
    assert directory_signal(
        method_of(index, "Lcom/example/app/BridgeParamPath;", "read(Ljava/lang/String;)V")
    ) is None


def test_bridge_without_impl_class_gets_no_sinks() -> None:
    """impl_class 无法回溯时，桥方法不该凭空长出 sink。"""
    index = index_of("BridgeObjFromField.smali")
    bridges = extract_bridges(index, [])
    annotated = attach_bridge_sinks(bridges, index, package=PACKAGE)
    assert annotated[0].methods == []


def test_sinks_are_deduplicated_and_sorted() -> None:
    index = index_of("SinksAll.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")
    sinks = scan_method_sinks(method, package=PACKAGE)
    keys = [(s.kind.value, s.ownership.value) for s in sinks]
    assert len(keys) == len(set(keys))
    assert all(s.source is not None and s.source.line > 0 for s in sinks)
