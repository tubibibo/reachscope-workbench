"""攻击路径推理引擎。

它回答的问题和扫描器不同：
    扫描器 → 「有什么」
    本引擎 → 「拿到这个之后，下一步能走到哪，最后能摸到什么」

思路来自 BloodHound（内网攻击路径图），但场景是外网 Web 资产。
把「打穿短表」里每条经验形式化为一次**状态转移**：
    前置（资产特征 + 已具备能力） → 动作 → 产出能力
然后做多跳搜索，找到从「公网可达」到「高价值终点」的链条，
并按可行性与跳数排序，同时把每一步的「假点」作为验证提示带出来。

当前实现的边界：
    路径在**单个资产内**展开（能力在该资产上累积）。
    跨资产的能力传递（如拿到的票据用于另一个资产）留待后续——
    过早支持会让路径爆炸，且多数场景单资产链条已足够说明问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from .models import Asset

RULES_FILE = Path(__file__).parent / "rules" / "transitions.yaml"

PUBLIC_CAPABILITY = "public_reach"

# 跳数惩罚系数：每多一跳可行性会衰减，避免 4 跳的弱链压过 2 跳的强链
DEPTH_PENALTY = 0.12


@dataclass
class Capability:
    """能力 / 状态：路径上的节点。"""

    id: str
    label: str = ""
    value: int = 0
    terminal: bool = False


@dataclass
class Transition:
    """一次状态转移（来自 transitions.yaml）。"""

    id: str
    name: str = ""
    from_tech: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    produces: str = ""
    weight: float = 0.5
    action: str = ""
    success_signal: str = ""
    false_positive: list[str] = field(default_factory=list)
    knowledge_ref: list[str] = field(default_factory=list)


@dataclass
class PathStep:
    transition: Transition
    gain: str = ""
    depth: int = 1


@dataclass
class AttackPath:
    asset: Asset
    steps: list[PathStep] = field(default_factory=list)
    target: str = ""
    score: float = 0.0
    feasibility: float = 0.0
    cautions: list[str] = field(default_factory=list)

    @property
    def hops(self) -> int:
        return len(self.steps)

    @property
    def is_chain(self) -> bool:
        """是否多跳链。

        一跳直达（如 Redis 未授权直接拿凭据）价值高但没有「推理」成分，
        扫描器也能列出来。多跳链才是本引擎的差异化输出，
        展示时需要单独分区置顶。
        """
        return len(self.steps) > 1

    @property
    def chain(self) -> str:
        """人类可读的链条，如：公网可达 → 接口清单 → 未授权读 → 他人业务数据"""
        labels = [PUBLIC_CAPABILITY] + [s.gain for s in self.steps]
        return " → ".join(labels)


def _load_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return cast("dict[str, Any]", yaml.safe_load(text) or {})
    import json

    return cast("dict[str, Any]", json.loads(text))


def load_transition_rules(
    path: Path | None = None,
) -> tuple[dict[str, Capability], list[Transition]]:
    """加载能力表与转移规则。数据全在 YAML，本模块不含规则字面量。"""
    data = _load_file(path or RULES_FILE)

    capabilities: dict[str, Capability] = {}
    for item in data.get("capabilities", []):
        cap = Capability(
            id=str(item.get("id", "")),
            label=str(item.get("label", "")),
            value=int(item.get("value", 0)),
            terminal=bool(item.get("terminal", False)),
        )
        if cap.id:
            capabilities[cap.id] = cap

    transitions: list[Transition] = []
    for item in data.get("transitions", []):
        transitions.append(
            Transition(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                from_tech=[str(t) for t in item.get("from_tech", [])],
                requires=[str(t) for t in item.get("requires", [])],
                produces=str(item.get("produces", "")),
                weight=float(item.get("weight", 0.5)),
                action=str(item.get("action", "")),
                success_signal=str(item.get("success_signal", "")),
                false_positive=[str(t) for t in item.get("false_positive", [])],
                knowledge_ref=[str(t) for t in item.get("knowledge_ref", [])],
            )
        )
    return capabilities, transitions


def _matches_asset(transition: Transition, asset: Asset) -> bool:
    """空 from_tech 表示任意资产可用（这类规则通常靠 requires 约束）。"""
    if not transition.from_tech:
        return True
    return asset.tech in transition.from_tech or asset.category in transition.from_tech


def _walk_from_asset(
    asset: Asset,
    capabilities: dict[str, Capability],
    transitions: list[Transition],
    max_depth: int,
    confidence_factor: float,
) -> list[AttackPath]:
    """从单条资产出发做多跳搜索，返回到达高价值终点的所有路径。

    单独抽成函数、而不是在 build_paths 的循环里定义闭包，
    是为了避免闭包捕获循环变量（延迟绑定隐患，ruff B023）。
    """
    results: list[AttackPath] = []

    def walk(current: frozenset[str], steps: list[PathStep]) -> None:
        if len(steps) >= max_depth:
            return
        for transition in transitions:
            if not _matches_asset(transition, asset):
                continue
            if transition.produces in current:
                continue
            if not set(transition.requires) <= current:
                continue

            step = PathStep(transition=transition, gain=transition.produces,
                            depth=len(steps) + 1)
            new_steps = steps + [step]
            new_caps = current | {transition.produces}

            target_cap = capabilities.get(transition.produces)
            if target_cap is not None and target_cap.terminal:
                feasibility = 1.0
                for s in new_steps:
                    feasibility *= s.transition.weight
                feasibility *= confidence_factor
                penalty = 1.0 / (1.0 + DEPTH_PENALTY * (len(new_steps) - 1))
                score = target_cap.value * feasibility * penalty

                cautions: list[str] = []
                for s in new_steps:
                    for fp in s.transition.false_positive:
                        if fp not in cautions:
                            cautions.append(fp)

                results.append(
                    AttackPath(
                        asset=asset,
                        steps=new_steps,
                        target=transition.produces,
                        score=round(score, 3),
                        feasibility=round(feasibility, 3),
                        cautions=cautions,
                    )
                )

            walk(new_caps, new_steps)

    walk(frozenset({PUBLIC_CAPABILITY}), [])
    return results


def build_paths(
    assets: list[Asset],
    capabilities: dict[str, Capability] | None = None,
    transitions: list[Transition] | None = None,
    max_depth: int = 4,
    max_paths: int = 40,
    keep_per_target: int = 2,
) -> list[AttackPath]:
    """对每条资产做多跳搜索，返回按分数排序的攻击路径。

    搜索约束：
      - 已获得的能力不再重复走（自然避免环路）
      - 深度上限 max_depth，避免长链噪音
      - 同一资产的同一终点最多保留 keep_per_target 条最优路径
    """
    if capabilities is None or transitions is None:
        loaded_caps, loaded_trans = load_transition_rules()
        capabilities = capabilities or loaded_caps
        transitions = transitions or loaded_trans

    found: list[AttackPath] = []

    for asset in assets:
        # 分类置信度参与可行性：证据单薄的资产，路径可信度也该打折
        confidence_factor = 0.5 + 0.5 * max(asset.confidence, 0.0)
        found.extend(
            _walk_from_asset(asset, capabilities, transitions, max_depth, confidence_factor)
        )

    # 排序：分数降序；同分用跳数少的优先
    found.sort(key=lambda p: (-p.score, p.hops, p.asset.host))

    # 同一资产同一终点只保留最优的几条，避免同一条链换个中间步骤重复刷屏
    kept: list[AttackPath] = []
    # Workbench adaptation: separate services on the same hostname must not
    # consume one another's candidate-path quota.
    counter: dict[tuple[int, str], int] = {}
    for path in found:
        key = (id(path.asset), path.target)
        count = counter.get(key, 0)
        if count >= keep_per_target:
            continue
        counter[key] = count + 1
        kept.append(path)
        if len(kept) >= max_paths:
            break
    return kept


def chains(paths: list[AttackPath]) -> list[AttackPath]:
    """只保留多跳链 —— 这是本引擎独有的输出。"""
    return [p for p in paths if p.is_chain]


def direct_hits(paths: list[AttackPath]) -> list[AttackPath]:
    """一跳直达的高价值面（有价值，但不是「推理」出来的）。"""
    return [p for p in paths if not p.is_chain]


def summarize(paths: list[AttackPath]) -> dict[str, int]:
    """按终点能力统计路径数，供报告概览使用。"""
    result: dict[str, int] = {}
    for path in paths:
        result[path.target] = result.get(path.target, 0) + 1
    return dict(sorted(result.items(), key=lambda kv: -kv[1]))
