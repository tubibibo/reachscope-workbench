"""Budgeted cloud JSON normalization with explicit unknown and sensitive values."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from ...core.models import WorkbenchError

MAX_BYTES = 2 * 1024 * 1024
MAX_RESOURCES = 500
MAX_STATEMENTS = 1000
UNKNOWN = "[unknown at plan time]"
REDACTED = "[sensitive value omitted]"
_FIELDS = {
    "aws_security_group": ("ingress",),
    "aws_security_group_rule": ("type", "protocol", "from_port", "to_port", "cidr_blocks", "ipv6_cidr_blocks"),
    "aws_vpc_security_group_ingress_rule": ("ip_protocol", "from_port", "to_port", "cidr_ipv4", "cidr_ipv6"),
    "aws_iam_policy": ("policy",),
    "aws_iam_role_policy": ("policy",),
    "aws_iam_user_policy": ("policy",),
    "aws_iam_group_policy": ("policy",),
    "aws_iam_role": ("assume_role_policy",),
    "aws_s3_bucket_public_access_block": ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"),
    "aws_s3_bucket_policy": ("policy",),
    "aws_s3_bucket_server_side_encryption_configuration": ("rule",),
    "aws_s3_bucket": (),
}


@dataclass
class CloudResource:
    address: str
    type: str
    name: str
    pointer: str
    values: dict[str, Any]
    supported: bool


def _reject(message: str) -> None:
    raise WorkbenchError("INVALID_CLOUD_INPUT", message)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("JSON 包含重复字段，无法唯一解释策略或配置")
        result[key] = value
    return result


def _constant(_: str) -> None:
    _reject("JSON 不支持 NaN 或无穷值")


def _budget(value: Any) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 40000 or depth > 35:
            raise WorkbenchError("CLOUD_INPUT_LIMIT", "配置结构超过节点或嵌套深度上限")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError as exc:
                raise WorkbenchError("INVALID_CLOUD_INPUT", "云配置包含无法保存的 Unicode 字符") from exc


def decode_json(data: bytes | str) -> Any:
    if len(data if isinstance(data, bytes) else data.encode("utf-8")) > MAX_BYTES:
        raise WorkbenchError("CLOUD_INPUT_LIMIT", "云配置 JSON 不得超过 2 MiB")
    try:
        value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WorkbenchError("INVALID_CLOUD_INPUT", "云配置必须是有效且深度有限的 JSON") from exc
    _budget(value)
    return value


def _mask(value: Any, sensitive: Any = None, unknown: Any = None) -> Any:
    if sensitive is True:
        return REDACTED
    # Terraform markers should mirror value shape. A malformed nested marker is
    # not permission to reveal a scalar (or a mismatched collection) unmodified.
    if isinstance(sensitive, (dict, list)) and sensitive and not isinstance(value, type(sensitive)):
        return REDACTED
    if unknown is True:
        return UNKNOWN
    if isinstance(unknown, (dict, list)) and unknown and not isinstance(value, type(unknown)):
        return UNKNOWN
    if isinstance(value, dict):
        private = sensitive if isinstance(sensitive, dict) else {}
        pending = unknown if isinstance(unknown, dict) else {}
        keys = value.keys() | pending.keys() | private.keys()
        return {key: _mask(value.get(key), private.get(key), pending.get(key)) for key in keys}
    if isinstance(value, list):
        hidden = sensitive if isinstance(sensitive, list) else []
        unresolved = unknown if isinstance(unknown, list) else []
        return [_mask(value[index] if index < len(value) else None, hidden[index] if index < len(hidden) else None,
                      unresolved[index] if index < len(unresolved) else None)
                for index in range(max(len(value), len(hidden), len(unresolved)))]
    return value


def _strings(value: Any, limit: int = 1000) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 1024 else UNKNOWN
    if isinstance(value, list):
        if len(value) > limit:
            raise WorkbenchError("CLOUD_INPUT_LIMIT", "单项策略或规则列表超过检查预算")
        return [_strings(item) for item in value]
    if isinstance(value, dict):
        if any(len(str(key)) > 255 for key in value):
            raise WorkbenchError("CLOUD_INPUT_LIMIT", "策略字段名超过 255 字符")
        return {str(key): _strings(child) for key, child in value.items()}
    return value


def policy_projection(value: Any) -> Any:
    if value in (UNKNOWN, REDACTED):
        return value
    if isinstance(value, str):
        try:
            value = decode_json(value)
        except WorkbenchError:
            return {"parse_error": True}
    if not isinstance(value, dict):
        return {"parse_error": True}
    if "Statement" not in value:
        return {"parse_error": True}
    statements = value["Statement"]
    statements = statements if isinstance(statements, list) else [statements]
    if len(statements) > MAX_STATEMENTS:
        raise WorkbenchError("CLOUD_INPUT_LIMIT", "IAM/存储策略超过 1000 条语句")
    output = []
    for statement in statements:
        if not isinstance(statement, dict):
            output.append({"unsupported_statement": True})
            continue
        projected: dict[str, Any] = {}
        for key in ("Effect", "Action", "NotAction", "Resource", "NotResource", "Principal", "NotPrincipal"):
            if key not in statement:
                continue
            item = statement[key]
            if key in {"Principal", "NotPrincipal"} and isinstance(item, dict):
                projected[key] = {name: _strings(child) for name, child in item.items()
                                  if name in {"AWS", "Service", "Federated", "CanonicalUser"}}
                if not projected[key] or any(name not in {"AWS", "Service", "Federated", "CanonicalUser"} for name in item):
                    projected[key] = UNKNOWN
            elif isinstance(item, str) or isinstance(item, list) and all(isinstance(child, str) for child in item):
                projected[key] = _strings(item)
            else:
                projected[key] = UNKNOWN
        if "Condition" in statement:
            condition = statement["Condition"]
            if isinstance(condition, dict):
                if any(len(str(key)) > 255 for key in condition) or any(
                    isinstance(clauses, dict) and any(len(str(key)) > 255 for key in clauses) for clauses in condition.values()
                ):
                    raise WorkbenchError("CLOUD_INPUT_LIMIT", "Condition 字段名超过 255 字符")
                projected["Condition"] = {
                    str(operator)[:255]: {str(key)[:255]: "[condition value omitted]" for key in clauses}
                    if isinstance(clauses, dict) else "[condition value omitted]"
                    for operator, clauses in condition.items()
                }
            else:
                projected["Condition"] = UNKNOWN
        output.append(projected)
    version = value.get("Version")
    return {"Version": version if isinstance(version, str) and version in {"2008-10-17", "2012-10-17"} else "", "Statement": output}


def _project(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    result = {key: values[key] for key in _FIELDS.get(kind, ()) if key in values}
    if "policy" in result:
        result["policy"] = policy_projection(result["policy"])
    if "assume_role_policy" in result:
        result["assume_role_policy"] = policy_projection(result["assume_role_policy"])
    if kind == "aws_security_group" and isinstance(result.get("ingress"), list):
        if len(result["ingress"]) > 300:
            raise WorkbenchError("CLOUD_INPUT_LIMIT", "单个安全组入站规则超过 300 条")
        keys = ("protocol", "from_port", "to_port", "cidr_blocks", "ipv6_cidr_blocks", "security_groups", "self")
        result["ingress"] = [{key: rule[key] for key in keys if key in rule} if isinstance(rule, dict) else UNKNOWN
                             for rule in result["ingress"]]
    if kind == "aws_s3_bucket_server_side_encryption_configuration":
        rules = result.get("rule")
        if isinstance(rules, list):
            result["rule"] = [{"apply_server_side_encryption_by_default":
                               [{"sse_algorithm": item.get("sse_algorithm", UNKNOWN)} if isinstance(item, dict) else UNKNOWN
                                for item in rule.get("apply_server_side_encryption_by_default", [])]
                               if isinstance(rule.get("apply_server_side_encryption_by_default"), list) else UNKNOWN}
                              if isinstance(rule, dict) else UNKNOWN for rule in rules]
    return cast("dict[str, Any]", _strings(result))


def _sg_values(group: dict[str, Any]) -> dict[str, Any]:
    permissions = group.get("IpPermissions", UNKNOWN)
    if not isinstance(permissions, list):
        return {"ingress": UNKNOWN}
    rules: list[Any] = []
    for row in permissions:
        if not isinstance(row, dict):
            rules.append(UNKNOWN)
            continue
        def ranges(key: str, field: str, current: dict[str, Any]) -> list[Any] | str:
            entries = current.get(key, [])
            return [item.get(field, UNKNOWN) if isinstance(item, dict) else UNKNOWN for item in entries] if isinstance(entries, list) else UNKNOWN
        rules.append({"protocol": row.get("IpProtocol", UNKNOWN), "from_port": row.get("FromPort"), "to_port": row.get("ToPort"),
                      "cidr_blocks": ranges("IpRanges", "CidrIp", row), "ipv6_cidr_blocks": ranges("Ipv6Ranges", "CidrIpv6", row)})
    return {"ingress": rules}


def parse_input(data: bytes) -> tuple[list[CloudResource], str]:
    document = decode_json(data)
    if not isinstance(document, dict):
        _reject("云配置根节点必须是 JSON 对象")
    resources: list[CloudResource] = []

    def add(address: str, kind: str, name: str, pointer: str, values: dict[str, Any], sensitive: Any = None, unknown: Any = None) -> None:
        if len(resources) >= MAX_RESOURCES:
            raise WorkbenchError("CLOUD_INPUT_LIMIT", "云配置最多 500 项资源")
        masked = _mask(values, sensitive, unknown)
        resources.append(CloudResource(address[:512], kind[:120], name[:255], pointer,
                                       _project(kind, masked) if isinstance(masked, dict) else {"unknown": masked}, kind in _FIELDS))

    if isinstance(document.get("planned_values"), dict):
        version = document.get("format_version", "1.0")
        if not isinstance(version, str) or version.split(".")[0] != "1":
            _reject("不支持此 Terraform JSON format_version 主版本")
        changes = {}
        resource_changes = document.get("resource_changes", [])
        if not isinstance(resource_changes, list):
            _reject("Terraform resource_changes 必须为数组")
        for entry in resource_changes:
            if isinstance(entry, dict) and isinstance(entry.get("address"), str):
                # A repeated identity must not replace sensitivity/unknown
                # markers from an earlier declaration of the same change.
                if entry["address"] in changes:
                    _reject("Terraform resource_changes 存在重复资源地址，无法唯一绑定敏感与未知标记")
                changes[entry["address"]] = entry.get("change", {})

        def walk(module: Any, pointer: str, depth: int = 0) -> None:
            if not isinstance(module, dict) or depth > 20:
                _reject("Terraform 模块结构无效或嵌套过深")
            entries = module.get("resources", [])
            if not isinstance(entries, list):
                _reject("Terraform resources 必须为数组")
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict) or not isinstance(entry.get("type"), str) or not isinstance(entry.get("address"), str):
                    _reject("Terraform 资源必须包含 type 与 address")
                if entry.get("mode", "managed") == "data":
                    continue
                values = entry.get("values", {})
                if not isinstance(values, dict):
                    _reject("Terraform values 必须为对象")
                change = changes.get(entry["address"], {})
                change = change if isinstance(change, dict) else {}
                values = _mask(values, change.get("after_sensitive"))
                sensitive = entry.get("sensitive_values")
                add(entry["address"], entry["type"], str(entry.get("name", "")), f"{pointer}/resources/{index}/values",
                    values, sensitive, change.get("after_unknown"))
            children = module.get("child_modules", [])
            if not isinstance(children, list):
                _reject("Terraform child_modules 必须为数组")
            for index, child in enumerate(children):
                walk(child, f"{pointer}/child_modules/{index}", depth + 1)

        walk(document["planned_values"].get("root_module"), "/planned_values/root_module")
        kind = "terraform_plan"
    elif "Statement" in document:
        add("iam.policy", "aws_iam_policy", "Uploaded policy", "", {"policy": document})
        kind = "iam_policy"
    elif isinstance(document.get("SecurityGroups"), list):
        for index, group in enumerate(document["SecurityGroups"]):
            if not isinstance(group, dict):
                _reject("SecurityGroups 条目必须为对象")
            add(str(group.get("GroupId", f"security-group-{index}")), "aws_security_group", str(group.get("GroupName", "")),
                f"/SecurityGroups/{index}", _sg_values(group))
        kind = "security_groups_export"
    elif isinstance(document.get("PublicAccessBlockConfiguration"), dict):
        mapping = {"BlockPublicAcls": "block_public_acls", "BlockPublicPolicy": "block_public_policy",
                   "IgnorePublicAcls": "ignore_public_acls", "RestrictPublicBuckets": "restrict_public_buckets"}
        config = document["PublicAccessBlockConfiguration"]
        add("s3.public_access_block", "aws_s3_bucket_public_access_block", str(document.get("Bucket", "Uploaded bucket")),
            "/PublicAccessBlockConfiguration", {new: config.get(old, UNKNOWN) for old, new in mapping.items()})
        kind = "s3_public_access_block_export"
    else:
        _reject("支持 Terraform Plan JSON、IAM 策略、安全组或 S3 PublicAccessBlock 导出；无法识别此文件")
    if not resources:
        _reject("输入中没有可列出的受管资源或策略，不能生成有效审查结果")
    statements = sum(len(policy.get("Statement", [])) for resource in resources for name in ("policy", "assume_role_policy")
                     if isinstance(policy := resource.values.get(name), dict))
    if statements > MAX_STATEMENTS:
        raise WorkbenchError("CLOUD_INPUT_LIMIT", "所有策略合计超过 1000 条语句")
    return resources, kind
