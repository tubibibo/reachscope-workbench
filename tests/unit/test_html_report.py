"""T4.2 HTML 报告（PLAN §8.2）。

覆盖验收：单文件无外部资源/无 JS、九章节顺序、`<details>` 可展开、
`analyzable=false` 置顶警告、反例与判据打分渲染、自动转义、打印样式、UTF-8/LF。
"""

from __future__ import annotations

import re
from pathlib import Path

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
    Component,
    CounterExample,
    EntryKind,
    Meta,
    Protection,
    Report,
    SourceLoc,
)
from reachscope.report.html_report import render_html, write_html

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"

#: §8.2 的九个章节，顺序即验收顺序。
SECTION_IDS = (
    "title",
    "disclaimer",
    "input",
    "protection",
    "overview",
    "chains",
    "counter-examples",
    "methods",
    "limitations",
)


def _report_from_case(case: Path) -> Report:
    """用 M1–M3 的现有能力拼一份报告（与 test_json_report 的端到端口径一致）。"""
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
            apk_sha256="a" * 64,
            package=manifest.package,
            version_name="1.0",
            target_sdk=manifest.target_sdk,
            analyzed_at="2026-10-19T00:00:00Z",
            tool_version="0.1.0",
            warnings=[*index.warnings, *warnings],
        ),
        protection=Protection(detected=False, analyzable=True),
        components=components,
        deeplinks=deeplinks,
        webviews=webviews,
        bridges=bridges,
        chains=chains,
        findings=findings,
        counter_examples=counter_examples,
    )


def _unanalyzable_report() -> Report:
    return Report(
        meta=Meta(package="com.example.hardened"),
        protection=Protection(detected=True, tool="apkid", labels=["DexGuard"], analyzable=False),
    )


# --- §8.2：九个章节与顺序 ---------------------------------------------------


def test_nine_sections_appear_in_order() -> None:
    html = render_html(_report_from_case(CASES / "01_positive_deeplink_bridge_sink"))
    positions = [html.index(f'id="{section}"') for section in SECTION_IDS]
    assert positions == sorted(positions), "章节顺序不符合 §8.2"
    assert len(positions) == 9


# --- 单文件：无外部资源、无 JS ----------------------------------------------


def test_no_external_resources_or_scripts() -> None:
    html = render_html(_report_from_case(CASES / "01_positive_deeplink_bridge_sink"))
    lowered = html.lower()
    assert "<script" not in lowered
    assert "<link" not in lowered
    assert re.search(r'\bsrc\s*=', lowered) is None
    assert "http://" not in lowered and "https://" not in lowered
    assert "@import" not in lowered
    assert "@media print" in lowered, "缺少打印样式"


# --- 链路：步骤可展开、判据打分、证据位置 -----------------------------------


def test_chain_steps_use_details_and_show_evidence() -> None:
    report = _report_from_case(CASES / "01_positive_deeplink_bridge_sink")
    assert report.findings, "case 01 必须产出 finding（T5.1 基线）"
    html = render_html(report)

    assert "<details" in html
    assert "步骤（" in html
    finding = report.findings[0]
    chain = next(c for c in report.chains if c.id == finding.chain_id)
    step = chain.steps[0]
    assert step.source is not None
    assert f"{step.source.file}:{step.source.line}" in html
    assert "判据打分" in html
    # J6 的理由来自判定本身（不是模板里的固定文案）
    assert any(judgment.name == "J6" for judgment in chain.judgments)
    assert chain.rank.exploitability is finding.exploitability


def test_counter_examples_are_rendered() -> None:
    report = _report_from_case(CASES / "02_signature_permission")
    assert report.counter_examples
    html = render_html(report)
    counter = report.counter_examples[0]
    assert counter.entry_id in html
    assert counter.reason in html
    assert "signature-level permission" in html


# --- 加固：整页置顶警告 ------------------------------------------------------


def test_unanalyzable_banner_is_at_the_top() -> None:
    html = render_html(_unanalyzable_report())
    banner = html.index('class="banner"')
    title = html.index('id="title"')
    assert banner < title
    assert "无法分析" in html
    assert "DexGuard" in html


def test_analyzable_report_has_no_banner() -> None:
    html = render_html(_report_from_case(CASES / "01_positive_deeplink_bridge_sink"))
    assert 'class="banner"' not in html


# --- 空入口：显式写“未发现入口” --------------------------------------------


def test_no_entries_is_stated_explicitly() -> None:
    report = Report(meta=Meta(package="com.example.empty"))
    html = render_html(report)
    assert "未发现入口" in html
    assert "未发现满足纳入条件的链路" in html


def test_inferred_export_conclusion_is_not_absolute() -> None:
    report = Report(
        meta=Meta(package="com.example.inferred"),
        components=[Component(name="com.example.inferred.Main", exported=False, exported_inferred=True)],
    )
    html = render_html(report)
    assert "已明确声明" in html
    assert "推断" in html
    assert "没有声明可被第三方触达的组件" not in html


# --- 自动转义：类名/理由里的 HTML 不能变成标记 -------------------------------


def test_user_controlled_text_is_escaped() -> None:
    """APK 里的类名/字符串会进报告；模板必须自动转义，不能变成可执行标记。"""
    name = "com.example.app.<script>alert(1)</script>"
    report = Report(
        meta=Meta(package="com.example.app"),
        counter_examples=[
            CounterExample(
                entry_id=name,
                entry_kind=EntryKind.COMPONENT,
                failed_judgment="J5",
                reason="no sink",
                source=SourceLoc(file="AndroidManifest.xml", line=12),
            )
        ],
    )

    html = render_html(report)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# --- 写文件：UTF-8、LF ------------------------------------------------------


def test_write_html_uses_utf8_and_lf(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.html"
    written = write_html(_report_from_case(CASES / "01_positive_deeplink_bridge_sink"), target)
    assert written == target

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert "ReachScope 分析报告".encode() in raw
