"""轻量调用图（PLAN §6.2 / TASKS T3.2）。

**只做静态调用边的索引，不解析虚派发。** 节点 = `(class_descriptor, method_signature)`，
边 = 一次 `invoke-virtual/static/direct/super/interface` 的精确签名目标。

四条约定（与 §6.2 对齐）：

- **精确签名连边**：`invoke-virtual {v0}, Lcom/app/Foo;->bar()V` 在索引里能找到
  `Lcom/app/Foo;->bar()V` 就连过去；找不到（框架 / 接口）→ 边的 `target=None`
- **多实现 / 接口调用 → may_dispatch=True**：`invoke-interface` 命中不到具体实现时记
  `may_dispatch=True`；命中了一个具体类也记 `may_dispatch=True`（v0.1 不解析派发）
- **深度上限 4**：`reachable_from(start, max_depth=4)` 严格不超出；够用即停
- **环不致死**：`seen` 集合做去重，BFS 不会因环无限循环
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingest.smali import Instruction, MethodInfo, SmaliIndex
from ..ir.model import SNIPPET_MAX_LENGTH, SourceLoc
from . import regflow

#: §6.2 深度上限：4 层调用链内必须停。
DEFAULT_MAX_DEPTH = 4


@dataclass(frozen=True, slots=True)
class Node:
    """调用图节点 = 一个方法的 `(类描述符, 签名)`。"""

    class_descriptor: str
    signature: str  # name(sig)ret

    @property
    def key(self) -> str:
        """`method_index` 用的统一键：`Lcls;->name(sig)ret`。"""
        return f"{self.class_descriptor}->{self.signature}"

    @classmethod
    def from_ref(cls, ref: str) -> Node:
        """从 `Lcls;->name(sig)ret` 字符串还原节点。"""
        arrow = ref.find("->")
        if arrow < 0:
            raise ValueError(f"非法 ref：{ref!r}")
        return cls(class_descriptor=ref[:arrow], signature=ref[arrow + 2 :])


@dataclass(frozen=True, slots=True)
class Edge:
    """调用图里的一条边。`target=None` 表示静态类型在索引里找不到（框架/接口）。"""

    source: Node
    target: Node | None
    may_dispatch: bool
    opcode: str
    site: SourceLoc


@dataclass(frozen=True)
class CallGraph:
    """`build(index)` 出来的全 APK 调用图（只读）。"""

    nodes: dict[str, Node]
    edges: tuple[Edge, ...]
    #: `source.key → 出边`。可达性查询必须走出边索引：逐次线性扫 `edges` 是
    #: O(入口数 × 边数 × 深度)，B 站 / 浏览器这类真实大包会把分析拖进小时级（D-062）。
    #: 手动构造（`CallGraph(nodes, edges)`）时为空字典 → 退回线性扫描，行为不变。
    adjacency: dict[str, tuple[Edge, ...]] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def build(cls, index: SmaliIndex) -> CallGraph:
        nodes: dict[str, Node] = {}
        for descriptor, class_info in sorted(index.class_by_descriptor.items()):
            for method in class_info.methods:
                node = Node(descriptor, method.name_with_signature)
                nodes[node.key] = node

        edges: list[Edge] = []
        for descriptor, class_info in sorted(index.class_by_descriptor.items()):
            for method in class_info.methods:
                source = Node(descriptor, method.name_with_signature)
                for instruction in method.instructions:
                    site = regflow.parse_invoke(instruction)
                    if site is None:
                        continue
                    edges.append(_make_edge(source, site, method, instruction, nodes))

        adjacency: dict[str, list[Edge]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source.key, []).append(edge)
        return cls(
            nodes=nodes,
            edges=tuple(edges),
            adjacency={key: tuple(items) for key, items in adjacency.items()},
        )

    def reachable_paths(
        self,
        start: Node | str,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> dict[str, tuple[Edge, ...]]:
        """BFS 找从 `start` 出发深度 ≤ `max_depth` 的可达节点及其**调用边路径**。

        返回 `{目标节点 key: 从 start 到它的边元组}`（不含 start 自身）。链构建需要
        把 `入口 → … → sink 所在方法` 的调用步骤写进证据，只有节点集合是不够的（D-062）。
        """
        start_node = _resolve(self, start)
        if start_node is None:
            return {}
        seen: set[str] = {start_node.key}
        frontier: list[tuple[Node, tuple[Edge, ...]]] = [(start_node, ())]
        paths: dict[str, tuple[Edge, ...]] = {}
        for _ in range(max_depth):
            next_frontier: list[tuple[Node, tuple[Edge, ...]]] = []
            for current, path in frontier:
                for edge in self._out_edges(current.key):
                    if edge.target is None or edge.target.key in seen:
                        continue
                    seen.add(edge.target.key)
                    edge_path = (*path, edge)
                    paths[edge.target.key] = edge_path
                    next_frontier.append((edge.target, edge_path))
            if not next_frontier:
                break
            frontier = next_frontier
        return paths

    def reachable_from(
        self,
        start: Node | str,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> list[Node]:
        """BFS 找从 `start` 出发深度 ≤ `max_depth` 的可达节点（不含自身），按 key 排序。"""
        paths = self.reachable_paths(start, max_depth=max_depth)
        return sorted((self.nodes[key] for key in paths), key=lambda node: node.key)

    def outgoing(self, start: Node | str) -> list[Edge]:
        """`start` 出发的全部边（含 `target=None` 的未解析边），按 `site` 排序。"""
        start_node = _resolve(self, start)
        if start_node is None:
            return []
        return sorted(
            self._out_edges(start_node.key),
            key=lambda edge: (edge.site.file, edge.site.line),
        )

    def _out_edges(self, key: str) -> tuple[Edge, ...]:
        """`key` 的出边；没建索引（手动构造的图）时退回线性扫描。"""
        if self.adjacency:
            return self.adjacency.get(key, ())
        return tuple(edge for edge in self.edges if edge.source.key == key)


def _resolve(graph: CallGraph, start: Node | str) -> Node | None:
    """把 `Node` 或 `Lcls;->m(sig)` 统一解析成节点；不在索引里 → None。"""
    if isinstance(start, Node):
        return graph.nodes.get(start.key)
    return graph.nodes.get(start)


def _make_edge(
    source: Node,
    site: regflow.InvokeSite,
    method: MethodInfo,
    instruction: Instruction,
    nodes: dict[str, Node],
) -> Edge:
    """建一条边：`target` 可能为 None；`may_dispatch` 按调用类型决定。"""
    target_ref = f"{site.class_descriptor}->{site.method}{site.signature}"
    target = nodes.get(target_ref)
    if target is not None:
        # 命中索引：精确签名已经定下来了；v0.1 不管子类覆写
        may_dispatch = site.opcode == "invoke-interface"
        return Edge(source, target, may_dispatch=may_dispatch, opcode=site.opcode, site=_loc(method, instruction))
    # 找不到：invoke-interface 算 may_dispatch；其它类型算“未解析”
    may_dispatch = site.opcode == "invoke-interface"
    return Edge(source, None, may_dispatch=may_dispatch, opcode=site.opcode, site=_loc(method, instruction))


def _loc(method: MethodInfo, instruction: Instruction) -> SourceLoc:
    """调用位置的证据。"""
    snippet = f"{instruction.opcode} {instruction.operands_raw}".strip()
    if len(snippet) > SNIPPET_MAX_LENGTH:
        snippet = snippet[:SNIPPET_MAX_LENGTH]
    return SourceLoc(file=method.source.file, line=instruction.file_line, snippet=snippet)


__all__ = ["DEFAULT_MAX_DEPTH", "CallGraph", "Edge", "Node"]
