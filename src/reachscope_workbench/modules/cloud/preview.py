"""Read-only input coverage preview, separate from cloud security rule execution.

Only allowlisted field names, counts and source pointers leave this layer. Values,
resource addresses/names, policy contents and credentials are never returned.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from ...core.models import WorkbenchError
from .input import REDACTED, UNKNOWN, CloudResource, parse_input

GROUP_LABELS = {"network": "网络访问规则", "iam": "身份与权限", "storage": "存储配置"}
_TYPE_GROUP = {
    "aws_security_group": "network", "aws_security_group_rule": "network", "aws_vpc_security_group_ingress_rule": "network",
    "aws_iam_policy": "iam", "aws_iam_role_policy": "iam", "aws_iam_user_policy": "iam", "aws_iam_group_policy": "iam", "aws_iam_role": "iam",
    "aws_s3_bucket_public_access_block": "storage", "aws_s3_bucket_policy": "storage", "aws_s3_bucket_server_side_encryption_configuration": "storage", "aws_s3_bucket": "storage",
}
_STATES = ("known", "missing", "unknown", "redacted", "invalid")
_MISSING = object()
MAX_GAPS = 80


def _state(value: Any, expected: type | tuple[type, ...] | None = None) -> str:
    if value is _MISSING:
        return "missing"
    if value == REDACTED:
        return "redacted"
    if value == UNKNOWN or value is None:
        return "unknown"
    if isinstance(value, dict):
        if value.get("parse_error") or value.get("unsupported_statement"):
            return "invalid"
        nested = [_state(child) for child in value.values()]
    elif isinstance(value, list):
        nested = [_state(child) for child in value]
    else:
        nested = []
    for status in ("redacted", "unknown", "invalid"):
        if status in nested:
            return status
    boolean_allowed = expected is bool or isinstance(expected, tuple) and bool in expected
    if expected is not None and (not isinstance(value, expected) or type(value) is bool and not boolean_allowed):
        return "invalid"
    return "known"


def preview_input(data: bytes, selected: list[str]) -> dict[str, Any]:
    """Normalize once without calling RULES, probing, writing or creating evidence."""
    resources, input_kind = parse_input(data)
    if len({item.address for item in resources}) != len(resources):
        raise WorkbenchError("INVALID_CLOUD_INPUT", "资源地址重复，无法唯一绑定输入预览")
    gaps: list[dict[str, Any]] = []
    gap_count = 0
    groups: dict[str, dict[str, Any]] = {key: {"id": key, "label": GROUP_LABELS[key], "applicable_resources": 0,
                    **{f"{state}_fields": 0 for state in _STATES}}
              for key in selected}

    def add(resource: CloudResource, index: int, field: str, value: Any, expected: type | tuple[type, ...] | None = None, *, pointer: str | None = None) -> None:
        nonlocal gap_count
        group = _TYPE_GROUP[resource.type]
        status = _state(value, expected)
        groups[group][f"{status}_fields"] += 1
        if status != "known":
            gap_count += 1
            if len(gaps) < MAX_GAPS:
                gaps.append({"resource_id": f"resource:{index}", "resource_type": resource.type, "group": group,
                             "field": field, "pointer": resource.pointer if pointer is None else pointer, "state": status})

    for index, resource in enumerate(resources):
        group = _TYPE_GROUP.get(resource.type)
        if group not in groups:
            continue
        groups[group]["applicable_resources"] += 1
        values = resource.values
        if group == "network":
            if resource.type == "aws_security_group":
                rows = values.get("ingress", _MISSING)
                add(resource, index, "ingress", rows, list)
                if not isinstance(rows, list):
                    continue
                for row_index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    pointer = resource.pointer + (f"/IpPermissions/{row_index}" if input_kind == "security_groups_export" else f"/ingress/{row_index}")
                    _network_fields(resource, index, row, add, pointer)
            else:
                if resource.type == "aws_security_group_rule":
                    add(resource, index, "type", values.get("type", _MISSING), str)
                _network_fields(resource, index, values, add, resource.pointer)
        elif group == "iam" or resource.type == "aws_s3_bucket_policy":
            key = "assume_role_policy" if resource.type == "aws_iam_role" else "policy"
            policy = values.get(key, _MISSING)
            pointer = "" if input_kind == "iam_policy" else resource.pointer + "/" + key if key in values else resource.pointer
            add(resource, index, key, policy, dict, pointer=pointer)
            if isinstance(policy, dict) and isinstance(policy.get("Statement"), list):
                if not policy["Statement"]:
                    add(resource, index, "Statement", _MISSING, pointer=pointer)
                for statement in policy["Statement"]:
                    if not isinstance(statement, dict) or statement.get("unsupported_statement"):
                        continue
                    for field in ("Effect", "Action"):
                        alternative = "NotAction" if field == "Action" else field
                        add(resource, index, field, statement.get(field, statement.get(alternative, _MISSING)), str if field == "Effect" else (str, list), pointer=pointer)
                    field = "Principal" if resource.type in {"aws_iam_role", "aws_s3_bucket_policy"} else "Resource"
                    add(resource, index, field, statement.get(field, statement.get("Not" + field, _MISSING)), (str, list, dict), pointer=pointer)
        elif resource.type == "aws_s3_bucket_public_access_block":
            for key in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
                add(resource, index, key, values.get(key, _MISSING), bool)
        elif resource.type == "aws_s3_bucket_server_side_encryption_configuration":
            encryption = values.get("rule", _MISSING)
            add(resource, index, "rule", encryption, list)
            if isinstance(encryption, list):
                if not encryption:
                    add(resource, index, "rule_entries", _MISSING, pointer=resource.pointer + "/rule")
                for row_index, row in enumerate(encryption):
                    if not isinstance(row, dict):
                        continue
                    key = "apply_server_side_encryption_by_default"
                    defaults = row.get(key, _MISSING)
                    pointer = resource.pointer + f"/rule/{row_index}"
                    add(resource, index, key, defaults, list, pointer=pointer)
                    if isinstance(defaults, list):
                        if not defaults:
                            add(resource, index, "encryption_defaults", _MISSING, pointer=pointer + "/" + key)
                        for default_index, default in enumerate(defaults):
                            if isinstance(default, dict):
                                add(resource, index, "sse_algorithm", default.get("sse_algorithm", _MISSING), str,
                                    pointer=pointer + f"/{key}/{default_index}")
        else:
            add(resource, index, "related_configuration", _MISSING)
    kinds = Counter(resource.type if resource.type in _TYPE_GROUP else "unsupported_resource" for resource in resources)
    return {
        "version": 1, "input_kind": input_kind, "sha256": hashlib.sha256(data).hexdigest(),
        "resources_total": len(resources), "supported_resources": sum(resource.supported for resource in resources),
        "unsupported_resources": sum(not resource.supported for resource in resources),
        "resource_types": [{"type": kind, "count": count, "supported": kind in _TYPE_GROUP} for kind, count in sorted(kinds.items())],
        "selected_groups": selected, "group_coverage": list(groups.values()), "field_gaps": gaps,
        "field_gaps_total": gap_count, "truncated": gap_count > len(gaps),
        "analysis_executed": False, "network_requests": False,
        "limitations": ["这是本地输入格式与字段覆盖预览，尚未执行安全规则或建立任务证据。", "资源类型支持与字段存在不代表安全；unknown、脱敏、缺失或不支持项需补充上下文。", "只显示允许的字段名、数量和来源指针，不返回配置值、资源名称、地址或策略内容。", "字段缺口指针定位到已提供的父对象；缺失字段本身或字符串形式策略的内部字段不能伪装成原文件中存在的 JSON 路径。"],
    }


def _network_fields(resource: CloudResource, index: int, values: dict[str, Any], add: Any, pointer: str) -> None:
    protocol = "ip_protocol" if resource.type == "aws_vpc_security_group_ingress_rule" else "protocol"
    value = values.get(protocol, _MISSING)
    add(resource, index, protocol, value, (str, int), pointer=pointer)
    if str(value).lower() in {"tcp", "6", "udp", "17"}:
        for key in ("from_port", "to_port"):
            add(resource, index, key, values.get(key, _MISSING), int, pointer=pointer)
    source_fields = ("cidr_ipv4", "cidr_ipv6") if resource.type == "aws_vpc_security_group_ingress_rule" else ("cidr_blocks", "ipv6_cidr_blocks", "security_groups", "self")
    present = [field for field in source_fields if field in values]
    if not present:
        add(resource, index, "source_ranges", _MISSING, pointer=pointer)
    for key in present:
        expected = str if key in {"cidr_ipv4", "cidr_ipv6"} else bool if key == "self" else list
        add(resource, index, key, values[key], expected, pointer=pointer)
