"""T3.5 单测：入口 → 桥方法内 sink 全链、每步 SourceLoc、去重、连不通不产链。"""

from __future__ import annotations

from pathlib import Path

from reachscope.analyze.chains import REACH_DEPTH, build_chains, dedup, index_bridge_calls
from reachscope.extract.bridge import extract_bridges
from reachscope.extract.sinks import attach_bridge_sinks
from reachscope.graph.callgraph import CallGraph
from reachscope.ingest.manifest import ManifestInfo
from reachscope.ingest.smali import SmaliIndex, index_smali_file, parse_smali_file
from reachscope.ir.model import (
    Chain,
    Component,
    ComponentType,
    Sink,
    SinkKind,
    SourceLoc,
    Step,
    stable_id,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"

PACKAGE = "com.example.app"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def make_manifest() -> ManifestInfo:
    return ManifestInfo(package=PACKAGE)


def make_component(name: str = "com.example.app.ChainEntry") -> Component:
    return Component(
        name=name,
        type=ComponentType.ACTIVITY,
        exported=True,
        impl_present=True,
    )


def built_index_and_bridges() -> tuple[SmaliIndex, list]:
    """把 ChainEntry + ChainBridge 跑一遍 T2.4 / T2.6，拿到带 sink 的桥。"""
    index = index_of("ChainEntry.smali", "ChainBridge.smali")
    warnings: list[str] = []
    bridges = extract_bridges(index, warnings)
    bridges = attach_bridge_sinks(bridges, index, package=PACKAGE)
    return index, bridges


# --- 全流程：deeplink → 桥方法 → file sink -------------------------------


def test_chain_from_deeplink_to_bridge_sink() -> None:
    """onCreate 里 deeplink → takeAndWrite → 桥方法体的 FileOutputStream sink。"""
    index, bridges = built_index_and_bridges()
    assert bridges, "T2.4 应该找到桥"
    bridge = bridges[0]
    method = bridge.methods[0]
    assert [s.kind for s in method.sinks] == [SinkKind.FILE], method.sinks

    chains = build_chains([make_component()], index, bridges, [], make_manifest())
    assert len(chains) == 1
    chain = chains[0]
    assert chain.entries == ["com.example.app.ChainEntry"]
    # 两步：entry → 桥方法调用 → 桥方法体内 sink
    assert len(chain.steps) == 2
    assert "bridge" in chain.steps[0].description
    assert chain.steps[1].sink == SinkKind.FILE.value


def test_every_step_has_source_loc() -> None:
    """§6.4：每一步都必须有 SourceLoc（含 file / line）。"""
    index, bridges = built_index_and_bridges()
    chains = build_chains([make_component()], index, bridges, [], make_manifest())
    for chain in chains:
        for step in chain.steps:
            assert step.source is not None
            assert step.source.file.endswith(".smali")
            assert step.source.line > 0
            assert "\\" not in step.source.file  # D-036 相对路径


def test_chain_ids_are_stable() -> None:
    """稳定 id：同一输入两次构建必须相同。"""
    index, bridges = built_index_and_bridges()
    first = build_chains([make_component()], index, bridges, [], make_manifest())
    second = build_chains([make_component()], index, bridges, [], make_manifest())
    assert [c.id for c in first] == [c.id for c in second]
    for chain in first:
        assert len(chain.id) == 8


# --- 去重 ---------------------------------------------------------------


def test_same_entry_sink_is_deduped() -> None:
    """onCreate 调了两次 `takeAndWrite`（同一 sink）→ 只保留一条链。"""
    index, bridges = built_index_and_bridges()
    chains = build_chains([make_component()], index, bridges, [], make_manifest())
    keys = [(c.entries[0], c.steps[0].to, c.steps[-1].sink) for c in chains]
    assert len(keys) == len(set(keys))
    assert len(chains) == 1


def test_dedup_keeps_most_complete_chain() -> None:
    """`dedup` 保留 `steps` 最多的那条。"""
    short = Chain(
        id=stable_id("chain", "a|b|1"),
        entries=["com.example.app.X"],
        steps=[Step(order=0, description="", from_="a", to="b", sink="file")],
    )
    long = Chain(
        id=stable_id("chain", "a|b|2"),
        entries=["com.example.app.X"],
        steps=[
            Step(order=0, description="", from_="a", to="b", sink="file"),
            Step(order=1, description="", from_="b", to="c", sink="file"),
        ],
    )
    result = dedup([short, long])
    assert len(result) == 1
    assert len(result[0].steps) == 2


# --- 连不通不生成链 ------------------------------------------------------


def test_entry_without_sink_produces_no_chain() -> None:
    """onStart 只 log，不进 sink → 该入口不生成链（不是空链）。"""
    index = index_of("J5Entry.smali", "J5Bridge.smali")
    bridges = extract_bridges(index, [])
    chains = build_chains([make_component("com.example.app.J5Entry")], index, bridges, [], make_manifest())
    # J5Entry 的 onCreate 走 loadUrl（webview sink），onStart 走 log（不产链）
    assert chains, "onCreate 的 loadUrl 应该产链"
    assert all(step.sink != "" for chain in chains for step in chain.steps)
    load_chains = [c for c in chains if c.steps[0].to == "webview"]
    assert len(load_chains) == 1


def test_non_exported_component_produces_no_chain() -> None:
    index, bridges = built_index_and_bridges()
    component = Component(
        name="com.example.app.ChainEntry",
        type=ComponentType.ACTIVITY,
        exported=False,
        impl_present=True,
    )
    assert build_chains([component], index, bridges, [], make_manifest()) == []


def test_missing_implementation_class_produces_no_chain() -> None:
    index, bridges = built_index_and_bridges()
    component = Component(
        name="com.example.app.NotInApk",
        type=ComponentType.ACTIVITY,
        exported=True,
        impl_present=False,
    )
    assert build_chains([component], index, bridges, [], make_manifest()) == []


# --- 深度上限与调用图 ---------------------------------------------------


def test_reach_depth_is_four() -> None:
    assert REACH_DEPTH == 4


def test_call_graph_is_used_for_depth() -> None:
    """`build_chains` 接受外部传入的 call_graph（默认自己 build）。"""
    index, bridges = built_index_and_bridges()
    graph = CallGraph.build(index)
    assert len(graph.nodes) > 0
    chains = build_chains(
        [make_component()], index, bridges, [], make_manifest(), call_graph=graph
    )
    assert len(chains) == 1


# --- 桥调用索引 ---------------------------------------------------------


def test_index_bridge_calls_maps_impl_class() -> None:
    """`Bridge.impl_class` 在 IR 里是点分名，索引键也用点分名。"""
    _index, bridges = built_index_and_bridges()
    mapping = index_bridge_calls(bridges)
    keys = list(mapping)
    assert keys, "桥调用索引不能为空"
    assert keys[0][0] == "com.example.app.ChainBridge"  # 点分名，不是 L...;
    assert keys[0][1] == "takeAndWrite"
    # impl_class 为空的桥不进索引（避免把空串当成调用点）
    assert all(descriptor for descriptor, _ in mapping)


def test_fixtures_have_no_unknown_syntax() -> None:
    for name in (
        "ChainEntry.smali",
        "ChainBridge.smali",
        "CallPathEntry.smali",
        "CallPathTarget.smali",
        "NonEntryTarget.smali",
        "BridgeParamPath.smali",
    ):
        _, warnings, unknown = parse_smali_file(SMALI / name)
        assert unknown == 0, f"{name} 有 {unknown} 行未知语法"
        assert warnings == []


def test_evidence_complete_is_true_for_built_chains() -> None:
    """T3.5 建的链每一步都有证据 → `evidence_complete=True`（T3.6 会按 unknown 降为 False）。"""
    index, bridges = built_index_and_bridges()
    chains = build_chains([make_component()], index, bridges, [], make_manifest())
    for chain in chains:
        assert chain.evidence_complete is True


def test_chain_to_dict_roundtrip() -> None:
    """链必须能序列化（T4.1 报告层用）。"""
    index, bridges = built_index_and_bridges()
    chains = build_chains([make_component()], index, bridges, [], make_manifest())
    data = chains[0].to_dict()
    assert data["id"] == chains[0].id
    assert len(data["steps"]) == 2


def test_bridge_refs_are_computed_once(monkeypatch) -> None:
    """D-061：`@JavascriptInterface` 全索引只扫一次，交给每次 j5 复用（大包上不许 O(n²)）。"""
    import reachscope.analyze.chains as chains_module

    index, bridges = built_index_and_bridges()
    calls: list[int] = []
    original = chains_module.bridge_method_refs

    def counting(index_arg):
        calls.append(1)
        return original(index_arg)

    monkeypatch.setattr(chains_module, "bridge_method_refs", counting)
    chains_module.build_chains([make_component()], index, bridges, [], make_manifest())
    assert len(calls) == 1


def test_reachable_query_uses_full_node_key() -> None:
    """D-062：可达性查询必须带类描述符（`Lcls;->...`），否则深度 4 的扫描恒为空。"""
    from reachscope.graph.callgraph import DEFAULT_MAX_DEPTH

    index, bridges = built_index_and_bridges()
    seen: list[str] = []

    class RecordingGraph(CallGraph):
        def reachable_paths(self, start, max_depth: int = DEFAULT_MAX_DEPTH):
            seen.append(start if isinstance(start, str) else start.key)
            return super().reachable_paths(start, max_depth=max_depth)

    graph = RecordingGraph.build(index)
    build_chains([make_component()], index, bridges, [], make_manifest(), call_graph=graph)

    assert seen, "每个入口方法都应该查询一次可达集"
    assert all(key.startswith("Lcom/example/app/ChainEntry;->") for key in seen), seen
    assert "Lcom/example/app/ChainEntry;->onCreate(Landroid/os/Bundle;)V" in seen


def test_chain_records_call_path_to_reachable_method() -> None:
    """D-062：sink 在深度 1 的 callee 里时，链必须先写"入口 → callee"这一步。"""
    index = index_of("CallPathEntry.smali", "CallPathTarget.smali")
    bridges = extract_bridges(index, [])
    chains = build_chains(
        [make_component("com.example.app.CallPathEntry")], index, bridges, [], make_manifest()
    )
    assert len(chains) == 1, chains
    chain = chains[0]
    assert [step.sink for step in chain.steps] == ["call", "webview"]
    assert chain.steps[0].to == "Lcom/example/app/CallPathTarget;->onCreate(Landroid/os/Bundle;)V"
    assert chain.steps[1].from_ == chain.steps[0].to
    assert chain.steps[0].source is not None
    assert chain.steps[1].source is not None
    # 跨调用的链 id 与直接链不同，避免两条链撞 id
    assert len(chain.id) == 8


def test_callee_without_entry_method_name_produces_chain() -> None:
    """D-064：callee 叫 `handleIntent` 也要能建链 —— 入口闸门只对入口方法生效。"""
    index = index_of("NonEntryTarget.smali")
    chains = build_chains(
        [make_component("com.example.app.NonEntryTarget")], index, [], [], make_manifest()
    )
    assert len(chains) == 1, chains
    chain = chains[0]
    assert [step.sink for step in chain.steps] == ["call", "webview"]
    assert (
        chain.steps[0].to
        == "Lcom/example/app/NonEntryTarget;->handleIntent(Landroid/content/Intent;)V"
    )
    assert chain.steps[1].from_ == chain.steps[0].to


def test_reachable_paths_is_bounded_by_depth() -> None:
    """`reachable_paths` 与 `reachable_from` 覆盖同一集合，且路径长度 = 深度。"""
    index = index_of(
        "CgChainA.smali", "CgChainB.smali", "CgChainC.smali", "CgChainD.smali"
    )
    graph = CallGraph.build(index)
    start = "Lcom/example/app/CgChainA;->start()V"
    paths = graph.reachable_paths(start, max_depth=2)
    assert set(paths) == {node.key for node in graph.reachable_from(start, max_depth=2)}
    for key, path in paths.items():
        assert path[-1].target is not None and path[-1].target.key == key
        assert len(path) <= 2


def test_bridge_sinks_helper() -> None:
    from reachscope.analyze.chains import bridge_sinks

    _index, bridges = built_index_and_bridges()
    sinks = bridge_sinks(bridges[0])
    assert sinks and isinstance(sinks[0], Sink)
    assert sinks[0].source is None or isinstance(sinks[0].source, SourceLoc)
