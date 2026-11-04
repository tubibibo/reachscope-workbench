"""J6 + 三元组排序 + Finding 纳入 + 反例收集（PLAN §6.5 / §6.6 / TASKS T3.6）。

本模块不做任何"猜测补齐"，只把 T3.3–T3.5 已经算出来的判定**汇总成结论**：

1. **J6 证据完整性**（§6.3 / §6.5）：链上每一步都有证据 → high；有一处推测 → medium；
   出现 unknown 或深度 > 4 → low，且 `Chain.evidence_complete=False`
2. **三元组排序**（§6.5）：字典序降序 `(exploitability, impact, confidence)`，同分按 `chain_id` 升序
3. **Finding 纳入**（§6.5 原文）：
   `J1 PASS AND J2 PASS AND J6 != low AND exploitability >= medium`
4. **反例**（§6.6）：每个**未成为 Finding 的入口**都生成 `CounterExample`
   （`entry_id / entry_kind / failed_judgment / reason / source`），
   `failed_judgment` 是第一个导致不纳入的判据（J1 → J2 → J5 → J4 → J6）
5. **没有任何入口**：返回空列表；"未发现入口"这句话由 T4.1 报告层写，
   本层不发明空链冒充"没问题"（D-001）
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..extract.components import class_name_of
from ..extract.sinks import scan_method_sinks
from ..ingest.manifest import ManifestInfo
from ..ingest.smali import SmaliIndex
from ..ir.model import (
    Bridge,
    Chain,
    Component,
    CounterExample,
    EntryKind,
    Finding,
    Judgment,
    JudgmentResult,
    Level,
    Rank,
    Sink,
    SinkKind,
    SourceLoc,
    WebView,
)
from ..ir.validation import validate_identifiers
from . import intercomponent
from .chains import ENTRY_COMPONENT_TYPES, index_bridge_calls
from .judgments import OWNERSHIP_TO_LEVEL, j1, j2, j3, j4

#: Finding 纳入所需的最低 exploitability（§6.5：>= medium）。
FINDING_MIN_EXPLOITABILITY = Level.MEDIUM


@dataclass(frozen=True)
class ChainJudgment:
    """一条链的完整判定结果（T3.6 中间产物，最终喂给 `Finding` / `CounterExample`）。"""

    chain_id: str
    #: J1 / J2 / J3 / J4*（多条）/ J5 / J6，每条都带 SourceLoc + confidence + score_delta
    judgments: list[Judgment]
    exploitability: Level
    impact: Level
    confidence: Level
    evidence_complete: bool
    #: 第一个导致"不纳入 Finding"的判据；纳入时为 None
    primary_failure: Judgment | None

    @property
    def qualifies(self) -> bool:
        """是否满足 §6.5 的 Finding 纳入条件。"""
        return self.primary_failure is None


def j6(chain: Chain, *, depth_exceeded: bool = False) -> tuple[Judgment, bool]:
    """证据完整性（§6.3 J6）→ `(Judgment, evidence_complete)`。

    - 每一步都有证据 → PASS(high)，`evidence_complete=True`
    - 任何一步缺 `SourceLoc` → UNKNOWN(low)，`evidence_complete=False`
    - 调用深度 > 4（§6.2 上限）→ UNKNOWN(low)，`evidence_complete=False`
    - v0.1 不做推测，所以没有 medium 档（不臆造）
    """
    source = chain.steps[0].source if chain.steps else None
    if not chain.steps:
        return (
            Judgment(
                name="J6",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="empty chain: no steps to verify",
                source=None,
            ),
            False,
        )
    if any(step.source is None for step in chain.steps):
        return (
            Judgment(
                name="J6",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="step missing source evidence",
                source=source,
            ),
            False,
        )
    if depth_exceeded:
        return (
            Judgment(
                name="J6",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="call depth exceeded 4",
                source=source,
            ),
            False,
        )
    # M1：分析阶段已经判定“某一步不可判定”（例如跨组件源侧 key 与目标侧读取
    # 的 key 无法对齐）→ 不能因为每步都有 SourceLoc 就冒充证据完整。
    if any(
        judgment.name == "J6" and judgment.result is JudgmentResult.UNKNOWN
        for judgment in chain.judgments
    ):
        return (
            Judgment(
                name="J6",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="analysis marked a step undecidable (e.g. unresolved cross-component payload key)",
                source=source,
            ),
            False,
        )
    return (
        Judgment(
            name="J6",
            result=JudgmentResult.PASS,
            confidence=Level.HIGH,
            reason="all steps have evidence",
            source=source,
        ),
        True,
    )


def judge_chain(
    chain: Chain,
    component: Component,
    index: SmaliIndex,
    bridges: list[Bridge],
    webviews: list[WebView],
    *,
    depth_exceeded: bool = False,
) -> ChainJudgment:
    """对一条链跑完 J1/J2/J3/J4/J5/J6，返回 `ChainJudgment`。"""
    j1_judgment = j1(component)
    j2_judgment = j2(component, index)
    j5_judgment = _j5_judgment(chain)
    j6_judgment, evidence_complete = j6(chain, depth_exceeded=depth_exceeded)

    sinks = sinks_for_chain(chain, bridges, index)
    j3_judgment, highest_ownership = j3(sinks)
    impact = OWNERSHIP_TO_LEVEL[highest_ownership]

    bridge, webview = bridge_webview_for_chain(chain, bridges, webviews)
    if bridge is not None and webview is not None:
        j4_judgments, exploitability = j4(bridge, webview)
    else:
        j4_judgments = [
            Judgment(
                name="J4",
                result=JudgmentResult.UNKNOWN,
                confidence=Level.LOW,
                reason="no bridge + WebView pair for this chain",
                source=chain.steps[0].source if chain.steps else None,
            )
        ]
        exploitability = Level.UNKNOWN

    judgments = [j1_judgment, j2_judgment, j3_judgment, j5_judgment, *j4_judgments, j6_judgment]
    confidence = _confidence_of(judgments)

    primary_failure = _primary_failure(
        j1_judgment,
        j2_judgment,
        j5_judgment,
        _j4_failure(j4_judgments, exploitability),
        j6_judgment,
        exploitability,
    )
    return ChainJudgment(
        chain_id=chain.id,
        judgments=judgments,
        exploitability=exploitability,
        impact=impact,
        confidence=confidence,
        evidence_complete=evidence_complete,
        primary_failure=primary_failure,
    )


def build_evidence(
    components: list[Component],
    manifest: ManifestInfo,
    index: SmaliIndex,
    bridges: list[Bridge],
    webviews: list[WebView],
    chains: list[Chain],
) -> tuple[list[Chain], list[Finding], list[CounterExample]]:
    """把链 + 组件汇总成 `(chains, findings, counter_examples)`（§6.5 / §6.6）。

    返回的链是**已写入判定结果**的副本（`rank` / `judgments` / `evidence_complete`），
    报告层（T4.2 的链路章节）直接使用，不再重算 J1–J6（D-067）。顺序与入参一致。
    """
    # Validate before chain.id becomes a dictionary key; a later report check
    # cannot recover evidence already overwritten by a colliding local label.
    validate_identifiers(components, chains)
    findings: list[Finding] = []
    counter_examples: list[CounterExample] = []
    enriched: dict[str, Chain] = {}

    for component in components:
        if not _is_entry_candidate(component):
            continue

        j1_judgment = j1(component)
        if j1_judgment.result is JudgmentResult.FAIL:
            counter_examples.append(_counter_example(component, j1_judgment, None))
            continue

        j2_judgment = j2(component, index)
        if j2_judgment.result is JudgmentResult.FAIL:
            counter_examples.append(_counter_example(component, j2_judgment, None))
            continue

        component_chains = [c for c in chains if c.entries and c.entries[0] == component.name]
        if not component_chains:
            counter_examples.append(
                _counter_example(
                    component, _j5_miss(component, index, manifest), component.source
                )
            )
            continue

        # §6.6：反例按**入口**计，不按链计 —— 同一入口有多条链时，
        # 只要有一条成为 Finding，这个入口就不再进反例。
        first_failure: tuple[Judgment, SourceLoc | None] | None = None
        qualified = False
        for chain in component_chains:
            judged = judge_chain(chain, component, index, bridges, webviews)
            enriched[chain.id] = _with_judgment(chain, judged)
            if judged.qualifies:
                qualified = True
                findings.append(
                    Finding(
                        chain_id=chain.id,
                        title=_chain_title(chain),
                        exploitability=judged.exploitability,
                        impact=judged.impact,
                        confidence=judged.confidence,
                        summary=_chain_summary(chain, judged),
                        counter_evidence=[],
                    )
                )
                continue
            if judged.primary_failure is not None and first_failure is None:
                first_failure = (
                    judged.primary_failure,
                    chain.steps[0].source if chain.steps else component.source,
                )
        if not qualified and first_failure is not None:
            counter_examples.append(
                _counter_example(component, first_failure[0], first_failure[1])
            )

    sort_findings(findings)
    judged_chains = [enriched.get(chain.id, chain) for chain in chains]
    return judged_chains, findings, counter_examples


def _with_judgment(chain: Chain, judged: ChainJudgment) -> Chain:
    """把 J1–J6 的结论写回链（§4.8 的 `rank` / `judgments` / `evidence_complete`）。"""
    return replace(
        chain,
        rank=Rank(
            exploitability=judged.exploitability,
            impact=judged.impact,
            confidence=judged.confidence,
        ),
        judgments=list(judged.judgments),
        evidence_complete=judged.evidence_complete,
    )


def sort_findings(findings: list[Finding]) -> None:
    """§6.5 排序：字典序降序 `(exploitability, impact, confidence)`，同分按 `chain_id` 升序。"""
    findings.sort(
        key=lambda f: (
            -f.exploitability.score(),
            -f.impact.score(),
            -f.confidence.score(),
            f.chain_id,
        )
    )


def sinks_for_chain(
    chain: Chain, bridges: list[Bridge], index: SmaliIndex | None = None
) -> list[Sink]:
    """链上所有 `Sink`（§6.3 J3 输入）。

    优先取桥方法体内 T2.6 扫到的 sink；链的 sink 直接落在入口/callee 方法里
    （`j5` 的 `file` 命中）时，按 `SourceLoc.file:line` 回到索引里找那个调用点，
    否则 J3 会拿到空列表、把一次任意路径写入判成 impact=low（少报）。
    """
    if not chain.steps:
        return []
    bridge_calls = index_bridge_calls(bridges)
    sinks: list[Sink] = []
    for step in chain.steps:
        target = step.to
        if "->" not in target:
            continue
        impl_class, _, method_name = target.partition("->")
        found = bridge_calls.get((impl_class, method_name))
        if found is not None:
            sinks.extend(found[1].sinks)
    if not sinks and index is not None:
        direct = _direct_sink(chain, index)
        if direct is not None:
            sinks.append(direct)
    return sinks


def _direct_sink(chain: Chain, index: SmaliIndex) -> Sink | None:
    """链上的 `file` sink 直接位于入口/callee 方法体时，定位那条 `Sink`。"""
    for step in chain.steps:
        if step.sink != SinkKind.FILE.value or step.source is None:
            continue
        descriptor = _descriptor_from_file(step.source.file)
        class_info = index.get_class(descriptor) if descriptor else None
        if class_info is None:
            continue
        for method in class_info.methods:
            if not any(i.file_line == step.source.line for i in method.instructions):
                continue
            for sink in scan_method_sinks(method):
                if sink.source is not None and sink.source.line == step.source.line:
                    return sink
    return None


def _descriptor_from_file(rel_path: str) -> str:
    """`smali_classes2/com/x/Y.smali` → `Lcom/x/Y;`（§4.10 相对路径口径）。"""
    parts = rel_path.replace("\\", "/").split("/")
    if parts and parts[0].startswith("smali"):
        parts = parts[1:]
    if not parts or not parts[-1].endswith(".smali"):
        return ""
    return "L" + "/".join(parts)[: -len(".smali")] + ";"


def bridge_webview_for_chain(
    chain: Chain, bridges: list[Bridge], webviews: list[WebView]
) -> tuple[Bridge | None, WebView | None]:
    """给 J4 找 `(bridge, webview)` 对（§6.3 J4 需要两者都在场）。"""
    if not chain.steps:
        return None, None
    bridge_calls = index_bridge_calls(bridges)
    for step in chain.steps:
        if "->" not in step.to:
            continue
        impl_class, _, method_name = step.to.partition("->")
        found = bridge_calls.get((impl_class, method_name))
        if found is not None:
            webview = webviews[0] if webviews else None
            return found[0], webview
    return None, None


def _is_entry_candidate(component: Component) -> bool:
    """入口组件（与 T3.5 `chains._is_entry_candidate` 同口径）。"""
    return component.exported and component.type in ENTRY_COMPONENT_TYPES


def _entry_kind(component: Component) -> EntryKind:
    """§6.6 `entry_kind`：有 scheme/host 的 intent-filter → deeplink，否则 component。"""
    for intent_filter in component.intent_filters:
        if intent_filter.schemes or intent_filter.hosts:
            return EntryKind.DEEPLINK
    return EntryKind.COMPONENT


def _counter_example(
    component: Component, judgment: Judgment, source: SourceLoc | None
) -> CounterExample:
    """生成一条反例。

    J1 / J2 在**进入深链之前**就把入口否掉了（组件根本收不到请求 / 实现不存在），
    此时 `entry_kind` 记为 `component`；J4 / J5 / J6 的失败发生在链上，
    入口是深链，记为 `deeplink`（case 02/03 与 09 的验收口径）。
    """
    entry_kind = (
        EntryKind.COMPONENT
        if judgment.name in ("J1", "J2")
        else _entry_kind(component)
    )
    return CounterExample(
        entry_id=component.name,
        entry_kind=entry_kind,
        failed_judgment=judgment.name,
        reason=judgment.reason,
        source=source if source is not None else judgment.source,
    )


def _j5_miss(
    component: Component, index: SmaliIndex, manifest: ManifestInfo
) -> Judgment:
    """入口方法里没有 attacker-controlled → sink 的直灌（§6.3 J5 未命中）。

    M1：如果入口确实把攻击者数据写进了显式 Intent，但目标组件里没有任何可达
    sink，反例要写清「跨组件流到 X 但目标无 sink」——这是**跨组件死路**，
    不是普通的 J5 未命中；证据指向 `startActivity` 那一行，方便人工复核。
    """
    hops = intercomponent.find_component_hops(
        component, index, package=manifest.package
    )
    if hops:
        targets = sorted({class_name_of(hop.target_descriptor) for hop in hops})
        return Judgment(
            name="J5",
            result=JudgmentResult.UNKNOWN,
            confidence=Level.LOW,
            reason=(
                "cross-component flow to "
                + ", ".join(targets)
                + " does not reach an attacker-controlled sink"
            ),
            source=hops[0].evidence,
        )
    return Judgment(
        name="J5",
        result=JudgmentResult.UNKNOWN,
        confidence=Level.LOW,
        reason="no attacker-controlled flow reaches a sink in entry methods",
        source=component.source,
    )


def _j5_judgment(chain: Chain) -> Judgment:
    """链已经存在 ⇒ J5 命中（T3.5 只在 J5 有命中时才建链）。"""
    source = chain.steps[0].source if chain.steps else None
    return Judgment(
        name="J5",
        result=JudgmentResult.PASS,
        confidence=Level.HIGH,
        reason="attacker-controlled value reaches sink in entry method",
        source=source,
    )


def _j4_failure(judgments: list[Judgment], exploitability: Level) -> Judgment:
    """不纳入 Finding 时引用的 J4 判据。

    - 短路（挡住首次加载 / 页面不可控）→ 原样引用那一条
    - 6 项累加后分数不够 → 合成一条摘要判据；不能把第一条累加项
      （`base +2`，结果是 PASS）当成“失败理由”报给用户
    """
    if len(judgments) == 1:
        return judgments[0]
    source = next((item.source for item in judgments if item.source is not None), None)
    return Judgment(
        name="J4",
        result=JudgmentResult.PASS,
        confidence=Level.HIGH,
        reason=f"J4 score maps to exploitability={exploitability.value}, below the medium threshold",
        source=source,
    )


def _primary_failure(
    j1_judgment: Judgment,
    j2_judgment: Judgment,
    j5_judgment: Judgment,
    j4_judgment: Judgment,
    j6_judgment: Judgment,
    exploitability: Level,
) -> Judgment | None:
    """§6.5 不纳入时，找出**第一个**导致失败的判据（J1 → J2 → J5 → J4 → J6）。"""
    if j1_judgment.result is JudgmentResult.FAIL:
        return j1_judgment
    if j2_judgment.result is JudgmentResult.FAIL:
        return j2_judgment
    if j5_judgment.result is not JudgmentResult.PASS:
        return j5_judgment
    if exploitability.score() < FINDING_MIN_EXPLOITABILITY.score():
        return j4_judgment
    if j6_judgment.result is not JudgmentResult.PASS:
        return j6_judgment
    return None


def _confidence_of(judgments: list[Judgment]) -> Level:
    """整体置信度 = 所有判据里**最保守**那一档（不取平均、不取最高）。"""
    if not judgments:
        return Level.UNKNOWN
    return min((j.confidence for j in judgments), key=lambda level: level.score())


def _chain_title(chain: Chain) -> str:
    """`Finding.title`：入口 → 链上最后一个 sink 的人类可读描述。"""
    if not chain.steps:
        return chain.id
    entry = chain.entries[0] if chain.entries else "?"
    last_sink = next((s.sink for s in reversed(chain.steps) if s.sink), "")
    if not last_sink:
        return f"{entry} → {chain.steps[-1].to}"
    return f"{entry} → {last_sink}"


def _chain_summary(chain: Chain, judged: ChainJudgment) -> str:
    """`Finding.summary`：路径 + 三元组 + 关键判据理由。"""
    path = " → ".join(
        step.to or step.sink or "?" for step in chain.steps
    )
    return (
        f"path: {path}; "
        f"exploitability={judged.exploitability.value}, "
        f"impact={judged.impact.value}, "
        f"confidence={judged.confidence.value}"
    )


__all__ = [
    "FINDING_MIN_EXPLOITABILITY",
    "ChainJudgment",
    "bridge_webview_for_chain",
    "build_evidence",
    "j6",
    "judge_chain",
    "sinks_for_chain",
    "sort_findings",
]
