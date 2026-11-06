"""IR 对象的通用双向序列化与稳定 ID。

按 T0.2 要求**不引入 pydantic**：基于 ``dataclasses.fields()`` 与
``typing.get_type_hints()`` 做递归转换，支持：

- 嵌套 dataclass
- ``enum.Enum`` / ``StrEnum``（序列化为 ``.value``）
- ``list[X]``、``dict[str, X]``
- ``X | None`` 与 ``Optional[X]``
- ``field(metadata={"alias": "..."})`` 改名（唯一用途：`Step.from_` → JSON 键 `from`）

反序列化失败一律抛 :class:`IRDeserializeError`，并带上字段路径。
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import types
import typing
from functools import cache
from typing import Any, Self, TypeVar, cast

T = TypeVar("T")

#: `field(metadata=...)` 中用于指定 JSON 键名的键。
ALIAS_KEY = "alias"

#: `{kind}|{key}` 的分隔符，固定不变（见 DECISIONS.md D-010）。
ID_SEPARATOR = "|"

#: stable_id 截取长度（PLAN §9.3：sha1 前 8 位）。
ID_LENGTH = 8

_MISSING = object()


class IRDeserializeError(ValueError):
    """IR 反序列化失败：字段取值或类型非法。"""

    def __init__(self, message: str, *, reason: str = "invalid_data", detail: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.detail = detail


class IRSerializable:
    """所有 IR dataclass 的公共基类，只提供 `to_dict()` / `from_dict()` 转发。"""

    def to_dict(self) -> dict[str, Any]:
        """把当前对象转成可 `json.dumps` 的 dict（枚举转为其字符串值）。"""
        return cast("dict[str, Any]", serialize(self))

    @classmethod
    def from_dict(cls: type[Self], data: dict[str, Any]) -> Self:
        """从 dict 还原对象；未知键忽略，非法取值抛 :class:`IRDeserializeError`。"""
        return deserialize(cls, data)


__all__ = [
    "ID_LENGTH",
    "ID_SEPARATOR",
    "IRDeserializeError",
    "IRSerializable",
    "deserialize",
    "serialize",
    "stable_id",
]


def stable_id(kind: str, key: str) -> str:
    """对 `(kind, 规范化键)` 取 sha1 前 8 位作为稳定 ID。

    规范化只做首尾空白 strip，**不做大小写折叠**（类名/路径大小写敏感）。
    """
    normalized = f"{kind.strip()}{ID_SEPARATOR}{key.strip()}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:ID_LENGTH]


def serialize(obj: Any) -> Any:
    """把 IR 对象（含嵌套结构）递归转成 JSON 友好的基本类型。"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            _alias(field): serialize(getattr(obj, field.name))
            for field in dataclasses.fields(obj)
            if field.init
        }
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): serialize(value) for key, value in obj.items()}
    return obj


def deserialize(cls: type[T], data: Any, path: str | None = None) -> T:
    """把 dict 还原成 dataclass 实例。

    - 未知键忽略（前向兼容，见 DECISIONS.md D-012）
    - 缺失键使用该字段的默认值
    - 类型或枚举取值非法 → :class:`IRDeserializeError`（错误信息带字段路径）
    """
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"deserialize 只接受 dataclass 类型，实际 {cls!r}")
    if not isinstance(data, dict):
        raise IRDeserializeError(f"{cls.__name__}: 期望 JSON 对象，实际 {type(data).__name__}")

    prefix = path or cls.__name__
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if not field.init:
            continue
        raw = data.get(_alias(field), data.get(field.name, _MISSING))
        if raw is _MISSING:
            continue
        kwargs[field.name] = _convert(hints[field.name], raw, f"{prefix}.{field.name}")
    return cls(**kwargs)


@cache
def _hints(cls: type) -> dict[str, Any]:
    """解析并缓存 dataclass 的类型标注（字符串注解 → 真实对象）。"""
    return typing.get_type_hints(cls)


def _alias(field: dataclasses.Field[Any]) -> str:
    """字段对应的 JSON 键名，默认就是字段名。"""
    alias = field.metadata.get(ALIAS_KEY)
    return alias if isinstance(alias, str) else field.name


def _is_union(hint: Any) -> bool:
    """是否为 `X | None` / `Optional[X]` / 更一般的联合类型。"""
    return typing.get_origin(hint) is typing.Union or isinstance(hint, types.UnionType)


def _allows_none(hint: Any) -> bool:
    """该标注是否接受 None。"""
    return _is_union(hint) and type(None) in typing.get_args(hint)


def _convert(hint: Any, raw: Any, path: str) -> Any:
    """按类型标注把 JSON 值转成 Python 值，失败时抛带路径的错误。"""
    if hint is Any or hint is None:
        return raw
    if raw is None:
        if _allows_none(hint):
            return None
        raise IRDeserializeError(f"{path}: 不允许 None")

    if _is_union(hint):
        candidates = [arg for arg in typing.get_args(hint) if arg is not type(None)]
        if len(candidates) == 1:
            return _convert(candidates[0], raw, path)
        for candidate in candidates:
            try:
                return _convert(candidate, raw, path)
            except IRDeserializeError:
                continue
        raise IRDeserializeError(f"{path}: 取值 {raw!r} 不匹配任一候选类型")

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is list:
        if not isinstance(raw, list):
            raise IRDeserializeError(f"{path}: 期望列表，实际 {type(raw).__name__}")
        item_hint = args[0] if args else Any
        return [_convert(item_hint, item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if origin is dict:
        if not isinstance(raw, dict):
            raise IRDeserializeError(f"{path}: 期望对象，实际 {type(raw).__name__}")
        value_hint = args[1] if len(args) > 1 else Any
        return {str(key): _convert(value_hint, value, f"{path}.{key}") for key, value in raw.items()}
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        return deserialize(hint, raw, path)
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        return _convert_enum(hint, raw, path)
    if hint is bool:
        if isinstance(raw, bool):
            return raw
        raise IRDeserializeError(f"{path}: 期望布尔，实际 {raw!r}")
    if hint is int:
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        raise IRDeserializeError(f"{path}: 期望整数，实际 {raw!r}")
    if hint is str:
        if isinstance(raw, str):
            return raw
        raise IRDeserializeError(f"{path}: 期望字符串，实际 {raw!r}")
    if hint is float:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        raise IRDeserializeError(f"{path}: 期望数值，实际 {raw!r}")
    return raw


def _convert_enum(enum_cls: type[enum.Enum], raw: Any, path: str) -> Any:
    """把 JSON 字符串转成枚举成员；已是成员则原样返回。"""
    try:
        return enum_cls(raw)
    except ValueError as exc:
        allowed = ", ".join(str(member.value) for member in enum_cls)
        raise IRDeserializeError(f"{path}: 非法取值 {raw!r}（允许：{allowed}）") from exc
