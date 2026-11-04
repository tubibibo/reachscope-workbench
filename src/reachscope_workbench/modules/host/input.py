"""Bounded operator-supplied configuration exports; no host or file-system access."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from ...core.models import WorkbenchError
from .collection_metadata import COLLECTOR_SCHEMA, parse_collection

MAX_BYTES = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 256 * 1024
SCHEMA = "reachscope-host/1"
_RFC3339 = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z")


def _reject(message: str) -> None:
    raise WorkbenchError("INVALID_HOST_INPUT", message)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("配置资料含重复 JSON 字段，无法唯一解释。")
        result[key] = value
    return result


def _constant(_: str) -> None:
    _reject("配置资料不接受 NaN 或无穷数值。")


def validate_host_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or value != value.strip():
        _reject("请提供 1–128 字符且无首尾空白的稳定主机标识。")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _reject("主机标识不得包含控制字符。")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _reject("主机标识包含无效 Unicode 字符。")
    return str(value)


def _timestamp(value: Any) -> tuple[str | None, str]:
    if value is None:
        return None, "unknown"
    if not isinstance(value, str) or len(value) > 80 or not _RFC3339.fullmatch(value):
        return None, "unknown"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None, "unknown"
        return parsed.astimezone(UTC).isoformat(), "provided_not_verified"
    except (ValueError, OverflowError):
        return None, "unknown"


def parse_baseline(raw: bytes, host_id: str) -> dict[str, Any]:
    """Validate the snapshot, retaining raw exports only for in-process analysis."""
    expected = validate_host_id(host_id)
    if not raw or len(raw) > MAX_BYTES:
        raise WorkbenchError("HOST_INPUT_LIMIT", "主机配置 JSON 必须为非空且不超过 2 MiB。")
    try:
        text = raw.decode("utf-8-sig")
        value = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorkbenchError("INVALID_HOST_INPUT", "主机配置必须是有效 UTF-8 JSON。") from exc
    pending = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > 20_000 or depth > 30:
            raise WorkbenchError("HOST_INPUT_LIMIT", "主机配置 JSON 超过节点或嵌套上限。")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for pair in current.items() for child in pair)
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeError as exc:
                raise WorkbenchError("INVALID_HOST_INPUT", "主机配置包含无效 Unicode 字符。") from exc
    if (not isinstance(value, dict) or not isinstance(value.get("schema_version"), str)
            or value["schema_version"] not in {SCHEMA, COLLECTOR_SCHEMA}):
        _reject("请选择 reachscope-host/1 模板或 reachscope-host/2 采集器配置导出。")
    if validate_host_id(value.get("host_id")) != expected:
        raise WorkbenchError("HOST_ID_MISMATCH", "配置内主机标识与保存资产不一致；请核对对应主机资料。")
    collected, collection_state = _timestamp(value.get("collected_at"))
    result: dict[str, Any] = {"schema_version": value["schema_version"], "host_id": expected,
                              "collected_at": collected, "collection_state": collection_state,
                              "input_sha256": hashlib.sha256(raw).hexdigest(), "source_kind": "operator_supplied_export"}
    collection = parse_collection(value.get("collector")) if value["schema_version"] == COLLECTOR_SCHEMA else None
    if collection is not None:
        result["collection_metadata"] = collection
    for component, field in (("ssh", "effective_config"), ("nginx", "config_dump")):
        item = value.get(component)
        exported = item.get(field) if isinstance(item, dict) else None
        if isinstance(exported, str):
            if len(exported.encode("utf-8")) > MAX_CONFIG_BYTES:
                raise WorkbenchError("HOST_INPUT_LIMIT", "单项配置导出不得超过 256 KiB。")
            result[component] = {field: exported}
        else:
            result[component] = {field: None}
        if collection is not None and collection["components"][component]["complete"] is not True:
            # A producer cannot turn failed/partial capture into a pass by
            # attaching apparently safe configuration text to its error state.
            result[component][field] = None
    ssh = value.get("ssh")
    context = ssh.get("connection_context") if isinstance(ssh, dict) else None
    if context is not None and (not isinstance(context, str) or not context.strip() or len(context) > 128
                                or context != context.strip() or any(ord(char) < 32 or ord(char) == 127 for char in context)):
        _reject("SSH 连接上下文须为 1–128 个无控制字符且无首尾空格的字符。")
    result["ssh"]["connection_context"] = context
    return result


def preview_baseline(data: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    components = []
    for component, field in (("ssh", "effective_config"), ("nginx", "config_dump")):
        value = data.get(component)
        exported = value.get(field) if isinstance(value, dict) else None
        components.append({"id": component, "selected": component in selected,
                           "provided": isinstance(exported, str) and bool(exported.strip()),
                           "bytes": len(exported.encode("utf-8")) if isinstance(exported, str) else 0,
                           **({"connection_context": "provided_not_verified" if value.get("connection_context") else "unspecified"}
                              if component == "ssh" and isinstance(value, dict) else {})})
    return {"version": 1, "input_kind": "host_baseline", "host_id": data["host_id"],
            "sha256": data["input_sha256"], "collection_state": data["collection_state"],
            "components": components, "analysis_executed": False, "network_requests": False,
            **({"collection_metadata": data["collection_metadata"]} if "collection_metadata" in data else {}),
            "limitations": ["预览仅确认输入格式与配置资料存在，不执行规则，不证明真实主机状态。", "未返回配置正文；原上传文件仍保留在本机。"]}
