"""T3.2 单测：精确签名建边、深度上限、may_dispatch、环终止、连不通的负例。"""

from __future__ import annotations

from pathlib import Path

from reachscope.graph.callgraph import DEFAULT_MAX_DEPTH, CallGraph, Node
from reachscope.ingest.smali import SmaliIndex, index_smali_file, parse_smali_file

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"

CHAIN = ("CgChainA.smali", "CgChainB.smali", "CgChainC.smali", "CgChainD.smali")


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def keys(nodes: list[Node]) -> list[str]:
    return [node.key for node in nodes]


# --- 节点与边 -------------------------------------------------------------


def test_nodes_match_index_methods() -> None:
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    assert len(graph.nodes) == index.method_count
    assert "Lcom/example/app/CgChainA;->start()V" in graph.nodes


def test_invoke_virtual_creates_edge_to_exact_target() -> None:
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    edges = graph.outgoing("Lcom/example/app/CgChainA;->start()V")
    targets = [edge.target.key for edge in edges if edge.target is not None]
    assert "Lcom/example/app/CgChainB;-><init>()V" in targets
    assert "Lcom/example/app/CgChainB;->step()V" in targets
    assert all(edge.may_dispatch is False for edge in edges)


def test_edge_carries_source_loc() -> None:
    """每条边都必须带证据位置（§4.10，file 是相对路径）。"""
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    for edge in graph.edges:
        assert edge.site.file.endswith(".smali")
        assert "\\" not in edge.site.file
        assert edge.site.line > 0


# --- 深度上限 -------------------------------------------------------------


def test_default_max_depth_is_four() -> None:
    assert DEFAULT_MAX_DEPTH == 4


def test_reachable_respects_depth() -> None:
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    start = "Lcom/example/app/CgChainA;->start()V"
    assert keys(graph.reachable_from(start, max_depth=1)) == [
        "Lcom/example/app/CgChainB;-><init>()V",
        "Lcom/example/app/CgChainB;->step()V",
    ]
    depth_two = keys(graph.reachable_from(start, max_depth=2))
    assert "Lcom/example/app/CgChainC;->next()V" in depth_two
    assert "Lcom/example/app/CgChainD;->tail()V" not in depth_two
    depth_three = keys(graph.reachable_from(start, max_depth=3))
    assert "Lcom/example/app/CgChainD;->tail()V" in depth_three
    # 默认深度 4：链只有 4 个节点，到此为止
    assert keys(graph.reachable_from(start)) == depth_three


def test_reachable_from_unknown_node_is_empty() -> None:
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    assert graph.reachable_from("Lcom/example/app/Nope;->x()V") == []


# --- 环 -------------------------------------------------------------------


def test_cycle_terminates() -> None:
    index = index_of("CgCycleA.smali", "CgCycleB.smali")
    graph = CallGraph.build(index)
    # A → B → A：BFS 用 seen 去重，深度给 100 也不该死循环
    reachable = graph.reachable_from("Lcom/example/app/CgCycleA;->ping()V", max_depth=100)
    assert keys(reachable) == ["Lcom/example/app/CgCycleB;->pong()V"]


# --- may_dispatch 与连不通的负例 ------------------------------------------


def test_interface_call_without_impl_is_may_dispatch_unresolved() -> None:
    index = index_of("CgIfaceUser.smali", "CgImpl.smali")
    graph = CallGraph.build(index)
    edges = graph.outgoing("Lcom/example/app/CgIfaceUser;->run(Lcom/example/app/CgIf;)V")
    assert len(edges) == 1
    assert edges[0].target is None  # 接口不在索引里 → 连不通
    assert edges[0].may_dispatch is True  # 记 may_dispatch，不算错
    assert edges[0].opcode == "invoke-interface"


def test_resolved_static_call_is_not_may_dispatch() -> None:
    index = index_of("CgIfaceUser.smali", "CgImpl.smali")
    graph = CallGraph.build(index)
    edges = graph.outgoing("Lcom/example/app/CgIfaceUser;->direct()V")
    assert len(edges) == 1
    assert edges[0].target is not None
    assert edges[0].target.key == "Lcom/example/app/CgImpl;->helper()V"
    assert edges[0].may_dispatch is False


def test_framework_call_is_unresolved_but_not_may_dispatch() -> None:
    """负例：invoke-virtual 到框架类 → 连不通，但因为是 virtual 而非 interface，不记 may_dispatch。"""
    index = index_of("CgUnresolved.smali")
    graph = CallGraph.build(index)
    edges = graph.outgoing("Lcom/example/app/CgUnresolved;->show(Landroid/view/View;)V")
    assert len(edges) == 1
    assert edges[0].target is None
    assert edges[0].may_dispatch is False
    # 连不通不算错：图照样建出来了，可达集为空
    assert graph.reachable_from("Lcom/example/app/CgUnresolved;->show(Landroid/view/View;)V") == []


def test_build_creates_outgoing_adjacency() -> None:
    """D-062：`build` 必须建出边索引，可达性不再逐次线性扫全部边。"""
    index = index_of(*CHAIN)
    graph = CallGraph.build(index)
    assert graph.adjacency
    start = "Lcom/example/app/CgChainA;->start()V"
    assert [edge.target.key for edge in graph.adjacency[start] if edge.target] == [
        "Lcom/example/app/CgChainB;-><init>()V",
        "Lcom/example/app/CgChainB;->step()V",
    ]


def test_reachable_works_without_adjacency() -> None:
    """手动构造（无出边索引）的图退回线性扫描，结果必须与 `build` 一致。"""
    index = index_of(*CHAIN)
    built = CallGraph.build(index)
    manual = CallGraph(nodes=built.nodes, edges=built.edges)
    start = "Lcom/example/app/CgChainA;->start()V"
    assert manual.adjacency == {}
    assert keys(manual.reachable_from(start)) == keys(built.reachable_from(start))
    assert [e.target.key for e in manual.outgoing(start) if e.target] == [
        e.target.key for e in built.outgoing(start) if e.target
    ]


def test_node_from_ref_roundtrip() -> None:
    node = Node.from_ref("Lcom/x;->m()V")
    assert node.class_descriptor == "Lcom/x;"
    assert node.signature == "m()V"
    assert node.key == "Lcom/x;->m()V"


def test_fixtures_have_no_unknown_syntax() -> None:
    for name in ("CgChainA.smali", "CgChainB.smali", "CgChainC.smali", "CgChainD.smali",
                 "CgCycleA.smali", "CgCycleB.smali", "CgIfaceUser.smali", "CgImpl.smali",
                 "CgUnresolved.smali"):
        _, warnings, unknown = parse_smali_file(SMALI / name)
        assert unknown == 0, f"{name} 有 {unknown} 行未知语法"
        assert warnings == []
