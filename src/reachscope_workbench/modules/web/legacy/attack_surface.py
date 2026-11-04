"""攻击面映射引擎。

把分类结果映射为可执行清单。每条规则输出四元组：

    tactics（打哪） / success_signal（出什么算成）
    / false_positive（什么算假点） / knowledge_ref（参考主题标签）

「假点」这一列标记「看起来可疑、实际不成立」的情形，
用于减少误报。规则文本与判据都在 rules/ 下，可逐条核对。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from .models import Asset, AttackSurface, SurfaceRule

RULES_FILE = Path(__file__).parent / "rules" / "attack_surface_rules.yaml"

# 文件里的规则被删干净时的最后兜底（唯一允许的硬编码规则）
_FALLBACK = SurfaceRule(
    category="unknown",
    display_name="未识别资产",
    priority=5,
    tactics=["人工确认资产归属与用途，再决定投入"],
    success_signal="—",
    false_positive=["不属于目标主体"],
    knowledge_ref=["asset discovery"],
)


def _load_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return cast("dict[str, Any]", yaml.safe_load(text) or {})
    import json

    return cast("dict[str, Any]", json.loads(text))


def load_surface_rules(path: Path | None = None) -> tuple[dict[str, SurfaceRule], dict[str, SurfaceRule]]:
    """返回 (按 tech 索引, 按 category 索引) 两份映射。"""
    data = _load_file(path or RULES_FILE)
    by_tech: dict[str, SurfaceRule] = {}
    by_category: dict[str, SurfaceRule] = {}
    for item in data.get("rules", []):
        rule = SurfaceRule(
            category=str(item.get("key", "")),
            display_name=str(item.get("display_name", "")),
            priority=int(item.get("priority", 5)),
            tactics=[str(t) for t in item.get("tactics", [])],
            success_signal=str(item.get("success_signal", "")),
            false_positive=[str(t) for t in item.get("false_positive", [])],
            knowledge_ref=[str(t) for t in item.get("knowledge_ref", [])],
        )
        if not rule.category:
            continue
        if str(item.get("match", "tech")) == "category":
            by_category[rule.category] = rule
        else:
            by_tech[rule.category] = rule
    return by_tech, by_category


def _lookup(asset: Asset, by_tech: dict[str, SurfaceRule],
            by_category: dict[str, SurfaceRule]) -> SurfaceRule:
    """tech 精确匹配优先，匹配不到再用 category 兜底。"""
    if asset.tech and asset.tech in by_tech:
        return by_tech[asset.tech]
    if asset.category and asset.category in by_category:
        return by_category[asset.category]
    if asset.category and asset.category in by_tech:
        return by_tech[asset.category]
    return _FALLBACK


def build_surfaces(
    assets: list[Asset],
    rules: tuple[dict[str, SurfaceRule], dict[str, SurfaceRule]] | None = None,
) -> list[AttackSurface]:
    """按攻击面分组资产，并按优先级排序（P1 在前）。"""
    by_tech, by_category = rules if rules is not None else load_surface_rules()
    grouped: dict[str, AttackSurface] = {}

    for asset in assets:
        rule = _lookup(asset, by_tech, by_category)
        surface = grouped.get(rule.category)
        if surface is None:
            surface = AttackSurface(
                category=rule.category,
                display_name=rule.display_name,
                priority=rule.priority,
                tactics=list(rule.tactics),
                success_signal=rule.success_signal,
                false_positive=list(rule.false_positive),
                knowledge_ref=list(rule.knowledge_ref),
            )
            grouped[rule.category] = surface
        surface.assets.append(asset)

    surfaces = list(grouped.values())
    # 优先级升序（P1 在前）；同级按资产数降序
    surfaces.sort(key=lambda s: (s.priority, -len(s.assets), s.category))
    return surfaces
