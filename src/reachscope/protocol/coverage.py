"""Report evidence coverage, distinct from whole-program completeness.

A clean parse does not prove that every runtime path was modeled. Fixed analysis
limits are always disclosed; actual warnings separately determine whether a
report can support an evidence-consistency verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ir.model import Report
from ..ir.serialize import IRSerializable

ANALYSIS_LIMITATIONS: tuple[str, ...] = (
    "Call paths are bounded to depth 4.",
    "Component transfer is limited to one explicit Intent hop within the APK.",
    "Data flow is not fully branch/path sensitive; a candidate path may be infeasible.",
    "Reflection, JNI, dynamic loading and asynchronous callbacks are not fully modeled.",
    "Parameter and instance/alias propagation are incomplete.",
    "Matching report evidence is not proof of runtime exploitability or of application safety.",
)


@dataclass(frozen=True)
class CoverageView(IRSerializable):
    """The legacy closed_world key never claims whole-program completeness."""

    closed_world: bool = False
    reasons: list[str] = field(default_factory=list)
    scope: str = "static_analysis_report"
    report_usable: bool = True
    negative_conclusions_limited: bool = True
    limitations: list[str] = field(default_factory=lambda: list(ANALYSIS_LIMITATIONS))

    @classmethod
    def from_report(cls, report: Report) -> CoverageView:
        """从报告派生；只读 IR，不重新分析 APK。"""
        reasons: list[str] = []

        protection = report.protection
        if protection.analyzable is False:
            reasons.append("protection.analyzable=false：加固导致分析被跳过")
        for label in protection.labels:
            lowered = label.lower()
            if "packer" in lowered or "obfusc" in lowered or "dexguard" in lowered:
                reasons.append(f"protection.label={label}：加固/混淆可能隐藏代码")
                break

        if any(component.exported_inferred and not component.exported for component in report.components):
            reasons.append(
                "Component.exported_inferred=true：未导出状态来自推断，不能作为显式访问边界"
            )

        warnings = report.meta.warnings
        if warnings:
            reasons.append(
                f"meta.warnings={len(warnings)} 条：分析存在降级、未知语法或解析失败"
            )

        index_meta: Any = getattr(report.meta, "index", None)
        mode = _index_mode(index_meta)
        if mode is not None and mode not in ("full", "complete"):
            reasons.append(f"meta.index.mode={mode}：索引不是完整模式")

        return cls(reasons=reasons, report_usable=not reasons)


def _index_mode(index_meta: Any) -> str | None:
    """读取未来的 `Meta.index.mode`；当前 v0.1 报告没有该字段。"""
    if isinstance(index_meta, dict):
        mode = index_meta.get("mode")
        return mode if isinstance(mode, str) else None
    mode = getattr(index_meta, "mode", None)
    return mode if isinstance(mode, str) else None


__all__ = ["ANALYSIS_LIMITATIONS", "CoverageView"]
