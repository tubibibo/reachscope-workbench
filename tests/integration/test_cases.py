"""T3.6 端到端：9 个 case fixture 跑完整管线（解码产物 → 提取 → 分析）并断言 expected.json。

断言范围（§6.5 / §6.6 / TASKS T3.6）：

- `exit_code` 语义（0=可分析，3=加固短路）
- `analyzable`
- `components`：`exported` / `impl_present` / `permission_protection`
- `deeplinks`：`scheme` / `host` / `component`
- `bridges`：`impl_class` / `revoked` / `origin_check_{strength,location,effective}` / `bypass_reason_non_empty`
- `findings`：`exploitability` / `impact` / `confidence_at_least` / `chain_must_include`
- `counter_examples`：`entry_kind` / `failed_judgment` / `reason_contains`

**fixture 与 expected.json 一字节不改**：本模块只读，不写。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from reachscope.analyze.chains import build_chains
from reachscope.analyze.evidence import build_evidence
from reachscope.extract.bridge import extract_bridges
from reachscope.extract.components import resolve_components
from reachscope.extract.deeplinks import extract_deeplinks
from reachscope.extract.origin import attach_origin_checks, collect_origin_checks
from reachscope.extract.sinks import attach_bridge_sinks
from reachscope.extract.webview import extract_webviews
from reachscope.ingest.manifest import parse_manifest
from reachscope.ingest.smali import build_index
from reachscope.ir.model import (
    Bridge,
    Chain,
    Component,
    CounterExample,
    Deeplink,
    Finding,
    Level,
    WebView,
)

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"

_LEVELS = {
    "high": Level.HIGH,
    "medium": Level.MEDIUM,
    "low": Level.LOW,
    "unknown": Level.UNKNOWN,
}


@dataclass(frozen=True)
class CaseResult:
    """一个 case 的完整分析结果（含 `exit_code`，供 T4.1 的 CLI 复用同一套语义）。"""

    exit_code: int
    analyzable: bool
    components: list[Component]
    deeplinks: list[Deeplink]
    webviews: list[WebView]
    bridges: list[Bridge]
    chains: list[Chain]
    findings: list[Finding]
    counter_examples: list[CounterExample]


def case_dirs() -> list[Path]:
    return sorted(d for d in CASES.iterdir() if d.is_dir())


def expected_of(case: Path) -> dict:
    return json.loads((case / "expected.json").read_text(encoding="utf-8"))


def _analyzable_per_protection(case: Path) -> bool:
    """`protection.json` 声明 `analyzable=false` → 主线短路（case 08）。"""
    protection = case / "protection.json"
    if not protection.exists():
        return True
    data = json.loads(protection.read_text(encoding="utf-8"))
    return bool(data.get("analyzable", True))


def analyze(case: Path) -> CaseResult:
    """解码产物 → 提取（T2.1–T2.6）→ 分析（T3.5–T3.6）。"""
    if not _analyzable_per_protection(case):
        return CaseResult(
            exit_code=3,
            analyzable=False,
            components=[],
            deeplinks=[],
            webviews=[],
            bridges=[],
            chains=[],
            findings=[],
            counter_examples=[],
        )

    manifest = parse_manifest(case / "AndroidManifest.xml")
    index = build_index(case)
    components = resolve_components(manifest, index)
    deeplinks = extract_deeplinks(components, manifest.package)
    webviews = extract_webviews(index)
    warnings: list[str] = []
    bridges = extract_bridges(index, warnings)
    bridges = attach_origin_checks(bridges, collect_origin_checks(index))
    bridges = attach_bridge_sinks(bridges, index, package=manifest.package)
    chains = build_chains(components, index, bridges, webviews, manifest)
    chains, findings, counter_examples = build_evidence(
        components, manifest, index, bridges, webviews, chains
    )
    return CaseResult(
        exit_code=0,
        analyzable=True,
        components=components,
        deeplinks=deeplinks,
        webviews=webviews,
        bridges=bridges,
        chains=chains,
        findings=findings,
        counter_examples=counter_examples,
    )


def _chain_text(chains: list[Chain], chain_id: str) -> str:
    """一条链的全部可检索文本（`description` / `to` / `sink` / `SourceLoc.snippet`）。"""
    chain = next((c for c in chains if c.id == chain_id), None)
    if chain is None:
        return ""
    parts = [chain.id]
    for step in chain.steps:
        parts.extend([step.description, step.from_, step.to, step.sink])
        if step.source is not None:
            parts.extend([step.source.file, step.source.snippet])
    return "\n".join(parts)


def _assert_components(components: list[Component], expected: dict) -> None:
    by_name = {c.name: c for c in components}
    for name, want in expected.items():
        assert name in by_name, f"组件 {name} 未提取到"
        got = by_name[name]
        assert got.exported == want["exported"], f"{name}.exported"
        assert got.impl_present == want["impl_present"], f"{name}.impl_present"
        assert got.permission_protection == want["permission_protection"], (
            f"{name}.permission_protection"
        )


def _assert_deeplinks(deeplinks: list[Deeplink], expected: list[dict]) -> None:
    got = {(d.scheme, d.host, d.component) for d in deeplinks}
    for want in expected:
        key = (want["scheme"], want["host"], want["component"])
        assert key in got, f"deeplink {key} 未提取到（实际 {sorted(got)}）"


def _assert_bridges(bridges: list[Bridge], expected: list[dict] | None) -> None:
    if expected is None:
        return
    by_class: dict[str, list[Bridge]] = {}
    for bridge in bridges:
        by_class.setdefault(bridge.impl_class, []).append(bridge)
    for want in expected:
        impl_class = want["impl_class"]
        assert impl_class in by_class, f"桥 {impl_class} 未提取到（实际 {sorted(by_class)}）"
        candidates = by_class[impl_class]
        # 同名类可能被注册多次（case 06 有多个名），取第一个满足 revoked 的
        bridge = next((b for b in candidates if b.revoked == want["revoked"]), candidates[0])
        assert bridge.revoked == want["revoked"], f"{impl_class}.revoked"
        if "origin_check_strength" in want:
            assert bridge.origin_check.strength.value == want["origin_check_strength"], (
                f"{impl_class}.origin_check.strength"
            )
        if "origin_check_location" in want:
            assert bridge.origin_check.location.value == want["origin_check_location"], (
                f"{impl_class}.origin_check.location"
            )
        if "origin_check_effective" in want:
            assert bridge.origin_check.effective == want["origin_check_effective"], (
                f"{impl_class}.origin_check.effective"
            )
        if want.get("bypass_reason_non_empty"):
            assert bridge.origin_check.bypass_reason, f"{impl_class}.bypass_reason 为空"


def _assert_findings(result: CaseResult, expected: list[dict]) -> None:
    assert len(result.findings) == len(expected), (
        f"findings 数量不符：实际 {len(result.findings)}，期望 {len(expected)}"
    )
    for finding, want in zip(result.findings, expected, strict=True):
        assert finding.exploitability is _LEVELS[want["exploitability"]], (
            f"{finding.chain_id}.exploitability"
        )
        assert finding.impact is _LEVELS[want["impact"]], f"{finding.chain_id}.impact"
        assert finding.confidence.score() >= _LEVELS[want["confidence_at_least"]].score(), (
            f"{finding.chain_id}.confidence 低于 {want['confidence_at_least']}"
        )
        text = _chain_text(result.chains, finding.chain_id)
        assert text, f"{finding.chain_id} 找不到对应链"
        for needle in want.get("chain_must_include", []):
            assert needle in text, f"{finding.chain_id} 链里缺少 {needle!r}"


def _assert_counter_examples(
    counter_examples: list[CounterExample], expected: list[dict]
) -> None:
    for want in expected:
        matches = [
            ce
            for ce in counter_examples
            if ce.entry_kind.value == want["entry_kind"]
            and ce.failed_judgment == want["failed_judgment"]
            and want["reason_contains"] in ce.reason
        ]
        assert matches, (
            f"反例未命中 {want}（实际 "
            f"{[(ce.entry_kind.value, ce.failed_judgment, ce.reason) for ce in counter_examples]}）"
        )


@pytest.mark.parametrize("case", case_dirs(), ids=lambda c: c.name)
def test_case_matches_expected(case: Path) -> None:
    """每个 case 的 `expected.json` 逐项断言。"""
    expected = expected_of(case)["expect"]
    result = analyze(case)

    assert result.exit_code == expected["exit_code"], "exit_code 不符"
    assert result.analyzable == expected["analyzable"], "analyzable 不符"

    _assert_components(result.components, expected.get("components", {}))
    _assert_deeplinks(result.deeplinks, expected.get("deeplinks", []))
    _assert_bridges(result.bridges, expected.get("bridges"))
    _assert_findings(result, expected.get("findings", []))
    _assert_counter_examples(result.counter_examples, expected.get("counter_examples", []))


def test_all_nine_cases_are_covered() -> None:
    """守门：fixture 目录必须恰好是 9 个 case，少一个都算漏测。"""
    names = [c.name for c in case_dirs()]
    assert len(names) == 9, f"case 数量不是 9：{names}"


def test_hardened_case_short_circuits() -> None:
    """case 08（加固）：analyzable=false → 不跑分析，findings/counter_examples 全空。"""
    case = CASES / "08_hardened_app"
    result = analyze(case)
    assert result.exit_code == 3
    assert result.analyzable is False
    assert result.findings == []
    assert result.counter_examples == []
    assert result.chains == []


def test_findings_are_sorted_descending() -> None:
    """§6.5：findings 按三元组字典序降序。"""
    for case in case_dirs():
        result = analyze(case)
        keys = [
            (f.exploitability.score(), f.impact.score(), f.confidence.score())
            for f in result.findings
        ]
        assert keys == sorted(keys, reverse=True), f"{case.name} findings 未降序"


def test_findings_carry_no_counter_evidence_yet() -> None:
    """M3 的 Finding.counter_evidence 由 M4 报告层补（T3.6 只放空列表，不臆造）。"""
    for case in case_dirs():
        result = analyze(case)
        for finding in result.findings:
            assert finding.counter_evidence == []
            assert finding.summary  # 必须有可读摘要，不能空字符串冒充
            assert finding.title
