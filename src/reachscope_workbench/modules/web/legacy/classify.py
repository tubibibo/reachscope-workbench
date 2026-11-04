"""资产指纹分类引擎：多信号加权打分。

为什么不是「优先级 if-else」：
    7 条硬编码 `in` 判断无法回答两个必被追问的问题——
    「两条规则同时命中怎么办」和「误判率多少」。
    加权打分给出 score，再用 confidence + evidence 解释判定依据，
    于是这两个问题都有答案。

规则数据全部来自 rules/classify_rules.yaml，本模块**不含任何规则字面量**
（唯一例外是 unknown 兜底）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from .models import Asset, Classification

RULES_FILE = Path(__file__).parent / "rules" / "classify_rules.yaml"

UNKNOWN = "unknown"


@dataclass
class Signal:
    field: str
    pattern: str
    weight: float


@dataclass
class ClassifyRule:
    tech: str
    category: str
    display_name: str = ""
    signals: list[Signal] = field(default_factory=list)
    confidence_at: float = 1.0

    @property
    def max_weight(self) -> float:
        return max((s.weight for s in self.signals), default=1.0)


def _load_file(path: Path) -> dict[str, Any]:
    """按后缀分派解析器，保留 JSON 降级能力。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return cast("dict[str, Any]", yaml.safe_load(text) or {})
    import json

    return cast("dict[str, Any]", json.loads(text))


def load_rules(path: Path | None = None) -> list[ClassifyRule]:
    """加载分类规则。规则顺序即优先级（平局时靠前的胜出）。"""
    data = _load_file(path or RULES_FILE)
    rules: list[ClassifyRule] = []
    for item in data.get("rules", []):
        signals = [
            Signal(
                field=str(s.get("field", "")),
                pattern=str(s.get("pattern", "")),
                weight=float(s.get("weight", 1.0)),
            )
            for s in item.get("signals", [])
        ]
        if not signals:
            continue
        rules.append(
            ClassifyRule(
                tech=str(item.get("tech", "")),
                category=str(item.get("category", UNKNOWN)),
                display_name=str(item.get("display_name", "")),
                signals=signals,
                confidence_at=float(item.get("confidence_at", 0.0)) or 0.0,
            )
        )
    return rules


def _field_value(asset: Asset, field_name: str) -> str:
    value = getattr(asset, field_name, "")
    return "" if value is None else str(value)


def _signal_hit(asset: Asset, signal: Signal) -> bool:
    value = _field_value(asset, signal.field).strip().lower()
    pattern = signal.pattern.strip().lower()
    if not value or not pattern:
        return False
    # 端口是离散值，必须精确相等，否则 "808" 会误伤 "8080"
    if signal.field == "port":
        return value == pattern
    return pattern in value


def classify_asset(asset: Asset, rules: list[ClassifyRule]) -> Classification:
    """对单条资产打分，返回得分最高的类别 + 置信度 + 命中证据。"""
    best: Classification | None = None
    best_score = 0.0

    for rule in rules:
        score = 0.0
        evidence: list[str] = []
        for signal in rule.signals:
            if _signal_hit(asset, signal):
                score += signal.weight
                evidence.append(
                    f"{signal.field}={_field_value(asset, signal.field)!r} 命中 {signal.pattern!r} (+{signal.weight})"
                )
        if score <= 0:
            continue
        if score > best_score:
            best_score = score
            # 置信基线取「最强单项权重 × 1.5」：
            # 只命中一个信号 ≈ 0.67（证据单薄），命中多个独立信号才接近满分。
            # 这样 confidence 才有区分度，而不是清一色 1.0。
            baseline = rule.confidence_at or (rule.max_weight * 1.5)
            confidence = min(1.0, score / baseline) if baseline > 0 else 1.0
            best = Classification(
                category=rule.category,
                tech=rule.tech,
                confidence=round(confidence, 3),
                evidence=evidence,
            )

    if best is None:
        return Classification(category=UNKNOWN, tech="", confidence=0.0, evidence=[])
    return best


def classify_assets(assets: list[Asset], rules: list[ClassifyRule] | None = None) -> list[Classification]:
    """批量分类，并把结果回填到 Asset 上（供报告与分组使用）。"""
    active_rules = rules if rules is not None else load_rules()
    results: list[Classification] = []
    for asset in assets:
        result = classify_asset(asset, active_rules)
        asset.category = result.category
        asset.tech = result.tech
        asset.confidence = result.confidence
        asset.evidence = list(result.evidence)
        results.append(result)
    return results
