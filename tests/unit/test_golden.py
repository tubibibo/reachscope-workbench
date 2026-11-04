"""T5.2 golden 回归：9 个 fixture case 的完整报告逐字节比对。

golden 覆盖**整份** `Report.to_dict()`（元信息、组件、深链、WebView、桥、链、
判据、finding、反例），因此任何一层行为变化都会体现在 diff 里。

- 生成/更新：`UPDATE_GOLDEN=1 pytest tests/unit/test_golden.py`
- 固定 `analyzed_at`，否则时间戳每次都不同（§9.3 只允许这一处差异）
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

import pytest

from reachscope.analyze.pipeline import analyze_workdir
from reachscope.ir.model import Protection
from reachscope.report.json_report import normalize_report

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"
GOLDEN = Path(__file__).resolve().parent.parent / "golden"
FIXED_AT = "2026-01-01T00:00:00+00:00"


def case_dirs() -> list[Path]:
    return sorted(d for d in CASES.iterdir() if d.is_dir())


def _protection(case: Path) -> Protection:
    path = case / "protection.json"
    if not path.exists():
        return Protection()
    return Protection.from_dict(json.loads(path.read_text(encoding="utf-8")))


def build_report(case: Path) -> dict:
    report = analyze_workdir(case, protection=_protection(case), analyzed_at=FIXED_AT)
    return normalize_report(report).to_dict()


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def golden_path(case: Path) -> Path:
    return GOLDEN / f"{case.name}.json"


def test_golden_directory_matches_cases() -> None:
    """守门：每个 case 恰好一个 golden，且没有孤儿文件。"""
    assert GOLDEN.is_dir(), f"缺少 {GOLDEN}"
    expected = {f"{c.name}.json" for c in case_dirs()}
    actual = {p.name for p in GOLDEN.glob("*.json")}
    assert actual == expected, f"golden 与 case 不配对：多 {actual - expected}，少 {expected - actual}"


@pytest.mark.parametrize("case", case_dirs(), ids=lambda c: c.name)
def test_case_matches_golden(case: Path) -> None:
    path = golden_path(case)
    actual = render(build_report(case))

    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        pytest.skip("UPDATE_GOLDEN=1：已重写 golden")

    assert path.is_file(), f"缺少 golden：{path}（用 UPDATE_GOLDEN=1 生成）"
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"golden/{path.name}",
                tofile=f"actual/{path.name}",
            )
        )
        pytest.fail(f"{case.name} 输出与 golden 不一致（UPDATE_GOLDEN=1 可更新）：\n{diff}")


def test_analysis_is_deterministic() -> None:
    """同一 case 连续两次分析，除固定时间戳外逐字段相同（§9.3）。"""
    for case in case_dirs():
        first = render(build_report(case))
        second = render(build_report(case))
        assert first == second, f"{case.name} 两次分析结果不同"
