"""T3.6 单测：J6 证据完整性、三元组排序、Finding 纳入条件、反例收集（PLAN §6.3 / §6.5 / §6.6）。"""

from __future__ import annotations

from reachscope.analyze.chains import Chain
from reachscope.analyze.evidence import (
    FINDING_MIN_EXPLOITABILITY,
    build_evidence,
    j6,
    judge_chain,
    sort_findings,
)
from reachscope.ingest.manifest import ManifestInfo
from reachscope.ingest.smali import SmaliIndex
from reachscope.ir.model import (
    Bridge,
    BridgeMethod,
    Component,
    ComponentType,
    EntryKind,
    Finding,
    IntentFilter,
    JudgmentResult,
    Level,
    Ownership,
    Sink,
    SinkKind,
    SourceLoc,
    Step,
    UrlSource,
    UrlSourceKind,
    WebView,
    stable_id,
)

PACKAGE = "com.example.app"


def loc(line: int = 1, file: str = "smali/com/example/app/Entry.smali") -> SourceLoc:
    return SourceLoc(file=file, line=line, snippet=f"line {line}")


def make_chain(
    *,
    entry: str = "com.example.app.Entry",
    missing_source: bool = False,
    key: str = "k",
) -> Chain:
    return Chain(
        id=stable_id("chain", key),
        entries=[entry],
        steps=[
            Step(
                order=0,
                description="deeplink → loadUrl",
                from_=entry,
                to="webview",
                sink="webview",
                source=None if missing_source else loc(10),
            )
        ],
    )


def make_component(
    name: str = "com.example.app.Entry",
    *,
    exported: bool = True,
    impl_present: bool = True,
    permission: str | None = None,
    protection: str | None = None,
    deeplink: bool = False,
) -> Component:
    filters = []
    if deeplink:
        filters.append(
            IntentFilter(
                actions=["android.intent.action.VIEW"],
                categories=["android.intent.category.BROWSABLE"],
                schemes=["myapp"],
                hosts=["open.example.com"],
            )
        )
    return Component(
        name=name,
        type=ComponentType.ACTIVITY,
        exported=exported,
        impl_present=impl_present,
        permission=permission,
        permission_protection=protection,
        intent_filters=filters,
        source=loc(1, "AndroidManifest.xml"),
    )


def make_finding(exploitability: Level, impact: Level, confidence: Level, chain_id: str) -> Finding:
    return Finding(
        chain_id=chain_id,
        title=f"title-{chain_id}",
        exploitability=exploitability,
        impact=impact,
        confidence=confidence,
        summary="summary",
    )


# --- J6 证据完整性 ---------------------------------------------------------


def test_j6_all_steps_have_evidence() -> None:
    judgment, complete = j6(make_chain())
    assert judgment.result is JudgmentResult.PASS
    assert judgment.confidence is Level.HIGH
    assert complete is True


def test_j6_missing_source_is_unknown_and_incomplete() -> None:
    judgment, complete = j6(make_chain(missing_source=True))
    assert judgment.result is JudgmentResult.UNKNOWN
    assert judgment.confidence is Level.LOW
    assert complete is False


def test_j6_depth_exceeded_is_unknown_and_incomplete() -> None:
    judgment, complete = j6(make_chain(), depth_exceeded=True)
    assert judgment.result is JudgmentResult.UNKNOWN
    assert judgment.confidence is Level.LOW
    assert complete is False
    assert "depth" in judgment.reason


def test_j6_empty_chain_is_unknown_and_incomplete() -> None:
    judgment, complete = j6(Chain(id="empty", entries=["x"], steps=[]))
    assert judgment.result is JudgmentResult.UNKNOWN
    assert complete is False


# --- 排序（§6.5） ----------------------------------------------------------


def test_sort_is_lexicographic_descending() -> None:
    findings = [
        make_finding(Level.LOW, Level.HIGH, Level.HIGH, "c"),
        make_finding(Level.HIGH, Level.LOW, Level.HIGH, "a"),
        make_finding(Level.HIGH, Level.HIGH, Level.LOW, "b"),
        make_finding(Level.MEDIUM, Level.HIGH, Level.HIGH, "d"),
    ]
    sort_findings(findings)
    # (exploitability, impact, confidence) 字典序降序：b(3,3,1) > a(3,1,3) > d(2,3,3) > c(1,3,3)
    assert [f.chain_id for f in findings] == ["b", "a", "d", "c"]


def test_sort_breaks_ties_by_chain_id() -> None:
    findings = [
        make_finding(Level.HIGH, Level.HIGH, Level.HIGH, "zz"),
        make_finding(Level.HIGH, Level.HIGH, Level.HIGH, "aa"),
        make_finding(Level.HIGH, Level.HIGH, Level.HIGH, "mm"),
    ]
    sort_findings(findings)
    assert [f.chain_id for f in findings] == ["aa", "mm", "zz"]


def test_sort_is_deterministic() -> None:
    findings = [
        make_finding(Level.MEDIUM, Level.LOW, Level.LOW, "b"),
        make_finding(Level.HIGH, Level.MEDIUM, Level.LOW, "a"),
    ]
    sort_findings(findings)
    first = [f.chain_id for f in findings]
    sort_findings(findings)
    assert [f.chain_id for f in findings] == first


# --- Finding 纳入条件（§6.5） ---------------------------------------------


def test_low_exploitability_never_becomes_finding() -> None:
    """没有 (bridge, WebView) 对 → J4 UNKNOWN → exploitability < medium → 反例。"""
    component = make_component()
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], [make_chain()]
    )
    assert findings == []
    assert len(counter_examples) == 1
    assert counter_examples[0].failed_judgment == "J4"
    assert counter_examples[0].entry_id == component.name


def test_build_evidence_writes_judgments_back_to_chain() -> None:
    """D-067：返回的链带上 rank / judgments / evidence_complete，供报告层直接使用。"""
    component = make_component()
    original = make_chain()
    chains, findings, _counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], [original]
    )

    assert [chain.id for chain in chains] == [original.id]
    assert findings == []
    judged = chains[0]
    assert judged is not original, "必须返回副本，不能改写入参"
    assert {judgment.name for judgment in judged.judgments} >= {"J1", "J2", "J3", "J4", "J5", "J6"}
    assert judged.rank.exploitability is Level.UNKNOWN  # 无 bridge/WebView → J4 unknown
    assert judged.evidence_complete is True
    # 没进入判定循环的链原样返回（不臆造 rank）
    untouched = make_chain(key="untouched")
    chains, _findings, _ces = build_evidence(
        [], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], [untouched]
    )
    assert chains == [untouched]


def test_not_exported_component_is_not_an_entry() -> None:
    """未 export 的组件收不到任何外部请求 → 不是 Entry，不产反例（§6.6 的 Entry 口径）。"""
    component = make_component(exported=False, deeplink=True)
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], []
    )
    assert findings == []
    assert counter_examples == []


def test_missing_implementation_is_a_j2_counter_example() -> None:
    component = make_component(impl_present=False, deeplink=True)
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], []
    )
    assert findings == []
    assert counter_examples[0].failed_judgment == "J2"
    assert counter_examples[0].entry_kind is EntryKind.COMPONENT
    assert "implementation class not found" in counter_examples[0].reason


def test_each_entry_yields_exactly_one_counter_example() -> None:
    """§6.6 的反例按入口计：同一入口两条失败链也只产出一条反例。"""
    component = make_component()
    chains = [make_chain(key="a"), make_chain(key="b")]
    _chains, _findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], chains
    )
    assert [ce.entry_id for ce in counter_examples] == [component.name]


def test_pass_with_note_still_qualifies_and_lowers_confidence() -> None:
    """J1=PASS_WITH_NOTE（normal/dangerous 权限）仍参与纳入，但整体置信度被拉到 medium。

    §6.5 字面写 `J1 == PASS`；J1 的四分支里 PASS_WITH_NOTE 的含义是"第三方 App 可以申请"，
    因此按可达处理，置信度由 `_confidence_of` 取最保守值（D-065）。
    """
    component = make_component(permission="android.permission.INTERNET", protection="normal")
    bridge = Bridge(
        id="bridge-1",
        impl_class="com.example.app.Bridge",
        methods=[BridgeMethod(name="read", sinks=[Sink(kind=SinkKind.FILE, ownership=Ownership.CROSS_APP)])],
    )
    webview = WebView(
        id="webview-1",
        url_sources=[UrlSource(kind=UrlSourceKind.INTENT_DATA)],
    )
    chain = Chain(
        id=stable_id("chain", "pass-with-note"),
        entries=[component.name],
        steps=[
            Step(
                order=0,
                description="entry → bridge method",
                from_=component.name,
                to="com.example.app.Bridge->read",
                sink="bridge_method",
                source=loc(5),
            )
        ],
    )
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [bridge], [webview], [chain]
    )
    assert len(findings) == 1
    # J1 的 medium 是全链最保守的一档 → 不能冒充 high confidence
    assert findings[0].confidence is Level.MEDIUM
    assert counter_examples == []


def test_entry_without_chain_is_a_j5_counter_example() -> None:
    component = make_component(deeplink=True)
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], []
    )
    assert findings == []
    assert counter_examples[0].failed_judgment == "J5"
    assert counter_examples[0].entry_kind is EntryKind.DEEPLINK


def test_no_entries_produces_no_counter_examples() -> None:
    """没有任何入口 → 两个列表都空；“未发现入口”由报告层写（§6.6）。"""
    _chains, findings, counter_examples = build_evidence(
        [], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], []
    )
    assert findings == []
    assert counter_examples == []


def test_non_entry_components_are_ignored() -> None:
    component = make_component(exported=False)
    _chains, findings, counter_examples = build_evidence(
        [component], ManifestInfo(package=PACKAGE), SmaliIndex(), [], [], []
    )
    assert findings == [] and counter_examples == []


# --- 判定入口 --------------------------------------------------------------


def test_judge_chain_exploitability_threshold_is_medium() -> None:
    assert FINDING_MIN_EXPLOITABILITY is Level.MEDIUM


def test_judge_chain_primary_failure_is_the_chain_level_judgment() -> None:
    component = make_component()
    judged = judge_chain(make_chain(), component, SmaliIndex(), [], [])
    assert judged.qualifies is False
    assert judged.primary_failure is not None
    assert judged.primary_failure.name == "J4"
    # 没有桥 → J4 显式 UNKNOWN，而不是拿第一条累加项（PASS 的 base +2）冒充失败理由
    assert judged.primary_failure.result is JudgmentResult.UNKNOWN
    assert "no bridge" in judged.primary_failure.reason


# --- J3 的 sink 来源（D-063）----------------------------------------------


def _case01_index():
    from pathlib import Path

    from reachscope.ingest.smali import index_smali_file

    case = Path(__file__).resolve().parent.parent / "fixtures" / "cases" / "01_positive_deeplink_bridge_sink"
    index = SmaliIndex()
    for path in sorted((case / "smali").rglob("*.smali")):
        index_smali_file(index, path, base_dir=case)
    return index


def test_direct_file_sink_is_located_by_source_loc() -> None:
    """链的 `file` sink 不在桥上、直接落在方法体时，J3 仍要拿到那条 Sink（不能空列表）。"""
    from reachscope.analyze.evidence import sinks_for_chain
    from reachscope.extract.sinks import scan_method_sinks
    from reachscope.ir.model import SinkKind

    index = _case01_index()
    class_info = index.get_class("Lcom/example/app/JsBridge;")
    assert class_info is not None
    sink = next(
        s
        for m in class_info.methods
        for s in scan_method_sinks(m)
        if s.kind is SinkKind.FILE
    )
    assert sink.source is not None
    chain = Chain(
        id="direct",
        entries=["com.example.app.MainActivity"],
        steps=[Step(order=0, sink="file", source=sink.source)],
    )
    found = sinks_for_chain(chain, [], index)
    assert len(found) == 1
    assert found[0].kind is SinkKind.FILE
    assert found[0].source is not None and found[0].source.line == sink.source.line

    # 不给索引（旧调用口径）→ 仍然返回空列表，不猜
    assert sinks_for_chain(chain, []) == []


def test_descriptor_from_file_handles_multi_dex() -> None:
    from reachscope.analyze.evidence import _descriptor_from_file

    assert _descriptor_from_file("smali/com/x/Y.smali") == "Lcom/x/Y;"
    assert _descriptor_from_file("smali_classes10/com/x/Y$Inner.smali") == "Lcom/x/Y$Inner;"
    assert _descriptor_from_file("not-a-smali.txt") == ""
