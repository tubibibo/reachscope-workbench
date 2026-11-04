"""T0.2 IR 数据模型测试：往返序列化、稳定 ID、显式状态。

覆盖 `PLAN.md` §4 的全部 IR 类型；不依赖 apktool / apkid / fixture。
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from reachscope.ir import (
    Bridge,
    BridgeMethod,
    Chain,
    Component,
    ComponentType,
    CounterEvidence,
    CounterExample,
    Deeplink,
    EntryKind,
    ExposedTo,
    Finding,
    IntentFilter,
    IRDeserializeError,
    IRSerializable,
    Judgment,
    JudgmentResult,
    Level,
    Meta,
    OriginCheck,
    OriginLocation,
    OriginStrength,
    Ownership,
    Protection,
    Rank,
    Report,
    Sink,
    SinkKind,
    SourceLoc,
    Step,
    UrlSource,
    UrlSourceKind,
    WebView,
    stable_id,
)
from reachscope.ir import model as ir_model

LOC = SourceLoc(
    file="smali/com/example/app/MainActivity.smali", line=42, snippet="invoke-virtual {v0, v1}"
)

#: 每个 IR dataclass 一个“填满字段”的样例，用于往返序列化。
SAMPLES: dict[type, Any] = {
    SourceLoc: LOC,
    Meta: Meta(
        apk_path="app.apk",
        apk_sha256="a" * 64,
        package="com.example.app",
        version_name="1.2.3",
        version_code="123",
        target_sdk=33,
        min_sdk=23,
        analyzed_at="2026-10-19T00:00:00Z",
        tool_version="0.1.0",
        apktool_version="2.9.3",
        warnings=["unknown smali syntax skipped: 2"],
    ),
    Protection: Protection(detected=True, tool="apkid", labels=["packer::dexguard"], analyzable=False),
    IntentFilter: IntentFilter(
        actions=["android.intent.action.VIEW"],
        categories=["android.intent.category.BROWSABLE"],
        schemes=["myapp"],
        hosts=["open.example.com"],
        ports=["443"],
        paths=["/open"],
        path_patterns=["/o.*"],
        auto_verify=True,
    ),
    Component: Component(
        name="com.example.app.MainActivity",
        type=ComponentType.ACTIVITY,
        exported=True,
        exported_inferred=True,
        permission="com.example.app.SIGNATURE_PERM",
        permission_protection="signature",
        intent_filters=[IntentFilter(schemes=["myapp"])],
        impl_present=True,
        source=LOC,
    ),
    Deeplink: Deeplink(
        id=stable_id("deeplink", "myapp://open.example.com/open"),
        scheme="myapp",
        host="open.example.com",
        path="/open",
        auto_verify=False,
        component="com.example.app.MainActivity",
        params=["url"],
        source=LOC,
    ),
    UrlSource: UrlSource(kind=UrlSourceKind.INTENT_DATA, value="intent.getData()", source=LOC),
    WebView: WebView(
        id=stable_id("webview", "com.example.app.MainActivity.onCreate"),
        owner_class="com.example.app.MainActivity",
        owner_method="onCreate",
        url_sources=[UrlSource(kind=UrlSourceKind.CONST, value="https://example.com")],
        js_enabled=True,
        file_access=None,
        universal_file_access=False,
        source=LOC,
    ),
    OriginCheck: OriginCheck(
        present=True,
        strength=OriginStrength.WEAK,
        kind="contains",
        location=OriginLocation.SHOULD_OVERRIDE,
        effective=False,
        evidence=LOC,
        bypass_reason="substring match on concatenated host+path",
    ),
    Sink: Sink(kind=SinkKind.FILE, ownership=Ownership.CROSS_APP, source=LOC),
    BridgeMethod: BridgeMethod(
        name="readFile",
        params=["java.lang.String"],
        sinks=[Sink(kind=SinkKind.FILE, ownership=Ownership.OWN)],
        guarded=False,
        source=LOC,
    ),
    Bridge: Bridge(
        id=stable_id("bridge", "com.example.app.JsBridge"),
        impl_class="com.example.app.JsBridge",
        registered_in=LOC,
        exposed_to=ExposedTo.ALL_PAGES,
        origin_check=OriginCheck(strength=OriginStrength.NONE),
        revoked=False,
        revoke_at=None,
        methods=[BridgeMethod(name="readFile")],
        source=LOC,
    ),
    Step: Step(
        order=1,
        description="deeplink url -> loadUrl",
        from_="com.example.app.MainActivity.onCreate",
        to="android.webkit.WebView.loadUrl",
        sink="loadUrl",
        source=LOC,
    ),
    Judgment: Judgment(
        name="J4",
        result=JudgmentResult.PASS_WITH_NOTE,
        confidence=Level.MEDIUM,
        reason="origin check not effective for first loadUrl",
        source=LOC,
        score_delta=1,
    ),
    Rank: Rank(exploitability=Level.HIGH, impact=Level.HIGH, confidence=Level.MEDIUM),
    Chain: Chain(
        id=stable_id("chain", "deeplink:myapp://open.example.com/open"),
        rank=Rank(exploitability=Level.HIGH, impact=Level.HIGH, confidence=Level.MEDIUM),
        entries=["deeplink:myapp://open.example.com/open"],
        steps=[Step(order=1, sink="loadUrl")],
        judgments=[Judgment(name="J1", result=JudgmentResult.PASS, confidence=Level.HIGH)],
        evidence_complete=True,
    ),
    CounterEvidence: CounterEvidence(judgment="J4", reason="strong origin check", source=LOC),
    Finding: Finding(
        chain_id=stable_id("chain", "deeplink:myapp://open.example.com/open"),
        title="深链 URL 直灌未校验的 WebView 桥",
        exploitability=Level.HIGH,
        impact=Level.HIGH,
        confidence=Level.MEDIUM,
        summary="零权限 App 可通过深链控制页面并调用桥方法读文件",
        counter_evidence=[CounterEvidence(judgment="J4", reason="bridge not revoked")],
    ),
    CounterExample: CounterExample(
        entry_id="component:com.example.app.InternalActivity",
        entry_kind=EntryKind.COMPONENT,
        failed_judgment="J1",
        reason="signature-level permission",
        source=LOC,
    ),
    Report: Report(
        meta=Meta(package="com.example.app", tool_version="0.1.0"),
        protection=Protection(detected=False, analyzable=True),
        components=[Component(name="com.example.app.MainActivity", exported=True)],
        deeplinks=[Deeplink(scheme="myapp", host="open.example.com")],
        webviews=[WebView(owner_class="com.example.app.MainActivity")],
        bridges=[Bridge(impl_class="com.example.app.JsBridge")],
        chains=[Chain(id="chain-1", rank=Rank(exploitability=Level.HIGH))],
        findings=[Finding(chain_id="chain-1", exploitability=Level.HIGH)],
        counter_examples=[CounterExample(entry_id="component:x", failed_judgment="J1")],
    ),
}


def _ir_dataclasses() -> set[type]:
    """模块里所有 IR dataclass（含 IRSerializable 子类）。"""
    return {
        obj
        for obj in vars(ir_model).values()
        if isinstance(obj, type)
        and dataclasses.is_dataclass(obj)
        and issubclass(obj, IRSerializable)
    }


def test_every_ir_dataclass_has_a_roundtrip_sample() -> None:
    """防止新增 IR 类型时漏写往返测试。"""
    assert _ir_dataclasses() == set(SAMPLES)


@pytest.mark.parametrize("sample", list(SAMPLES.values()), ids=lambda s: type(s).__name__)
def test_roundtrip_serialization(sample: Any) -> None:
    data = sample.to_dict()
    json_text = json.dumps(data, ensure_ascii=False, indent=2)
    restored = type(sample).from_dict(json.loads(json_text))
    assert restored == sample
    assert restored.to_dict() == data


@pytest.mark.parametrize("sample", list(SAMPLES.values()), ids=lambda s: type(s).__name__)
def test_all_dataclasses_are_frozen(sample: Any) -> None:
    first_field = next(iter(dataclasses.fields(sample))).name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(sample, first_field, "changed")


def test_stable_id_is_deterministic_and_unique() -> None:
    first = stable_id("component", "com.example.app.MainActivity")
    assert first == stable_id("component", "com.example.app.MainActivity")
    assert len(first) == 8
    assert all(char in "0123456789abcdef" for char in first)
    assert first != stable_id("component", "com.example.app.OtherActivity")
    assert first != stable_id("bridge", "com.example.app.MainActivity")


def test_stable_id_normalizes_surrounding_whitespace() -> None:
    assert stable_id(" component ", " com.example.app.A ") == stable_id("component", "com.example.app.A")


def test_empty_report_is_valid_json_with_schema_version() -> None:
    data = json.loads(json.dumps(Report().to_dict(), ensure_ascii=False))
    assert data["schema_version"] == "0.1"
    assert data["summary"] == {
        "components": 0,
        "deeplinks": 0,
        "webviews": 0,
        "bridges": 0,
        "chains": 0,
        "findings": 0,
        "counter_examples": 0,
    }
    assert data["components"] == []
    assert data["counter_examples"] == []


def test_report_summary_counts_match_contents() -> None:
    report: Report = SAMPLES[Report]
    assert report.summary() == {
        "components": 1,
        "deeplinks": 1,
        "webviews": 1,
        "bridges": 1,
        "chains": 1,
        "findings": 1,
        "counter_examples": 1,
    }


def test_report_from_dict_ignores_derived_keys() -> None:
    data = Report(meta=Meta(package="com.example.app")).to_dict()
    assert "schema_version" in data and "summary" in data
    assert Report.from_dict(data) == Report(meta=Meta(package="com.example.app"))


def test_step_uses_from_alias_in_json() -> None:
    data = SAMPLES[Step].to_dict()
    assert "from" in data
    assert "from_" not in data
    assert Step.from_dict(data).from_ == "com.example.app.MainActivity.onCreate"


def test_snippet_is_truncated_to_200_chars() -> None:
    loc = SourceLoc(file="a.smali", line=1, snippet="x" * 500)
    assert len(loc.snippet) == 200
    assert len(loc.to_dict()["snippet"]) == 200


def test_enums_serialize_to_their_values() -> None:
    assert Ownership.CROSS_APP.value == "cross-app"
    assert Level.UNKNOWN.value == "unknown"
    assert JudgmentResult.PASS_WITH_NOTE.value == "PASS_WITH_NOTE"
    assert SAMPLES[Sink].to_dict()["ownership"] == "cross-app"


def test_ownership_and_level_are_independent() -> None:
    """D-011：归属档位不是 high/medium/low，不能复用 Level。"""
    assert {member.value for member in Ownership} == {"own", "shared", "cross-app", "high", "unknown"}
    assert {member.value for member in Level} == {"high", "medium", "low", "unknown"}
    assert "cross-app" not in {member.value for member in Level}


def test_rank_sort_key_is_lexicographic() -> None:
    high = Rank(exploitability=Level.HIGH, impact=Level.LOW, confidence=Level.LOW)
    medium = Rank(exploitability=Level.MEDIUM, impact=Level.HIGH, confidence=Level.HIGH)
    assert high.sort_key() > medium.sort_key()
    assert Level.HIGH.score() == 3 and Level.UNKNOWN.score() == 0


def test_origin_location_effective_matches_spec() -> None:
    """PLAN §5.6：只有 pre_load / bridge_method 覆盖首次加载。"""
    assert OriginLocation.PRE_LOAD.effective is True
    assert OriginLocation.BRIDGE_METHOD.effective is True
    assert OriginLocation.SHOULD_OVERRIDE.effective is False
    assert OriginLocation.PAGE_CALLBACK.effective is False


def test_unknown_keys_are_ignored() -> None:
    assert Component.from_dict({"name": "com.example.app.A", "future_field": 1}) == Component(
        name="com.example.app.A"
    )


def test_missing_keys_fall_back_to_defaults() -> None:
    assert Component.from_dict({}) == Component()


def test_invalid_enum_value_raises_with_field_path() -> None:
    with pytest.raises(IRDeserializeError) as excinfo:
        Component.from_dict({"type": "not-a-component-type"})
    assert "Component.type" in str(excinfo.value)


def test_invalid_scalar_type_raises_with_field_path() -> None:
    with pytest.raises(IRDeserializeError) as excinfo:
        SourceLoc.from_dict({"line": "42"})
    assert "SourceLoc.line" in str(excinfo.value)


def test_none_for_non_optional_field_raises() -> None:
    with pytest.raises(IRDeserializeError) as excinfo:
        Component.from_dict({"name": None})
    assert "Component.name" in str(excinfo.value)


def test_none_is_allowed_for_optional_field() -> None:
    assert WebView.from_dict({"js_enabled": None}).js_enabled is None
    assert WebView.from_dict({"js_enabled": True}).js_enabled is True


def test_deserialize_non_object_raises() -> None:
    with pytest.raises(IRDeserializeError):
        Component.from_dict(["not", "an", "object"])


def test_nested_lists_roundtrip_with_element_path_in_errors() -> None:
    with pytest.raises(IRDeserializeError) as excinfo:
        Report.from_dict({"components": [{"type": "bogus"}]})
    assert "components[0].type" in str(excinfo.value)
