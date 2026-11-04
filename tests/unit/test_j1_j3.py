"""T3.3 单测：J1（4 分支）、J2（缺失实现 / 抽象类 / 有实现）、J3（4 档归属）。"""

from __future__ import annotations

from pathlib import Path

from reachscope.analyze.judgments import OWNERSHIP_TO_LEVEL, j1, j2, j3
from reachscope.extract.components import descriptor_of
from reachscope.ingest.manifest import ManifestInfo, parse_manifest
from reachscope.ingest.smali import SmaliIndex, index_smali_file
from reachscope.ir.model import (
    Component,
    ComponentType,
    JudgmentResult,
    Level,
    Ownership,
    Sink,
    SinkKind,
    SourceLoc,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def make_component(
    *,
    name: str = "com.example.app.MainActivity",
    type_: ComponentType = ComponentType.ACTIVITY,
    exported: bool = True,
    permission: str | None = None,
    permission_protection: str | None = None,
    impl_present: bool = True,
) -> Component:
    return Component(
        name=name,
        type=type_,
        exported=exported,
        permission=permission,
        permission_protection=permission_protection,
        impl_present=impl_present,
    )


# --- J1：零特权可达性 -----------------------------------------------------


def test_j1_exported_false_is_fail_not_exported() -> None:
    component = make_component(exported=False)
    result = j1(component)
    assert result.result is JudgmentResult.FAIL
    assert result.reason == "not exported"
    assert result.confidence is Level.HIGH


def test_j1_no_permission_is_pass() -> None:
    component = make_component()
    result = j1(component)
    assert result.result is JudgmentResult.PASS
    assert result.reason == "no permission required"
    assert result.confidence is Level.HIGH


def test_j1_signature_permission_is_fail() -> None:
    component = make_component(
        permission="com.example.app.SIG_PERM",
        permission_protection="signature",
    )
    result = j1(component)
    assert result.result is JudgmentResult.FAIL
    assert result.reason == "signature-level permission"
    assert result.confidence is Level.HIGH


def test_j1_normal_permission_is_pass_with_note() -> None:
    component = make_component(
        permission="android.permission.INTERNET",
        permission_protection="normal",
    )
    result = j1(component)
    assert result.result is JudgmentResult.PASS_WITH_NOTE
    assert result.reason == "requires normal permission; third-party app can request it"
    assert result.confidence is Level.MEDIUM


def test_j1_dangerous_permission_is_pass_with_note() -> None:
    component = make_component(
        permission="android.permission.READ_CONTACTS",
        permission_protection="dangerous",
    )
    result = j1(component)
    assert result.result is JudgmentResult.PASS_WITH_NOTE
    assert result.reason == "requires dangerous permission; third-party app can request it"


def test_j1_unknown_protection_is_unknown() -> None:
    component = make_component(
        permission="com.thirdparty.X",
        permission_protection="unknown",
    )
    result = j1(component)
    assert result.result is JudgmentResult.UNKNOWN
    assert result.reason == "permission protection level unresolved"
    assert result.confidence is Level.LOW


def test_j1_judgment_has_source_loc() -> None:
    """§6.3 要求每条判定都带 SourceLoc。"""
    source = SourceLoc(file="AndroidManifest.xml", line=12, snippet="<activity ...>")
    component = make_component(exported=False)
    object.__setattr__(component, "source", source)
    assert j1(component).source is source


# --- J2：实现真实性 -------------------------------------------------------


def test_j2_impl_missing_is_fail() -> None:
    component = make_component(
        name="com.example.app.NotInApk",
        impl_present=False,
    )
    result = j2(component, index_of())
    assert result.result is JudgmentResult.FAIL
    assert result.reason == "implementation class not found in APK"


def test_j2_abstract_without_subclass_is_fail() -> None:
    index = index_of("J2AbstractClass.smali")
    component = make_component(name="com.example.app.AbstractEntry", impl_present=True)
    assert index.get_class(descriptor_of(component.name)) is not None
    assert index.get_class(descriptor_of(component.name)).is_abstract
    result = j2(component, index)
    assert result.result is JudgmentResult.FAIL
    assert result.reason == "no concrete implementation"


def test_j2_abstract_with_subclass_is_pass() -> None:
    index = index_of("J2AbstractClass.smali", "J2Subclass.smali")
    component = make_component(name="com.example.app.AbstractEntry", impl_present=True)
    result = j2(component, index)
    assert result.result is JudgmentResult.PASS
    assert result.reason == "implementation present"


def test_j2_concrete_is_pass() -> None:
    index = index_of("J2ConcreteClass.smali")
    component = make_component(name="com.example.app.ConcreteEntry", impl_present=True)
    result = j2(component, index)
    assert result.result is JudgmentResult.PASS


def test_j2_alias_skips_abstract_check() -> None:
    """activity-alias 的 `Component.name` 在 smali 里没有类，abstract 检查必须跳过（D-032b）。"""
    index = index_of("J2ConcreteClass.smali")
    component = make_component(
        name="com.example.app.LauncherAlias",
        type_=ComponentType.ACTIVITY_ALIAS,
        impl_present=True,
    )
    result = j2(component, index)
    assert result.result is JudgmentResult.PASS


# --- J3：数据归属 ---------------------------------------------------------


def _sink(ownership: Ownership) -> Sink:
    return Sink(kind=SinkKind.FILE, ownership=ownership)


def test_j3_own_only_yields_low_impact_and_special_reason() -> None:
    judgment, highest = j3([_sink(Ownership.OWN), _sink(Ownership.OWN)])
    assert highest is Ownership.OWN
    assert judgment.reason == "all sinks stay within own boundary"
    assert OWNERSHIP_TO_LEVEL[highest] is Level.LOW


def test_j3_shared_yields_medium() -> None:
    judgment, highest = j3([_sink(Ownership.OWN), _sink(Ownership.SHARED)])
    assert highest is Ownership.SHARED
    assert OWNERSHIP_TO_LEVEL[highest] is Level.MEDIUM
    assert "shared" in judgment.reason


def test_j3_cross_app_yields_high() -> None:
    _judgment, highest = j3([_sink(Ownership.OWN), _sink(Ownership.CROSS_APP)])
    assert highest is Ownership.CROSS_APP
    assert OWNERSHIP_TO_LEVEL[highest] is Level.HIGH


def test_j3_high_yields_high_and_takes_precedence() -> None:
    """§6.3 J3：取最高一档作为 impact 依据。"""
    _judgment, highest = j3(
        [_sink(Ownership.OWN), _sink(Ownership.SHARED), _sink(Ownership.HIGH)]
    )
    assert highest is Ownership.HIGH
    assert OWNERSHIP_TO_LEVEL[highest] is Level.HIGH


def test_j3_empty_sinks_is_unknown_low() -> None:
    """没汇点时也不能冒充“高危”。"""
    judgment, highest = j3([])
    assert highest is Ownership.UNKNOWN
    assert judgment.result is JudgmentResult.UNKNOWN
    assert judgment.confidence is Level.LOW


# --- 真实 manifest 解析 → J1/J2 联调（不写 expected） ---------------------


def test_j1_with_real_manifest_components() -> None:
    """用真实 fixture manifest 走通：J1 至少能跑遍所有组件不抛异常。"""
    manifest = parse_manifest(SMALI.parent / "manifests" / "all_component_types.xml")
    assert isinstance(manifest, ManifestInfo)
    for component in manifest.components:
        judgment = j1(component)
        assert judgment.name == "J1"
        assert judgment.reason  # 必须有理由
