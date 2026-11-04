"""T2.5 单测：strong/medium/weak/none 四档、location、effective、扫描范围收紧。

strong/weak 用真实 fixture `cases/04`、`cases/05`、`cases/09`，
medium 与“顺序无法确认”用 `tests/fixtures/smali/` 的新 fixture。
"""

from __future__ import annotations

from pathlib import Path

from reachscope.extract.bridge import extract_bridges
from reachscope.extract.origin import (
    BYPASS_CONCAT,
    attach_origin_checks,
    collect_origin_checks,
)
from reachscope.ingest.smali import SmaliIndex, build_index, index_smali_file
from reachscope.ir.model import OriginLocation, OriginStrength

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"
CASES = FIXTURES / "cases"


def index_of(*names: str) -> SmaliIndex:
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def only(bridges):
    assert len(bridges) == 1
    return bridges[0]


# --- strong（cases/04、cases/09） ------------------------------------------


def test_case04_strong_in_should_override_is_not_effective() -> None:
    """强校验但只在 shouldOverrideUrlLoading → effective=false + bypass_reason 非空。"""
    index = build_index(CASES / "04_origin_strong_should_override")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    check = only(annotated).origin_check

    assert check.present is True
    assert check.strength is OriginStrength.STRONG
    assert check.location is OriginLocation.SHOULD_OVERRIDE
    assert check.effective is False
    assert check.bypass_reason
    assert check.kind == "String.equals"
    assert check.evidence is not None
    assert check.evidence.file == "smali/com/example/app/SafeClient.smali"


def test_case09_strong_before_load_is_effective() -> None:
    """校验在 loadUrl 之前且失败分支跳过 loadUrl → pre_load + effective=true。"""
    index = build_index(CASES / "09_origin_check_before_load")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    check = only(annotated).origin_check

    assert check.strength is OriginStrength.STRONG
    assert check.location is OriginLocation.PRE_LOAD
    assert check.effective is True
    assert check.evidence is not None
    assert check.evidence.file == "smali/com/example/app/MainActivity.smali"


# --- weak（cases/05） -------------------------------------------------------


def test_case05_concat_is_weak_with_bypass_reason() -> None:
    """contains 作用在 host+path 拼接串上 → weak + bypass_reason 说明拼接。"""
    index = build_index(CASES / "05_origin_weak_concat")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    check = only(annotated).origin_check

    assert check.strength is OriginStrength.WEAK
    assert check.location is OriginLocation.SHOULD_OVERRIDE
    assert check.effective is False
    assert check.bypass_reason == BYPASS_CONCAT


def test_weak_full_url_match() -> None:
    """contains 作用在完整 URL → weak + 'substring match on full URL'。"""
    index = index_of("OriginWeakFullUrl.smali")
    findings = collect_origin_checks(index)
    assert len(findings) == 1
    check = findings[0].check
    assert check.strength is OriginStrength.WEAK
    assert check.bypass_reason is not None
    assert "full URL" in check.bypass_reason
    assert check.location is OriginLocation.SHOULD_OVERRIDE


# --- medium ----------------------------------------------------------------


def test_medium_raw_url_equals() -> None:
    index = index_of("OriginMedium.smali")
    findings = collect_origin_checks(index)
    equals = next(f for f in findings if f.method.name == "shouldOverrideUrlLoading")
    assert equals.check.strength is OriginStrength.MEDIUM
    assert equals.check.kind == "String.equals"
    assert equals.check.location is OriginLocation.SHOULD_OVERRIDE
    assert equals.check.effective is False


def test_medium_host_starts_with() -> None:
    index = index_of("OriginMedium.smali")
    findings = collect_origin_checks(index)
    callback = next(f for f in findings if f.method.name == "onPageStarted")
    assert callback.check.strength is OriginStrength.MEDIUM
    assert callback.check.kind == "String.startsWith"
    assert callback.check.location is OriginLocation.PAGE_CALLBACK


# --- none / 扫描范围 --------------------------------------------------------


def test_case01_has_no_origin_check() -> None:
    """没有任何校验 → 默认 OriginCheck（none，不冒充“已校验”）。"""
    index = build_index(CASES / "01_positive_deeplink_bridge_sink")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    check = only(annotated).origin_check
    assert check.present is False
    assert check.strength is OriginStrength.NONE
    assert check.location is OriginLocation.NONE
    assert check.effective is False
    assert check.bypass_reason is None


def test_out_of_scope_same_name_method_is_ignored() -> None:
    """同名但不是 WebViewClient 体系的方法不能产生校验（D-047）。"""
    index = index_of("FakeClient.smali")
    assert collect_origin_checks(index) == []


def test_unconfirmed_order_is_not_effective() -> None:
    """强校验但顺序无法确认 → effective=false + 证据写明（D-048）。"""
    index = index_of("OriginUnconfirmed.smali")
    findings = collect_origin_checks(index)
    assert len(findings) == 1
    check = findings[0].check
    assert check.strength is OriginStrength.STRONG
    assert check.location is OriginLocation.PRE_LOAD
    assert check.effective is False
    assert check.bypass_reason is not None
    assert "branch" in check.bypass_reason


# --- 挂到桥上 --------------------------------------------------------------


def test_bridge_method_check_is_bridge_method_location_and_guarded() -> None:
    """桥方法内自带校验 → location=bridge_method、effective=true、guarded=true（D-044）。"""
    index = index_of("GuardedBridge.smali", "GuardedBridgeHost.smali")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    bridge = only(annotated)

    assert bridge.origin_check.location is OriginLocation.BRIDGE_METHOD
    assert bridge.origin_check.effective is True
    assert bridge.origin_check.strength is OriginStrength.STRONG
    assert [m.guarded for m in bridge.methods] == [True]


def test_bridge_without_check_keeps_guarded_false() -> None:
    """桥方法里没有校验 → guarded 保持 False，不冒充“已防护”。"""
    index = index_of("JsBridge.smali", "WebViewCallsites.smali")
    bridges = extract_bridges(index, [])
    annotated = attach_origin_checks(bridges, collect_origin_checks(index))
    bridge = only(annotated)
    assert bridge.methods
    assert all(m.guarded is False for m in bridge.methods)


def test_findings_are_sorted_by_evidence() -> None:
    index = index_of("OriginMedium.smali", "OriginWeakFullUrl.smali")
    findings = collect_origin_checks(index)
    keys = [(f.check.evidence.file, f.check.evidence.line) for f in findings]
    assert keys == sorted(keys)
