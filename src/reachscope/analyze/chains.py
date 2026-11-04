"""链构建（PLAN §6.4 / TASKS T3.5）。

步骤（按 §6.4 原文）：

1. 对每个**入口组件**（exported 的 activity / service / receiver / provider），
   在其实现类里找入口方法集合（`onCreate / onNewIntent / onStart / onResume /
   onReceive / onBind / query`）
2. 用 §6.1 的 `regflow` 找 attacker-controlled 标签（`intent_data` / `intent_extra` / `deeplink_param`）
3. 用 §6.2 的 `callgraph` 找从入口方法出发、深度 ≤ `REACH_DEPTH` 的 sink
4. 组装 `Chain`：每一步都带 `SourceLoc`
5. 同一 `(entry, sink)` 去重，保留证据最完整的一条
6. **连不通的入口不生成链**（不写空链冒充“没找到”）

`judgments` 与 `rank` 由 T3.6 填充，本模块只负责把**路径**和**证据**拼出来。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..extract import sinks
from ..extract.components import class_name_of, descriptor_of
from ..graph import regflow
from ..graph.callgraph import CallGraph, Edge
from ..ingest.manifest import ManifestInfo
from ..ingest.smali import MethodInfo, SmaliIndex
from ..ir.model import (
    Bridge,
    BridgeMethod,
    Chain,
    Component,
    ComponentType,
    Judgment,
    JudgmentResult,
    Level,
    Ownership,
    Sink,
    SinkKind,
    SourceLoc,
    Step,
    WebView,
    stable_id,
)
from . import intercomponent
from .judgments import ENTRY_METHOD_NAMES, J5Hit, bridge_method_refs, is_entry_method, j5

#: §6.4：从入口方法出发的调用深度上限（与 §6.2 的 max_depth 一致）。
REACH_DEPTH = 4

#: v0.3：跨组件跳数上限。先只做一跳（入口 → 目标组件），不走链式转发。
MAX_COMPONENT_HOPS = 1

#: M1：跨组件 payload 的 key/载体无法判定时，链上留下的 J6 预判标记。
#: `Chain.evidence_complete` 的默认值本来就是 False（IR 历史口径），不能拿它
#: 当“分析判定不可判定”的信号；用一条预置 J6 判据把语义显式带进 `evidence.j6`。
UNDECIDABLE_CROSS_COMPONENT = (
    "cross-component payload key/carrier could not be decided"
)

#: 视为入口的组件类型（activity-alias 在 v0.1 不单独建链，走它的 target）。
ENTRY_COMPONENT_TYPES = (
    ComponentType.ACTIVITY,
    ComponentType.SERVICE,
    ComponentType.RECEIVER,
    ComponentType.PROVIDER,
)

#: `(impl_class_dotted, method_name)` → `(Bridge, BridgeMethod)`。
#: `Bridge.impl_class` 在 IR 里是**点分名**（`com.x.Bridge`），所以索引键也用点分名，
#: 匹配时把调用点的 `Lcls;` 用 `class_name_of` 转一次（`BridgeMethod` 没有返回类型字段，
#: 故按 `(类, 方法名)` 建键，再用 `param_types` 校验参数列表，避免重载误配）。
BridgeCallIndex = dict[tuple[str, str], tuple[Bridge, BridgeMethod]]


def build_chains(
    components: list[Component],
    index: SmaliIndex,
    bridges: list[Bridge],
    webviews: list[WebView],
    manifest: ManifestInfo,
    *,
    call_graph: CallGraph | None = None,
) -> list[Chain]:
    """对每个入口组件构造攻击链（去重后的列表）。"""
    del webviews  # WebView 暴露在 J4 里参与打分，链本身只记路径；T3.6 用到时再接
    graph = call_graph if call_graph is not None else CallGraph.build(index)
    bridge_calls = index_bridge_calls(bridges)
    # 全索引只扫一次（D-061）：j5 每个方法都要用，逐个方法重扫在大包上是 O(n²)
    bridge_refs = bridge_method_refs(index)
    #: 显式 Intent 的目标 → manifest 组件（activity-alias 暂不参与跨组件目标解析）。
    component_by_descriptor = {
        descriptor_of(component.name): component
        for component in components
        if component.type is not ComponentType.ACTIVITY_ALIAS
    }

    chains: list[Chain] = []
    for component in components:
        if not _is_entry_candidate(component):
            continue
        class_info = index.get_class(descriptor_of(component.name))
        if class_info is None:
            continue
        for entry_method in class_info.methods:
            if not is_entry_method(entry_method.name, component.type):
                continue
            chains.extend(
                _chains_from_entry(
                    component,
                    entry_method,
                    class_info.descriptor,
                    index,
                    bridge_calls,
                    bridge_refs,
                    graph,
                    manifest,
                    component_by_descriptor,
                    hops_left=MAX_COMPONENT_HOPS,
                    visited=frozenset({component.name}),
                )
            )
    return dedup(chains)


def index_bridge_calls(bridges: list[Bridge]) -> BridgeCallIndex:
    """把 `Bridge` 摊平成 `调用点 → (Bridge, BridgeMethod)` 的索引（§6.4 第 5 步用）。"""
    mapping: BridgeCallIndex = {}
    for bridge in bridges:
        if not bridge.impl_class:
            continue
        for method in bridge.methods:
            mapping[(bridge.impl_class, method.name)] = (bridge, method)
    return mapping


def match_bridge_call(
    site: regflow.InvokeSite, bridge_calls: BridgeCallIndex
) -> tuple[Bridge, BridgeMethod] | None:
    """调用点是否命中某个已注册桥的 `@JavascriptInterface` 方法（含参数列表校验）。"""
    found = bridge_calls.get((class_name_of(site.class_descriptor), site.method))
    if found is None:
        return None
    _bridge, method = found
    if list(method.params) != regflow.param_types(site.signature):
        return None
    return found


def dedup(chains: list[Chain]) -> list[Chain]:
    """同一 `(entry, sink)` 只保留**证据最完整**的一条（`steps` 最多的那条）。"""
    best: dict[tuple[str, str], Chain] = {}
    for chain in chains:
        if not chain.steps:
            continue
        entry = chain.entries[0] if chain.entries else ""
        # 跨调用的链以 `call` 步骤开头（D-062）、跨组件的链以 `cross_component`
        # 开头：去重键用**第一个真正的 sink 步**，否则同一入口经不同路径到不同
        # sink 会被错误合并（M1：之前只跳过 `call`，跨组件链会互相吞掉）。
        first = next(
            (
                step
                for step in chain.steps
                if step.sink not in ("call", SinkKind.CROSS_COMPONENT.value)
            ),
            chain.steps[0],
        )
        # 跨组件链要带上**目标组件**：同一入口把数据转发给不同组件时，
        # 目标侧的 sink 形状可能相同（都是 `→ webview`），只按 sink 去重会吞链。
        cross_target = next(
            (
                step.to
                for step in chain.steps
                if step.sink == SinkKind.CROSS_COMPONENT.value
            ),
            "",
        )
        key = (entry, f"{cross_target}|{first.to}|{first.sink}")
        current = best.get(key)
        if current is None or len(chain.steps) > len(current.steps):
            best[key] = chain
    return list(best.values())


def _is_entry_candidate(component: Component) -> bool:
    """入口组件：exported 且类型是四大组件之一。"""
    return component.exported and component.type in ENTRY_COMPONENT_TYPES


def _chains_from_entry(
    component: Component,
    entry_method: MethodInfo,
    class_descriptor: str,
    index: SmaliIndex,
    bridge_calls: BridgeCallIndex,
    bridge_refs: set[tuple[str, str, str]],
    graph: CallGraph,
    manifest: ManifestInfo,
    component_by_descriptor: dict[str, Component],
    *,
    hops_left: int,
    visited: frozenset[str],
    constraint: _PayloadConstraint | None = None,
) -> list[Chain]:
    """从一个入口方法出发，把"能走到 sink"的路径组装成链；连不通 → 空列表。

    `hops_left > 0` 时，还会尝试「显式 Intent 跨组件 → 目标组件的入口方法」这条边
    （v0.3）。目标组件即使未导出也跟；跳数与环由 `hops_left` / `visited` 控制。

    M1：
    - 沿调用路径把实参标签映射成 callee 形参标签（过程间污点），不再让每个
      callee 的 `Intent` 形参一律当入口 Intent；
    - `constraint` 是跨组件来源的 payload 约束，目标组件里的 sink 必须读到
      对应载体/相同 key 才建链；判不定则把链标成 `evidence_complete=False`。
    """
    chains: list[Chain] = []
    # 3. 深度 ≤ REACH_DEPTH 的可达方法（含入口自身）。
    # 🔴 调用图节点键是 `Lcls;->name(sig)ret`；只传 `name(sig)ret` 查不到任何节点，
    # 可达集会恒为空（D-062 修的就是这个——之前深度 4 的扫描等于没做）。
    start_key = f"{class_descriptor}->{entry_method.name_with_signature}"
    paths = graph.reachable_paths(start_key, max_depth=REACH_DEPTH)
    initial_by_key = _initial_tags_along_paths(entry_method, start_key, paths, index)
    methods: list[tuple[MethodInfo, tuple[Edge, ...], dict[str, regflow.Tag] | None]] = [
        (entry_method, (), None)
    ]
    for key in sorted(paths):
        # O(1) 查 `method_index`（键格式与 Node.key 完全一致）；
        # 不要退回 `get_class().method()` 的线性扫描 —— 大类上可达集一多就是 O(n²)。
        method = index.find_method(key)
        if method is not None and method is not entry_method:
            methods.append((method, paths[key], initial_by_key.get(key)))

    for method, call_path, initial in methods:
        built = _chains_in_method(
            component,
            entry_method,
            method,
            index,
            bridge_calls,
            bridge_refs,
            manifest,
            initial=initial,
            constraint=constraint,
        )
        if hops_left > 0:
            built.extend(
                _cross_component_chains(
                    component,
                    method,
                    index,
                    bridge_calls,
                    bridge_refs,
                    graph,
                    manifest,
                    component_by_descriptor,
                    hops_left=hops_left,
                    visited=visited,
                    initial=initial,
                )
            )
        chains.extend(_with_call_path(component, chain, call_path) for chain in built)
    return chains


def _initial_tags_along_paths(
    entry_method: MethodInfo,
    start_key: str,
    paths: dict[str, tuple[Edge, ...]],
    index: SmaliIndex,
) -> dict[str, dict[str, regflow.Tag]]:
    """沿调用路径逐跳把实参标签映射到 callee 形参（M1 过程间污点）。

    只对**可达方法**算，且按路径长度排序，保证调用者的标签先算出来。
    查不到调用者标签的路径直接跳过（调用方会退回 `regflow` 的保守默认）。
    """
    initial: dict[str, dict[str, regflow.Tag]] = {
        start_key: regflow.propagate(entry_method, smali=index).tags
    }
    for key in sorted(paths, key=lambda item: (len(paths[item]), item)):
        path = paths[key]
        if not path:
            continue
        callee = index.find_method(key)
        if callee is None:
            continue
        edge = path[-1]
        caller_tags = initial.get(edge.source.key)
        if caller_tags is None:
            continue
        site = _invoke_site_at(index, edge.source.key, edge.site.line)
        if site is None:
            continue
        initial[key] = regflow.param_tags_for(site, caller_tags, callee)
    return initial


def _invoke_site_at(
    index: SmaliIndex, caller_key: str, line: int
) -> regflow.InvokeSite | None:
    """按调用图边的 `SourceLoc.line` 回到调用者方法里取 `InvokeSite`。

    `callgraph.Edge.site` 只存 `SourceLoc`（不带实参寄存器），过程间标签映射
    需要实参，因此这里用行号做一次精确回查；查不到就放弃（调用方退回保守默认）。
    """
    caller = index.find_method(caller_key)
    if caller is None:
        return None
    for instruction in caller.instructions:
        if instruction.file_line != line:
            continue
        return regflow.parse_invoke(instruction)
    return None


@dataclass(frozen=True)
class _PayloadConstraint:
    """跨组件来源侧的数据载荷约束（M1：载体 + extra key）。

    目标组件里的 sink 只在该命中**可能**读取到这些数据时才接链：

    - 明确匹配 → 建链；
    - 明确不匹配（载体不同 / key 无交集）→ 不建链；
    - 不可判定（key 不是常量、`Uri` 可能由 extra 派生）→ 建链但
      `evidence_complete=False`，协议层只能给 `UNDECIDABLE`。
    """

    extra_keys: frozenset[str]
    has_unknown_extra_key: bool
    has_data: bool

    @classmethod
    def from_hop(cls, hop: intercomponent.CrossComponentHop) -> _PayloadConstraint:
        return cls(
            extra_keys=hop.extra_keys,
            has_unknown_extra_key=hop.has_unknown_extra_key,
            has_data=hop.has_data,
        )

    def match(self, hit: J5Hit) -> bool | None:
        verdicts: list[bool | None] = []
        if hit.reads_data:
            verdicts.append(self.has_data)
        if hit.reads_deeplink_param:
            origins = hit.deeplink_origins
            if "extra" in origins:
                # Uri 由 extra 里的字符串派生：载体对得上，但具体 key 未跟到。
                verdicts.append(
                    None if (self.extra_keys or self.has_unknown_extra_key) else False
                )
            elif "data" in origins:
                verdicts.append(self.has_data)
            else:
                # 来源未知：data 可能匹配，extra 也可能匹配。
                verdicts.append(True if self.has_data else None)
        if hit.extra_keys or hit.has_unknown_extra_key:
            if hit.has_unknown_extra_key or self.has_unknown_extra_key:
                verdicts.append(None)
            else:
                verdicts.append(bool(hit.extra_keys & self.extra_keys))
        if not verdicts:
            # 攻击者标签不是 intent extra/data（不应出现）：不据此断言匹配。
            return None
        if any(verdict is True for verdict in verdicts):
            return True
        if all(verdict is False for verdict in verdicts):
            return False
        return None


def _cross_component_chains(
    component: Component,
    method: MethodInfo,
    index: SmaliIndex,
    bridge_calls: BridgeCallIndex,
    bridge_refs: set[tuple[str, str, str]],
    graph: CallGraph,
    manifest: ManifestInfo,
    component_by_descriptor: dict[str, Component],
    *,
    hops_left: int,
    visited: frozenset[str],
    initial: dict[str, regflow.Tag] | None = None,
) -> list[Chain]:
    """把「显式 Intent 跨组件」接到目标组件的入口方法上。

    只保留目标组件里**真的走到 sink**的链：`startActivity` 本身不是漏洞，
    数据最终流到哪里才是。目标组件的链一旦建立，`entries` 仍记**源入口**，
    这样 J1（源入口是否导出）与反例归属都跟着真正的攻击面走。

    M1：启动方法必须与目标组件类型一致（`startActivity` → Activity、
    `startService` → Service、`sendBroadcast` → Receiver）；目标入口方法按
    目标组件类型取子集；来源 payload（载体 + key）作为约束传给目标分析。
    """
    chains: list[Chain] = []
    for hop in intercomponent.find_hops(
        method, index, package=manifest.package, initial=initial
    ):
        target = component_by_descriptor.get(hop.target_descriptor)
        if target is None or not target.impl_present:
            continue
        if target.type is not hop.target_type:
            continue
        if target.name == component.name or target.name in visited:
            continue
        target_class = index.get_class(descriptor_of(target.name))
        if target_class is None:
            continue
        constraint = _PayloadConstraint.from_hop(hop)
        for target_method in target_class.methods:
            if not is_entry_method(target_method.name, target.type):
                continue
            for chain in _chains_from_entry(
                target,
                target_method,
                target_class.descriptor,
                index,
                bridge_calls,
                bridge_refs,
                graph,
                manifest,
                component_by_descriptor,
                hops_left=hops_left - 1,
                visited=visited | {target.name},
                constraint=constraint,
            ):
                chains.append(_prepend_cross_component(component, target, chain, hop))
    return chains


def _prepend_cross_component(
    source: Component,
    target: Component,
    chain: Chain,
    hop: intercomponent.CrossComponentHop,
) -> Chain:
    """在目标组件的链前插入一步 `cross_component`，并把入口改回源组件。"""
    payload = _describe_payload(hop)
    steps = [
        Step(
            order=0,
            description=f"explicit Intent → {target.name}" + (f" ({payload})" if payload else ""),
            from_=source.name,
            to=target.name,
            sink=SinkKind.CROSS_COMPONENT.value,
            source=hop.evidence,
        )
    ]
    steps.extend(replace(step, order=step.order + 1) for step in chain.steps)
    return replace(
        chain,
        id=stable_id(
            "chain",
            f"{source.name}|cross|{target.name}|{hop.evidence.file}:{hop.evidence.line}|{chain.id}",
        ),
        entries=[source.name],
        steps=steps,
    )


def _describe_payload(hop: intercomponent.CrossComponentHop) -> str:
    """跨组件步的人类可读载荷描述（证据可回放：extra key / data）。"""
    parts: list[str] = []
    keys = sorted(hop.extra_keys)
    if keys:
        parts.append("extra " + ", ".join(f'"{key}"' for key in keys))
    if hop.has_unknown_extra_key:
        parts.append("extra <unknown key>")
    if hop.has_data:
        parts.append("data")
    return "; ".join(parts)


def _with_call_path(
    component: Component, chain: Chain, call_path: tuple[Edge, ...]
) -> Chain:
    """把 `入口 → … → 该方法的调用路径` 作为前置步骤写进链（D-062）。

    §6.4 第 3 步要求"从入口方法出发、深度 ≤ 4"；只把 sink 所在方法写进链、不写怎么
    走到那里，读者无法复核深度，J6 也会把一条跨调用的链误报成"全部有证据"。
    """
    if not call_path:
        return chain

    steps: list[Step] = []
    order = 0
    previous = component.name
    keys: list[str] = []
    for edge in call_path:
        target = edge.target.key if edge.target is not None else "?"
        keys.append(target)
        steps.append(
            Step(
                order=order,
                description=f"entry → callee (call depth {order + 1})",
                from_=previous,
                to=target,
                sink="call",
                source=edge.site,
            )
        )
        previous = target
        order += 1

    for position, step in enumerate(chain.steps):
        steps.append(
            Step(
                order=order,
                description=step.description,
                # 原链的第一步以"入口方法"为起点；跨调用后它来自最后一级 callee。
                from_=previous if position == 0 else step.from_,
                to=step.to,
                sink=step.sink,
                source=step.source,
            )
        )
        order += 1
    return replace(chain, id=stable_id("chain", f"{chain.id}|call|{'|'.join(keys)}"), steps=steps)


def _chains_in_method(
    component: Component,
    entry_method: MethodInfo,
    method: MethodInfo,
    index: SmaliIndex,
    bridge_calls: BridgeCallIndex,
    bridge_refs: set[tuple[str, str, str]],
    manifest: ManifestInfo,
    *,
    initial: dict[str, regflow.Tag] | None = None,
    constraint: _PayloadConstraint | None = None,
) -> list[Chain]:
    """在 `method` 里找 attacker-controlled → sink 的调用点，并为每个 sink 建一条链。

    §6.4 第 4 步的**"页面被外部控制"**和**"桥方法体内的 sink"**是同一条链的两段：
    `loadUrl(attacker_url)` 把页面交给攻击者 → 该 WebView 上注册的 `@JavascriptInterface`
    方法就处在攻击者可控页面里 → 桥方法体内的 sink 随之可达。所以 loadUrl 命中会
    把**该项目下所有已注册桥的暴露 + sink** 接在后面（v0.1 不区分是哪个 WebView 实例）。

    `constraint`（M1）：目标组件里的命中必须读到源侧写入的同一载体/extra key；
    明确不匹配的命中直接丢弃，不可判定的命中保留但把链标成 `evidence_complete=False`。
    """
    # 入口方法走 J5 的入口闸门；callee 是 §6.4 第 3 步算出来的"深度 ≤ 4 可达"，
    # 方法名不可能是入口名，闸门必须关掉（D-064）。
    hits = j5(
        method,
        index,
        package=manifest.package,
        bridge_refs=bridge_refs,
        require_entry_method=method is entry_method,
        initial=initial,
        component_type=component.type if method is entry_method else None,
    )
    if not hits:
        return []

    chains: list[Chain] = []
    for hit in hits:
        decidable = True if constraint is None else constraint.match(hit)
        if decidable is False:
            continue
        built: list[Chain] = []
        if hit.sink_kind == "bridge":
            matched = match_bridge_call(hit.site, bridge_calls)
            if matched is None:
                continue
            bridge, bridge_method = matched
            built = _bridge_chains(
                component, entry_method, hit.source, bridge, bridge_method, index,
            )
        elif hit.sink_kind == "webview":
            built = [
                _load_url_chain(component, entry_method, hit.source, bridge_calls, index)
            ]
        elif hit.sink_kind == "file":
            built = [
                _single_step_chain(component, entry_method, hit.source, "file", SinkKind.FILE.value)
            ]
        if decidable is None:
            built = [_mark_undecidable(chain) for chain in built]
        chains.extend(built)
    return chains


def _mark_undecidable(chain: Chain) -> Chain:
    """把链标成“跨组件 payload 不可判定”，J6 必须降为 UNKNOWN。"""
    marker = Judgment(
        name="J6",
        result=JudgmentResult.UNKNOWN,
        confidence=Level.LOW,
        reason=UNDECIDABLE_CROSS_COMPONENT,
        source=chain.steps[0].source if chain.steps else None,
    )
    return replace(
        chain,
        evidence_complete=False,
        judgments=[*chain.judgments, marker],
    )


def _load_url_chain(
    component: Component,
    entry_method: MethodInfo,
    evidence: SourceLoc,
    bridge_calls: BridgeCallIndex,
    index: SmaliIndex,
) -> Chain:
    """§6.4 第 4+5 步：入口 → loadUrl（页面外部可控）→ 该 WebView 上注册的桥 → 桥体内 sink。

    桥暴露这一步的 `source` 是 `addJavascriptInterface` 的注册点（§5.5），
    sink 那一步的 `source` 是 T2.6 在桥方法体内扫到的调用点。

    🔴 **已撤销的桥不暴露**（`revoked=True`）：页面拿不到被移除的命名空间，
    把它写进链只会把 exploitability 算低（case 06）。
    """
    del entry_method
    steps = [
        Step(
            order=0,
            description="deeplink → loadUrl",
            from_=component.name,
            to="webview",
            sink=SinkKind.WEBVIEW.value,
            source=evidence,
        )
    ]
    order = 1
    for (impl_class, method_name), (bridge, bridge_method) in sorted(bridge_calls.items()):
        if bridge.revoked:
            continue
        target = f"{impl_class}->{method_name}"
        steps.append(
            Step(
                order=order,
                description="bridge exposed to attacker-controlled page",
                from_="webview",
                to=target,
                sink="bridge_method",
                source=bridge.registered_in,
            )
        )
        order += 1
        order = _append_sink_steps(
            steps, order, target, impl_class, bridge_method, index,
        )
    return Chain(
        id=stable_id("chain", f"{component.name}|loadUrl|{evidence.line}|{len(steps)}"),
        entries=[component.name],
        steps=steps,
        evidence_complete=True,
    )


def _append_sink_steps(
    steps: list[Step],
    order: int,
    target: str,
    impl_class: str,
    bridge_method: BridgeMethod,
    index: SmaliIndex,
) -> int:
    """把桥方法体内的 sink 逐步追加到 `steps`，返回下一个 `order`。

    文件类 sink 的归属若由目录信号（`getCacheDir` 等）判定，额外追加一步
    **归属证据**（§6.4 每步都要 SourceLoc）：报告据此解释 impact 为什么是
    own → low，而不是只给一个结论。
    """
    file_sinks = [sink for sink in bridge_method.sinks if sink.kind is SinkKind.FILE]
    for sink in bridge_method.sinks:
        steps.append(
            Step(
                order=order,
                description=f"bridge method → {sink.kind.value} sink",
                from_=target,
                to="",
                sink=sink.kind.value,
                source=sink.source,
            )
        )
        order += 1

    bounded = [
        sink
        for sink in file_sinks
        if sink.ownership in (Ownership.OWN, Ownership.SHARED)
    ]
    if bounded:
        impl = _impl_method(index, impl_class, bridge_method.name)
        location = sinks.directory_signal(impl) if impl is not None else None
        if location is not None:
            steps.append(
                Step(
                    order=order,
                    description=(
                        "file sink path bounded by directory signal "
                        f"(ownership={bounded[0].ownership.value})"
                    ),
                    from_=target,
                    to="",
                    sink="file_ownership",
                    source=location,
                )
            )
            order += 1
    return order


def _impl_method(
    index: SmaliIndex, impl_class: str, method_name: str
) -> MethodInfo | None:
    """按点分类名 + 方法名取实现（与 `attach_bridge_sinks` 同口径）。"""
    class_info = index.get_class(descriptor_of(impl_class))
    if class_info is None:
        return None
    return next((m for m in class_info.methods if m.name == method_name), None)


def _bridge_chains(
    component: Component,
    entry_method: MethodInfo,
    evidence: SourceLoc,
    bridge: Bridge,
    bridge_method: BridgeMethod,
    index: SmaliIndex,
) -> list[Chain]:
    """入口 → 桥方法调用 → 桥方法体内的 sink（§6.4 第 6 步）。"""
    first = Step(
        order=0,
        description="deeplink → bridge method call",
        from_=component.name,
        to=f"{bridge.impl_class}->{bridge_method.name}",
        sink="bridge_method",
        source=evidence,
    )
    if not bridge_method.sinks:
        return [
            Chain(
                id=stable_id(
                    "chain",
                    f"{component.name}|{bridge_method.name}|no_sink|{evidence.line}",
                ),
                entries=[component.name],
                steps=[first],
                evidence_complete=True,
            )
        ]

    chains: list[Chain] = []
    for order, sink in enumerate(bridge_method.sinks, start=1):
        steps = [
            first,
            Step(
                order=order,
                description=f"bridge method → {sink.kind.value} sink",
                from_=f"{bridge.impl_class}->{bridge_method.name}",
                to="",
                sink=sink.kind.value,
                source=sink.source,
            ),
        ]
        if sink.kind is SinkKind.FILE and sink.ownership in (
            Ownership.OWN,
            Ownership.SHARED,
        ):
            impl = _impl_method(index, bridge.impl_class, bridge_method.name)
            location = sinks.directory_signal(impl) if impl is not None else None
            if location is not None:
                steps.append(
                    Step(
                        order=order + 1,
                        description=(
                            "file sink path bounded by directory signal "
                            f"(ownership={sink.ownership.value})"
                        ),
                        from_=f"{bridge.impl_class}->{bridge_method.name}",
                        to="",
                        sink="file_ownership",
                        source=location,
                    )
                )
        chains.append(
            Chain(
                id=stable_id(
                    "chain",
                    f"{component.name}|{bridge_method.name}|{sink.kind.value}|{order}",
                ),
                entries=[component.name],
                steps=steps,
                evidence_complete=True,
            )
        )
    return chains


def _single_step_chain(
    component: Component,
    entry_method: MethodInfo,
    evidence: SourceLoc,
    to: str,
    sink_kind: str,
) -> Chain:
    """入口 → 单个 sink（loadUrl / 文件路径）的一步链。"""
    del entry_method
    return Chain(
        id=stable_id("chain", f"{component.name}|{to}|{evidence.line}"),
        entries=[component.name],
        steps=[
            Step(
                order=0,
                description=f"deeplink → {to}",
                from_=component.name,
                to=to,
                sink=sink_kind,
                source=evidence,
            )
        ],
        evidence_complete=True,
    )


def entry_method_names() -> frozenset[str]:
    """入口方法名集合（对外暴露，供报告层解释"为什么没建链"）。"""
    return ENTRY_METHOD_NAMES


def bridge_sinks(bridge: Bridge) -> list[Sink]:
    """桥的全部 sink（T3.6 的 J3 用）。"""
    return [sink for method in bridge.methods for sink in method.sinks]


__all__ = [
    "ENTRY_COMPONENT_TYPES",
    "REACH_DEPTH",
    "bridge_sinks",
    "build_chains",
    "dedup",
    "entry_method_names",
    "index_bridge_calls",
    "match_bridge_call",
]
