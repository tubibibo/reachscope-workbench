"""模型提交的 claim（协议 v0.1）。

模型只能提交**结构化断言**，不能提交自由文本结论：

```json
{
  "schema_version": "0.1",
  "kind": "reachability",
  "entry": {"kind": "component", "name": "com.example.app.MainActivity"},
  "sink": {"kind": "file"},
  "asserted_steps": [{"sink": "webview"}, {"sink": "bridge_method"}, {"sink": "file"}],
  "assumptions": [{"id": "a-1", "text": "页面 URL 可由第三方控制"}]
}
```

校验口径：

- 未知键忽略（前向兼容，与 IR 的 D-012 一致）；
- 缺 `kind`、`entry` 无法定位、`sink` 词表外取值、步骤 span 词表外取值
  → :class:`ClaimError`（CLI 退出码 2）；
- `claim_id` 缺省时由**去掉 `claim_id` 的规范化 JSON** 生成，同一输入稳定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from ..ir.model import SinkKind
from ..ir.serialize import (
    IRDeserializeError,
    IRSerializable,
    deserialize,
    serialize,
    stable_id,
)

#: 协议 schema 版本；与报告 IR 的 `SCHEMA_VERSION` 独立演进。
PROTOCOL_SCHEMA_VERSION = "0.2"
SUPPORTED_INPUT_VERSIONS: frozenset[str] = frozenset({"0.1", PROTOCOL_SCHEMA_VERSION})

#: `Step.sink` 现有词表（`Step` 用字符串而非枚举，见 `ir/model.py`）。
STEP_SINK_KINDS: frozenset[str] = frozenset(
    {kind.value for kind in SinkKind} | {"bridge_method", "call", "file_ownership"}
)

#: claim 的 `sink.kind` 允许值：步骤词表 + `any` + 聚合别名 `bridge`。
CLAIM_SINK_KINDS: frozenset[str] = STEP_SINK_KINDS | {"any", "bridge"}


class ClaimError(ValueError):
    """claim / 回答文件非法（语法、必填、词表或多义）。"""


class ClaimKind(StrEnum):
    """首版只支持「入口 → sink 可达性」。"""

    REACHABILITY = "reachability"


class EntryRefKind(StrEnum):
    """claim 指向的入口类别。"""

    COMPONENT = "component"
    DEEPLINK = "deeplink"


@dataclass(frozen=True)
class EntryRef(IRSerializable):
    """入口引用。`id` 优先于 `name`；两者至少一个非空。"""

    kind: EntryRefKind = EntryRefKind.COMPONENT
    name: str = ""
    id: str = ""

    def validate(self) -> None:
        """至少给出 id 或 name。"""
        if not self.id.strip() and not self.name.strip():
            raise ClaimError("claim.entry 需要 id 或 name（至少一个）")


@dataclass(frozen=True)
class SinkRef(IRSerializable):
    """sink 引用。`id` 目前只作备注（IR 的 Sink 没有稳定 ID）。"""

    kind: str = ""
    id: str = ""

    def validate(self) -> None:
        """`kind` 必填且必须在词表内。"""
        if not self.kind:
            raise ClaimError("claim.sink.kind 不能为空")
        if self.kind not in CLAIM_SINK_KINDS:
            allowed = ", ".join(sorted(CLAIM_SINK_KINDS))
            raise ClaimError(f"claim.sink.kind 非法：{self.kind!r}（允许：{allowed}）")


@dataclass(frozen=True)
class StepRef(IRSerializable):
    """`asserted_steps` 的一步，按 `Step.sink` 词表声明。"""

    sink: str = ""

    def validate(self) -> None:
        """步骤词表外的值一律拒绝，避免模型自造数据流。"""
        if not self.sink:
            raise ClaimError("claim.asserted_steps[].sink 不能为空")
        if self.sink not in STEP_SINK_KINDS:
            allowed = ", ".join(sorted(STEP_SINK_KINDS))
            raise ClaimError(
                f"claim.asserted_steps[].sink 非法：{self.sink!r}（允许：{allowed}）"
            )


@dataclass(frozen=True)
class Assumption(IRSerializable):
    """显式前置假设。带假设的 claim 永远不可能拿到 `SUPPORTED`。"""

    id: str = ""
    text: str = ""
    source: str = "model"

    def validate(self) -> None:
        """假设必须有 id 与正文，便于在 verdict 里逐条回显。"""
        if not self.id.strip():
            raise ClaimError("claim.assumptions[].id 不能为空")
        if not self.text.strip():
            raise ClaimError("claim.assumptions[].text 不能为空")


@dataclass(frozen=True)
class Claim(IRSerializable):
    """一条可达性 claim。"""

    schema_version: str = PROTOCOL_SCHEMA_VERSION
    claim_id: str = ""
    kind: ClaimKind = ClaimKind.REACHABILITY
    entry: EntryRef = field(default_factory=EntryRef)
    sink: SinkRef | None = None
    asserted_steps: list[StepRef] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """解析并校验；失败统一抛 :class:`ClaimError`。"""
        try:
            claim = deserialize(cls, data)
        except IRDeserializeError as exc:
            raise ClaimError(f"claim 解析失败：{exc}") from exc
        _validate(claim)
        claim = replace(claim, schema_version=PROTOCOL_SCHEMA_VERSION)
        if not claim.claim_id.strip():
            claim = replace(claim, claim_id=_canonical_claim_id(claim))
        return claim

    def to_dict(self) -> dict[str, Any]:
        """序列化（`claim_id` 若为空则补算，保证输出自洽）。"""
        data = super().to_dict()
        if not self.claim_id.strip():
            data["claim_id"] = _canonical_claim_id(self)
        return data


def load_claim(path: str | Path) -> Claim:
    """从 JSON 文件读取 claim。"""
    claim_path = Path(path)
    try:
        raw = claim_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClaimError(f"claim 文件无法读取：{claim_path}（{exc}）") from exc
    return parse_claim(raw, source=str(claim_path))


def parse_claim(raw: str, *, source: str = "<claim>") -> Claim:
    """从 JSON 文本读取 claim。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaimError(f"claim 不是合法 JSON（{source}）：{exc}") from exc
    if not isinstance(data, dict):
        raise ClaimError(f"claim 顶层必须是 JSON 对象（{source}）")
    return Claim.from_dict(data)


def _validate(claim: Claim) -> None:
    """字段级校验；错误信息带字段名，便于模型自我纠正。"""
    if claim.schema_version not in SUPPORTED_INPUT_VERSIONS:
        raise ClaimError(
            f"不支持的 claim.schema_version：{claim.schema_version!r}"
            f"（接受 {', '.join(sorted(SUPPORTED_INPUT_VERSIONS))}）"
        )
    claim.entry.validate()
    if claim.sink is not None:
        claim.sink.validate()
    for step in claim.asserted_steps:
        step.validate()
    seen: set[str] = set()
    for assumption in claim.assumptions:
        assumption.validate()
        if assumption.id in seen:
            raise ClaimError(f"claim.assumptions 的 id 重复：{assumption.id!r}")
        seen.add(assumption.id)


def _canonical_claim_id(claim: Claim) -> str:
    """由规范化 JSON（排除 `claim_id`）生成稳定 ID。"""
    # 直接走 serialize，避免调用 `Claim.to_dict()` 造成无限递归。
    data: dict[str, Any] = serialize(claim)
    data.pop("claim_id", None)
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return stable_id("claim", canonical)


__all__ = [
    "CLAIM_SINK_KINDS",
    "PROTOCOL_SCHEMA_VERSION",
    "STEP_SINK_KINDS",
    "Assumption",
    "Claim",
    "ClaimError",
    "ClaimKind",
    "EntryRef",
    "EntryRefKind",
    "SinkRef",
    "StepRef",
    "load_claim",
    "parse_claim",
]
