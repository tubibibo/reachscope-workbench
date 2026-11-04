"""T4.3 分析管线：解码产物 → `Report`（不碰 apktool、不写文件）。"""

from __future__ import annotations

from pathlib import Path

from reachscope.analyze.pipeline import analyze_workdir
from reachscope.ir.model import Protection, Report

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"
FIXED_TIME = "2026-10-19T00:00:00+00:00"


def _analyze(case: Path, protection: Protection | None = None) -> Report:
    return analyze_workdir(
        case,
        protection=protection or Protection(detected=False),
        apk_path="sample.apk",
        apk_sha256="b" * 64,
        apktool_version="2.11.1",
        analyzed_at=FIXED_TIME,
    )


def test_pipeline_populates_report_from_fixture() -> None:
    report = _analyze(CASES / "01_positive_deeplink_bridge_sink")

    assert report.meta.package == "com.example.app"
    assert report.meta.analyzed_at == FIXED_TIME
    assert report.meta.apktool_version == "2.11.1"
    assert report.meta.tool_version
    assert report.components and report.deeplinks and report.bridges
    assert len(report.findings) == 1
    assert report.counter_examples == []
    assert report.chains[0].judgments  # D-067：判定已写回链


def test_pipeline_is_deterministic() -> None:
    first = _analyze(CASES / "01_positive_deeplink_bridge_sink")
    second = _analyze(CASES / "01_positive_deeplink_bridge_sink")
    assert first.to_dict() == second.to_dict()


def test_pipeline_collects_protection_warnings() -> None:
    protection = Protection(
        detected=None, analyzable=True, warnings=["apkid 未安装或调用失败"]
    )
    report = _analyze(CASES / "01_positive_deeplink_bridge_sink", protection)
    assert "apkid 未安装或调用失败" in report.meta.warnings


def test_unanalyzable_protection_short_circuits_without_parsing(tmp_path: Path) -> None:
    """强加固：不读解码产物（目录可以不存在），返回带 protection 的空报告。"""
    report = _analyze(
        tmp_path / "does-not-exist",
        Protection(detected=True, labels=["packer::dexguard"], analyzable=False),
    )
    assert report.protection.analyzable is False
    assert report.components == []
    assert report.chains == []
    assert report.findings == []
    assert report.counter_examples == []
