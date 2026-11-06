"""T4.1 JSON 报告（PLAN §8.1）。

覆盖四条验收：稳定排序、`schema_version`、`summary` 与实际计数一致、
同输入两次渲染除 `analyzed_at` 外逐字节相同；另加一个真实 fixture case 的端到端用例。
"""

from __future__ import annotations

import dataclasses
import json
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
    EntryKind,
    Finding,
    Level,
    Meta,
    Report,
    SourceLoc,
    Step,
    WebView,
)
from reachscope.ir.serialize import IRDeserializeError
from reachscope.report.json_report import load_json, normalize_report, render_json, write_json

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"


def _source(line: int = 1) -> SourceLoc:
    return SourceLoc(file="smali/com/example/app/MainActivity.smali", line=line, snippet="invoke-x")


def _component(name: str) -> Component:
    return Component(name=name, exported=True, source=_source())


def _chain(chain_id: str, *, sink: str = "loadUrl") -> Chain:
    return Chain(
        id=chain_id,
        entries=["com.example.app.MainActivity"],
        steps=[
            Step(
                order=0,
                description="deeplink -> loadUrl",
                from_="com.example.app.MainActivity->onCreate(Landroid/content/Intent;)V",
                to="com.example.app.Bridge->exec(Ljava/lang/String;)V",
                sink=sink,
                source=_source(),
            )
        ],
        evidence_complete=True,
    )


def _finding(chain_id: str, exploitability: Level) -> Finding:
    return Finding(
        chain_id=chain_id,
        title=f"finding {chain_id}",
        exploitability=exploitability,
        impact=Level.HIGH,
        confidence=Level.HIGH,
        summary="synthetic",
    )


def _sample_report() -> Report:
    """刻意让每个列表都**乱序**，用来验证输出被排序。"""
    return Report(
        meta=Meta(
            apk_path="app.apk",
            apk_sha256="0" * 64,
            package="com.example.app",
            version_name="1.0",
            version_code="1",
            target_sdk=31,
            analyzed_at="2026-10-19T00:00:00Z",
            tool_version="0.1.0",
            warnings=["w2", "w1"],
        ),
        components=[
            _component("com.example.app.C"),
            _component("com.example.app.A"),
            _component("com.example.app.B"),
        ],
        deeplinks=[
            Deeplink(id="bbbbbbbb", scheme="myapp", host="b.example.com", component="com.example.app.B"),
            Deeplink(id="aaaaaaaa", scheme="myapp", host="a.example.com", component="com.example.app.A"),
        ],
        webviews=[
            WebView(id="dddddddd", owner_class="com.example.app.D"),
            WebView(id="cccccccc", owner_class="com.example.app.C"),
        ],
        bridges=[
            Bridge(id="ffffffff", impl_class="com.example.app.F"),
            Bridge(id="eeeeeeee", impl_class="com.example.app.E"),
        ],
        chains=[_chain("22222222"), _chain("11111111")],
        findings=[
            _finding("33333333", Level.LOW),
            _finding("44444444", Level.HIGH),
            _finding("55555555", Level.MEDIUM),
        ],
        counter_examples=[
            CounterExample(
                entry_id="com.example.app.B",
                entry_kind=EntryKind.COMPONENT,
                failed_judgment="J2",
                reason="implementation class not found",
                source=_source(),
            ),
            CounterExample(
                entry_id="com.example.app.A",
                entry_kind=EntryKind.DEEPLINK,
                failed_judgment="J5",
                reason="no attacker-controlled flow",
                source=_source(),
            ),
        ],
    )


# --- §8.1：schema_version / summary --------------------------------------


def test_schema_version_and_summary_match_lists() -> None:
    report = _sample_report()
    data = json.loads(render_json(report))

    assert data["schema_version"] == "0.1"
    assert data["summary"] == {
        "components": 3,
        "deeplinks": 2,
        "webviews": 2,
        "bridges": 2,
        "chains": 2,
        "findings": 3,
        "counter_examples": 2,
    }


# --- §8.1：稳定排序 -------------------------------------------------------


def test_top_level_lists_sorted_by_id() -> None:
    data = json.loads(render_json(_sample_report()))

    for key in ("deeplinks", "webviews", "bridges", "chains"):
        ids = [item["id"] for item in data[key]]
        assert ids == sorted(ids), f"{key} 未按 id 排序：{ids}"

    # Component 的 id 是派生属性（不序列化），按同一个 stable id 口径比对
    normalized = normalize_report(_sample_report())
    rendered = [item["name"] for item in data["components"]]
    assert rendered == [component.name for component in normalized.components]


def test_findings_sorted_by_rank_not_by_id() -> None:
    """§6.5 排序优先于 §8.1 的“按 id”（D-066）。"""
    data = json.loads(render_json(_sample_report()))
    order = [(item["exploitability"], item["impact"], item["confidence"]) for item in data["findings"]]
    ranks = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    scores = [(ranks[e], ranks[i], ranks[c]) for e, i, c in order]
    assert scores == sorted(scores, reverse=True)
    assert data["findings"][0]["exploitability"] == "high"


def test_counter_examples_sorted_by_entry() -> None:
    data = json.loads(render_json(_sample_report()))
    entries = [item["entry_id"] for item in data["counter_examples"]]
    assert entries == sorted(entries)


# --- 确定性：两次渲染逐字节相同 -------------------------------------------


def test_same_report_renders_byte_identical() -> None:
    report = _sample_report()
    assert render_json(report) == render_json(report)


def test_only_analyzed_at_differs_between_runs() -> None:
    first = _sample_report()
    second = dataclasses.replace(
        first,
        meta=dataclasses.replace(first.meta, analyzed_at="2026-10-20T12:34:56Z"),
    )

    lines_first = render_json(first).splitlines()
    lines_second = render_json(second).splitlines()
    assert len(lines_first) == len(lines_second)

    differing = [
        (left, right)
        for left, right in zip(lines_first, lines_second, strict=True)
        if left != right
    ]
    assert len(differing) == 1, f"除 analyzed_at 外还有差异：{differing}"
    assert "analyzed_at" in differing[0][0]


# --- 编码与格式 -----------------------------------------------------------


def test_chinese_is_not_ascii_escaped() -> None:
    report = dataclasses.replace(
        _sample_report(),
        findings=[dataclasses.replace(_finding("33333333", Level.HIGH), title="深链 → 桥方法")],
    )
    text = render_json(report)
    assert "深链 → 桥方法" in text
    assert "\\u6df1" not in text


def test_indent_is_two_spaces_and_ends_with_single_newline() -> None:
    text = render_json(_sample_report())
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert '\n  "meta": {' in text
    assert '\n    "apk_path": "app.apk",' in text


def test_write_json_creates_parents_and_uses_lf(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.json"
    written = write_json(_sample_report(), target)

    assert written == target
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "不应写 BOM"
    assert b"\r\n" not in raw, "报告文件必须是 LF"
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8"))["schema_version"] == "0.1"


# --- 读回：explain 依赖 load_json ------------------------------------------


def test_load_json_round_trips(tmp_path: Path) -> None:
    report = _sample_report()
    path = write_json(report, tmp_path / "report.json")
    assert load_json(path) == normalize_report(report)


def test_report_json_distinguishes_explicit_and_inferred_export() -> None:
    data = json.loads(render_json(Report(
        meta=Meta(package="com.example.app"),
        components=[
            Component(name="com.example.Explicit", exported=False),
            Component(name="com.example.Inferred", exported=False, exported_inferred=True),
        ],
    )))
    assert [item["exported_inferred"] for item in data["components"]] == [False, True]


def test_load_json_rejects_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(IRDeserializeError):
        load_json(path)


def test_load_json_non_utf8_is_structured_input_error(tmp_path: Path) -> None:
    path = tmp_path / "gbk.json"
    path.write_bytes("{}".encode("gbk") + b"\x81")
    with pytest.raises(IRDeserializeError) as error:
        load_json(path)
    assert error.value.reason == "not_utf8"
    assert error.value.detail
    assert str(path) in str(error.value) and "不是 UTF-8" in str(error.value)


def test_load_json_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(IRDeserializeError):
        load_json(path)


# --- 端到端：真实 fixture case 的报告可往返 --------------------------------


def _report_from_case(case: Path) -> Report:
    """用 M1–M3 的现有能力拼一份报告（T4.1 不引入新的分析逻辑）。"""
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
    return Report(
        meta=Meta(
            apk_path=case.name + ".apk",
            package=manifest.package,
            target_sdk=manifest.target_sdk,
            analyzed_at="2026-10-19T00:00:00Z",
            tool_version="0.1.0",
            warnings=[*index.warnings, *warnings],
        ),
        components=components,
        deeplinks=deeplinks,
        webviews=webviews,
        bridges=bridges,
        chains=chains,
        findings=findings,
        counter_examples=counter_examples,
    )


def test_real_case_report_is_stable_and_round_trips() -> None:
    report = _report_from_case(CASES / "01_positive_deeplink_bridge_sink")

    text = render_json(report)
    assert text == render_json(_report_from_case(CASES / "01_positive_deeplink_bridge_sink"))

    data = json.loads(text)
    assert data["summary"] == report.summary()
    assert data["summary"]["findings"] == len(report.findings) >= 1

    restored = Report.from_dict(data)
    assert restored == normalize_report(report)
