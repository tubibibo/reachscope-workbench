"""v0.3 跨组件可达：显式 Intent + 攻击者数据 → 目标组件入口。"""

from __future__ import annotations

from pathlib import Path

from reachscope.analyze.chains import build_chains
from reachscope.analyze.evidence import build_evidence
from reachscope.analyze.intercomponent import find_hops
from reachscope.ingest.manifest import ManifestInfo
from reachscope.ingest.smali import SmaliIndex, index_smali_file
from reachscope.ir.model import (
    Component,
    ComponentType,
    JudgmentResult,
    SinkKind,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
PACKAGE = "com.example.app"
TARGET = "Lcom/example/app/CrossTarget;"

#: 用 FIXTURES 作为 base_dir：SourceLoc.file 保留 `smali/` 前缀，
#: `_class_descriptor_of` 才能推出方法所属类（与真实解码产物同口径）。
SMALI = FIXTURES / "smali"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(
            index, SMALI / "com" / "example" / "app" / name, base_dir=FIXTURES
        )
    return index


def method_of(index: SmaliIndex, class_name: str, name: str):
    class_info = index.get_class(f"L{class_name.replace('.', '/')};")
    assert class_info is not None
    for method in class_info.methods:
        if method.name == name:
            return method
    raise AssertionError(f"{class_name}.{name} 不存在")


def components(*, include_target: bool = True) -> list[Component]:
    result = [
        Component(
            name="com.example.app.CrossEntry",
            type=ComponentType.ACTIVITY,
            exported=True,
            impl_present=True,
        )
    ]
    if include_target:
        result.append(
            Component(
                name="com.example.app.CrossTarget",
                type=ComponentType.ACTIVITY,
                # 🔴 未导出也要跟：跨组件转发到内部组件正是本能力要覆盖的场景。
                exported=False,
                impl_present=True,
            )
        )
    return result


def test_explicit_constructor_with_attacker_extra_is_a_hop() -> None:
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    hops = find_hops(
        method_of(index, "com.example.app.CrossEntry", "onCreate"),
        index,
        package=PACKAGE,
    )
    assert [hop.target_descriptor for hop in hops] == [TARGET]
    assert hops[0].evidence.file.endswith("CrossEntry.smali")
    assert hops[0].evidence.line > 0


def test_set_class_name_with_attacker_extra_is_a_hop() -> None:
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    hops = find_hops(
        method_of(index, "com.example.app.CrossEntry", "onStart"),
        index,
        package=PACKAGE,
    )
    assert [hop.target_descriptor for hop in hops] == [TARGET]


def test_component_name_with_attacker_extra_is_a_hop() -> None:
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    hops = find_hops(
        method_of(index, "com.example.app.CrossEntry", "onNewIntent"),
        index,
        package=PACKAGE,
    )
    assert [hop.target_descriptor for hop in hops] == [TARGET]


def test_explicit_target_without_data_is_not_a_hop() -> None:
    """没有攻击者数据的 startActivity 是正常跳转，不是一条链。"""
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    hops = find_hops(
        method_of(index, "com.example.app.CrossEntry", "onResume"),
        index,
        package=PACKAGE,
    )
    assert hops == []


def test_implicit_intent_is_not_followed() -> None:
    """只有 action 的隐式 Intent 没有唯一目标，v0.3 不跟。"""
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    hops = find_hops(
        method_of(index, "com.example.app.CrossEntry", "onReceive"),
        index,
        package=PACKAGE,
    )
    assert hops == []


def test_chain_links_source_entry_to_target_sink() -> None:
    """入口 → cross_component → 目标组件 onCreate → loadUrl。"""
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    chains = build_chains(components(), index, [], [], ManifestInfo(package=PACKAGE))
    assert len(chains) == 1
    chain = chains[0]
    assert chain.entries == ["com.example.app.CrossEntry"]
    assert [step.sink for step in chain.steps] == [
        SinkKind.CROSS_COMPONENT.value,
        SinkKind.WEBVIEW.value,
    ]
    assert chain.steps[0].to == "com.example.app.CrossTarget"
    assert all(step.source is not None for step in chain.steps)
    assert chain.evidence_complete


def test_target_missing_from_manifest_is_not_followed() -> None:
    """显式目标不在 manifest 里（外部 App / 动态类）→ 不建跨组件链。"""
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    chains = build_chains(
        components(include_target=False), index, [], [], ManifestInfo(package=PACKAGE)
    )
    assert chains == []


def test_chain_id_is_stable() -> None:
    index = index_of("CrossEntry.smali", "CrossTarget.smali")
    manifest = ManifestInfo(package=PACKAGE)
    first = build_chains(components(), index, [], [], manifest)
    second = build_chains(components(), index, [], [], manifest)
    assert [chain.id for chain in first] == [chain.id for chain in second]


# --- M1 判别矩阵：应建链 ---------------------------------------------------


M1_FIXTURES = (
    "M1EntryKey.smali",
    "M1EntryConst.smali",
    "M1EntryBranch.smali",
    "M1BranchKey.smali",
    "M1ServiceEntry.smali",
    "M1CompatEntry.smali",
    "M1ReceiverEntry.smali",
    "M1KeyMismatch.smali",
    "M1CarrierMismatch.smali",
    "CrossTarget.smali",
    "M1DataTarget.smali",
    "M1ServiceTarget.smali",
    "M1ReceiverTarget.smali",
)


def m1_components(*names: str) -> list[Component]:
    """M1 矩阵的组件表：源入口全部导出，目标全部未导出。"""
    catalog = {
        "M1EntryKey": (ComponentType.ACTIVITY, True),
        "M1EntryConst": (ComponentType.ACTIVITY, True),
        "M1EntryBranch": (ComponentType.ACTIVITY, True),
        "M1BranchKey": (ComponentType.ACTIVITY, True),
        "M1ServiceEntry": (ComponentType.ACTIVITY, True),
        "M1CompatEntry": (ComponentType.ACTIVITY, True),
        "M1ReceiverEntry": (ComponentType.ACTIVITY, True),
        "M1KeyMismatch": (ComponentType.ACTIVITY, True),
        "M1CarrierMismatch": (ComponentType.ACTIVITY, True),
        "M1UnknownKey": (ComponentType.ACTIVITY, True),
        "CrossDeadEnd": (ComponentType.ACTIVITY, True),
        "DeadEndTarget": (ComponentType.ACTIVITY, False),
        "CrossTarget": (ComponentType.ACTIVITY, False),
        "M1DataTarget": (ComponentType.ACTIVITY, False),
        "M1ServiceTarget": (ComponentType.SERVICE, False),
        "M1ReceiverTarget": (ComponentType.RECEIVER, False),
    }
    selected = names or tuple(catalog)
    return [
        Component(
            name=f"{PACKAGE}.{name}",
            type=catalog[name][0],
            exported=catalog[name][1],
            impl_present=True,
        )
        for name in selected
    ]


def _cross_summary(chains) -> set[tuple[str, str, str]]:
    return {
        (
            chain.entries[0],
            next(
                step.to
                for step in chain.steps
                if step.sink == SinkKind.CROSS_COMPONENT.value
            ),
            chain.steps[-1].sink,
        )
        for chain in chains
    }


def test_m1_should_chain_matrix() -> None:
    """至少 6 个应建链形状：key 匹配 / data 载体 / Service / Broadcast / compat / 过程间。"""
    index = index_of(*M1_FIXTURES)
    chains = build_chains(
        m1_components(), index, [], [], ManifestInfo(package=PACKAGE)
    )
    assert _cross_summary(chains) == {
        (f"{PACKAGE}.M1EntryKey", f"{PACKAGE}.CrossTarget", "webview"),
        (f"{PACKAGE}.M1EntryKey", f"{PACKAGE}.M1DataTarget", "webview"),
        (f"{PACKAGE}.M1BranchKey", f"{PACKAGE}.CrossTarget", "webview"),
        (f"{PACKAGE}.M1ServiceEntry", f"{PACKAGE}.M1ServiceTarget", "webview"),
        (f"{PACKAGE}.M1CompatEntry", f"{PACKAGE}.CrossTarget", "webview"),
        (f"{PACKAGE}.M1ReceiverEntry", f"{PACKAGE}.M1ReceiverTarget", "webview"),
    }
    assert all(chain.evidence_complete for chain in chains)
    # 跨组件步要能回放源侧写入的 key / 载体（M1 证据要求）。
    key_chain = next(
        chain
        for chain in chains
        if chain.entries[0] == f"{PACKAGE}.M1EntryKey"
        and chain.steps[0].to == f"{PACKAGE}.CrossTarget"
    )
    assert 'extra "url"' in key_chain.steps[0].description
    branch_chain = next(
        chain
        for chain in chains
        if chain.entries[0] == f"{PACKAGE}.M1BranchKey"
    )
    # 跨分支复用寄存器后，key 仍要能回放到源侧常量 "url"。
    assert 'extra "url"' in branch_chain.steps[0].description
    assert branch_chain.evidence_complete
    data_chain = next(
        chain
        for chain in chains
        if chain.entries[0] == f"{PACKAGE}.M1EntryKey"
        and chain.steps[0].to == f"{PACKAGE}.M1DataTarget"
    )
    assert "data" in data_chain.steps[0].description


def test_m1_should_not_chain_matrix() -> None:
    """至少 8 个不应建链形状：key/载体不匹配、常量、本地 Intent、分支/寄存器、类型不符。"""
    index = index_of(*M1_FIXTURES)
    chains = build_chains(
        m1_components(
            "M1EntryKey",
            "M1EntryConst",
            "M1EntryBranch",
            "M1ServiceEntry",
            "M1ReceiverEntry",
            "M1KeyMismatch",
            "M1CarrierMismatch",
            "CrossTarget",
            "M1DataTarget",
            "M1ServiceTarget",
            "M1ReceiverTarget",
        ),
        index,
        [],
        [],
        ManifestInfo(package=PACKAGE),
    )
    # 只保留“负例”入口：它们一条链都不该有。
    negative_entries = {
        f"{PACKAGE}.M1EntryConst",
        f"{PACKAGE}.M1EntryBranch",
        f"{PACKAGE}.M1KeyMismatch",
        f"{PACKAGE}.M1CarrierMismatch",
    }
    assert not [
        chain for chain in chains if chain.entries[0] in negative_entries
    ]


def test_m1_start_method_is_bound_to_target_type() -> None:
    """`startActivity` 记 Activity、`startService` 记 Service（即使目标类型写错）。"""
    index = index_of(*M1_FIXTURES)
    onCreate = method_of(index, f"{PACKAGE}.M1ServiceEntry", "onCreate")
    onStart = method_of(index, f"{PACKAGE}.M1ServiceEntry", "onStart")
    resume = method_of(index, f"{PACKAGE}.M1ServiceEntry", "onResume")

    assert [hop.target_type for hop in find_hops(onCreate, index, package=PACKAGE)] == [
        ComponentType.SERVICE
    ]
    assert [hop.target_type for hop in find_hops(onStart, index, package=PACKAGE)] == [
        ComponentType.ACTIVITY
    ]
    assert [hop.target_type for hop in find_hops(resume, index, package=PACKAGE)] == [
        ComponentType.SERVICE
    ]


def test_m1_key_mismatch_alone_produces_no_chain() -> None:
    index = index_of("M1KeyMismatch.smali", "CrossTarget.smali")
    chains = build_chains(
        m1_components("M1KeyMismatch", "CrossTarget"),
        index,
        [],
        [],
        ManifestInfo(package=PACKAGE),
    )
    assert chains == []


def test_m1_carrier_mismatch_alone_produces_no_chain() -> None:
    index = index_of("M1CarrierMismatch.smali", "M1DataTarget.smali")
    chains = build_chains(
        m1_components("M1CarrierMismatch", "M1DataTarget"),
        index,
        [],
        [],
        ManifestInfo(package=PACKAGE),
    )
    assert chains == []


def test_m1_unknown_key_keeps_chain_but_marks_evidence_incomplete() -> None:
    """源侧 key 不是常量 → 保留链但必须 `evidence_complete=False`（协议只能 UNDECIDABLE）。"""
    index = index_of("M1UnknownKey.smali", "CrossTarget.smali")
    chains = build_chains(
        m1_components("M1UnknownKey", "CrossTarget"),
        index,
        [],
        [],
        ManifestInfo(package=PACKAGE),
    )
    assert len(chains) == 1
    assert chains[0].evidence_complete is False
    assert chains[0].judgments  # `evidence.j6` 会据此降为 UNKNOWN

    components = m1_components("M1UnknownKey", "CrossTarget")
    manifest = ManifestInfo(package=PACKAGE)
    judged, findings, _counter_examples = build_evidence(
        components, manifest, index, [], [], chains
    )
    assert findings == []
    assert judged[0].evidence_complete is False
    assert any(
        judgment.name == "J6" and judgment.result is JudgmentResult.UNKNOWN
        for judgment in judged[0].judgments
    )


def test_m1_dead_end_hop_gets_hop_specific_counter_example() -> None:
    """跨组件流到目标但目标无 sink → 反例要指向 startActivity，而不是普通 J5。"""
    index = index_of("CrossDeadEnd.smali", "DeadEndTarget.smali")
    components = m1_components("CrossDeadEnd", "DeadEndTarget")
    manifest = ManifestInfo(package=PACKAGE)
    chains = build_chains(components, index, [], [], manifest)
    assert chains == []

    _chains, findings, counter_examples = build_evidence(
        components, manifest, index, [], [], chains
    )
    assert findings == []
    entry = next(
        example
        for example in counter_examples
        if example.entry_id == f"{PACKAGE}.CrossDeadEnd"
    )
    assert entry.failed_judgment == "J5"
    assert "cross-component flow to" in entry.reason
    assert f"{PACKAGE}.DeadEndTarget" in entry.reason
    assert entry.source is not None and entry.source.file.endswith("CrossDeadEnd.smali")
