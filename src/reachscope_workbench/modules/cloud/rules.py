"""Small evidence-backed rules, deliberately short of effective-permission evaluation."""

from __future__ import annotations

import ipaddress
from typing import Any

from .input import REDACTED, UNKNOWN, CloudResource

GROUPS = {"network": "网络访问规则", "iam": "身份与权限", "storage": "存储配置"}
SENSITIVE_PORTS = {22: "SSH", 23: "Telnet", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 9200: "Elasticsearch", 27017: "MongoDB"}


def _check(resource: CloudResource, rule: str, title: str, status: str, description: str,
           recommendation: str, values: Any, suffix: str = "") -> dict[str, Any]:
    return {"id": rule, "resource_id": resource.address, "title": title, "status": status,
            "severity": "medium" if status == "review" else "info", "description": description,
            "recommendation": recommendation, "evidence_ids": [],
            "evidence": {"pointer": resource.pointer + suffix, "values": values}}


def _unknown(value: Any) -> bool:
    if value is None or value in (UNKNOWN, REDACTED):
        return True
    if isinstance(value, dict):
        return any(_unknown(child) for child in value.values())
    if isinstance(value, list):
        return any(_unknown(child) for child in value)
    return False


def network(resource: CloudResource) -> list[dict[str, Any]]:
    if resource.type not in {"aws_security_group", "aws_security_group_rule", "aws_vpc_security_group_ingress_rule"}:
        return []
    if resource.type == "aws_security_group_rule" and resource.values.get("type") != "ingress":
        return [_check(resource, "network.public_sensitive_ports", "入站敏感端口规则", "not_applicable" if resource.values.get("type") == "egress" else "unknown",
                       "该独立规则未明确声明为 ingress，不将其作为入站暴露规则。", "如需检查入站规则，请提供其方向和完整配置。", resource.values)]
    rules = resource.values.get("ingress") if resource.type == "aws_security_group" else [resource.values]
    if not isinstance(rules, list):
        return [_check(resource, "network.public_sensitive_ports", "入站敏感端口规则", "unknown",
                       "入站规则未知、被脱敏或缺少，无法评估。", "提供已解析的入站规则；计划阶段未知值需在部署后另行核对。", {"ingress": rules})]
    affected, unresolved = [], []
    for index, row in enumerate(rules):
        if not isinstance(row, dict):
            unresolved.append(index)
            continue
        protocol = row.get("protocol", row.get("ip_protocol"))
        cidrs = row.get("cidr_blocks", [])
        ipv6 = row.get("ipv6_cidr_blocks", [])
        if "cidr_ipv4" in row:
            cidrs = [row["cidr_ipv4"]]
        if "cidr_ipv6" in row:
            ipv6 = [row["cidr_ipv6"]]
        if not isinstance(cidrs, list) or not isinstance(ipv6, list) or _unknown(protocol):
            unresolved.append(index)
            continue
        public = []
        bad_cidr = False
        for cidr in [*cidrs, *ipv6]:
            try:
                if not isinstance(cidr, str):
                    raise TypeError("CIDR must be text")
                parsed = ipaddress.ip_network(cidr, strict=False)
                if parsed.prefixlen == 0:
                    public.append(cidr)
            except (ValueError, TypeError):
                bad_cidr = True
        if bad_cidr:
            unresolved.append(index)
        if not public:
            continue
        if str(protocol) in {"-1", "all"}:
            ports = list(SENSITIVE_PORTS)
        elif str(protocol).lower() in {"tcp", "6"}:
            first, last = row.get("from_port"), row.get("to_port")
            if type(first) is not int or type(last) is not int or not 0 <= first <= last <= 65535:
                unresolved.append(index)
                continue
            ports = [port for port in SENSITIVE_PORTS if first <= port <= last]
        elif str(protocol).lower() in {"udp", "17", "icmp", "1", "icmpv6", "58"}:
            continue
        else:
            unresolved.append(index)
            continue
        if ports:
            affected.append({"rule_index": index, "source_cidrs": public, "protocol": protocol,
                             "sensitive_ports": ports, "services": [SENSITIVE_PORTS[port] for port in ports]})
    status = "review" if affected else "unknown" if unresolved else "pass"
    description = ("入站规则允许任意来源访问列出的 TCP 管理/数据服务端口；未检查路由、公网地址、其他安全组或实际监听。" if affected
                   else "部分规则字段未知或无法解析，无法完整判断敏感端口允许范围。" if unresolved
                   else "已提供规则未命中任意来源的所列 TCP 敏感端口条件；不代表主机无其他暴露面。")
    return [_check(resource, "network.public_sensitive_ports", "入站敏感端口规则", status, description,
                   "按业务缩小来源 CIDR 与端口范围，并结合部署路由、主机监听和关联规则复核。",
                   {"affected": affected, "unknown_rule_indexes": unresolved, "ports_considered": SENSITIVE_PORTS})]


def _list(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _wildcard_action(value: Any) -> bool:
    return any(action == "*" or ":" in action and action.split(":", 1)[1] == "*" for action in _list(value))


def _wildcard_principal(value: Any) -> bool:
    return value == "*" or isinstance(value, dict) and any("*" in _list(item) for item in value.values())


def _policy(resource: CloudResource, *, trust: bool = False, bucket: bool = False) -> list[dict[str, Any]]:
    field = "assume_role_policy" if trust else "policy"
    policy = resource.values.get(field)
    rule = "iam.trust_principal" if trust else "storage.bucket_policy_principal" if bucket else "iam.broad_allow"
    title = "角色信任主体范围" if trust else "存储策略主体范围" if bucket else "IAM Allow 权限范围"
    advice = "核对主体、动作、资源和 Condition，并结合显式拒绝、权限边界、会话策略与组织策略评估有效权限。"
    # A standalone policy is the document root. The normalized "policy" wrapper
    # is internal; do not invent a /policy location absent from the uploaded JSON.
    pointer_suffix = "/" + field if resource.pointer else ""
    if not isinstance(policy, dict) or policy.get("parse_error") or not isinstance(policy.get("Statement"), list) or not policy["Statement"]:
        return [_check(resource, rule, title, "unknown", "策略缺失、未知、被脱敏或无法解析，未作权限结论。", advice,
                       {field: policy}, pointer_suffix)]
    affected, unresolved, deny, conditioned = [], [], 0, 0
    for index, statement in enumerate(policy["Statement"]):
        if not isinstance(statement, dict) or not statement or statement.get("unsupported_statement"):
            unresolved.append(index)
            continue
        effect = statement.get("Effect")
        if effect == "Deny":
            deny += 1
            continue
        if effect != "Allow" or "NotAction" in statement or "NotResource" in statement or "NotPrincipal" in statement:
            unresolved.append(index)
            continue
        condition = statement.get("Condition")
        if "Condition" in statement:
            conditioned += 1
        if trust or bucket:
            if "Principal" not in statement or "Action" not in statement or _unknown(statement.get("Principal")) or _unknown(statement.get("Action")):
                unresolved.append(index)
                continue
            broad = _wildcard_principal(statement["Principal"])
        else:
            if "Action" not in statement or "Resource" not in statement or _unknown(statement["Action"]) or _unknown(statement["Resource"]):
                unresolved.append(index)
                continue
            broad = _wildcard_action(statement["Action"]) and "*" in _list(statement["Resource"])
        if broad:
            affected.append({"statement_index": index, "condition_present": "Condition" in statement,
                             "condition_keys": sorted(condition) if isinstance(condition, dict) else [],
                             "context_required": True, "statement": statement})
    status = "review" if affected else "unknown" if unresolved else "info"
    description = ("观察到宽泛 Allow 主体或动作/资源；Condition、Deny 与外部策略可能进一步限制，未求值有效权限或公开可访问性。" if affected
                   else "策略使用未支持或未知的表达式；当前规则无法完整评估。" if unresolved
                   else "已解析语句未命中本项宽泛 Allow 条件；未计算完整有效权限，不能据此认定最小权限。")
    return [_check(resource, rule, title, status, description, advice,
                   {"affected": affected, "unknown_statement_indexes": unresolved,
                    "deny_statements_not_evaluated": deny, "conditioned_statements": conditioned,
                    "effective_permissions_evaluated": False}, pointer_suffix)]


def iam(resource: CloudResource) -> list[dict[str, Any]]:
    if resource.type in {"aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"}:
        return _policy(resource)
    if resource.type == "aws_iam_role":
        return _policy(resource, trust=True)
    return []


def storage(resource: CloudResource) -> list[dict[str, Any]]:
    if resource.type == "aws_s3_bucket_public_access_block":
        flags = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")
        known = {key: resource.values.get(key, UNKNOWN) for key in flags}
        disabled = [key for key, value in known.items() if value is False]
        missing = [key for key, value in known.items() if type(value) is not bool]
        status = "review" if disabled else "unknown" if missing else "pass"
        description = ("部分桶级公共访问保护关闭；这不等于存储桶已公开，还需结合账号级保护、ACL 与策略。" if disabled
                       else "公共访问保护字段未知、被脱敏或缺失；不能判断全部保护状态。" if missing
                       else "四项已提供的桶级公共访问保护均为 true；不代表完整访问策略已经验证。")
        return [_check(resource, "storage.public_access_block", "S3 公共访问保护配置", status, description,
                       "按业务开启四项保护，并核对账号级保护、访问点与桶策略的组合效果。", {"configuration": known, "disabled": disabled, "unknown": missing})]
    if resource.type == "aws_s3_bucket_policy":
        return _policy(resource, bucket=True)
    if resource.type == "aws_s3_bucket_server_side_encryption_configuration":
        rules = resource.values.get("rule")
        algorithms: list[Any] = []
        if isinstance(rules, list):
            for row in rules:
                defaults = row.get("apply_server_side_encryption_by_default") if isinstance(row, dict) else None
                if isinstance(defaults, list):
                    algorithms.extend(item.get("sse_algorithm") for item in defaults if isinstance(item, dict))
        known_algorithm = bool(algorithms) and all(isinstance(value, str) and value in {"AES256", "aws:kms", "aws:kms:dsse"} for value in algorithms)
        return [_check(resource, "storage.encryption_declaration", "S3 加密配置声明", "info" if known_algorithm else "unknown",
                       "观察到支持的服务端加密声明；未检查 KMS 密钥状态、密钥策略或对象实际状态。" if known_algorithm
                       else "未解析到支持的明确加密声明；S3 存在默认加密，不能由缺少声明推断数据未加密。",
                       "结合数据要求核对算法、KMS 策略和部署状态。", {"algorithms": algorithms})]
    if resource.type == "aws_s3_bucket":
        return [_check(resource, "storage.bucket_context", "S3 配置覆盖范围", "unknown",
                       "仅提供存储桶资源本体，缺少独立的公共访问保护、策略和加密资源，不能评估其组合配置。",
                       "补充关联资源或 AWS 配置导出；未提供配置不等于云端没有保护。", {})]
    return []


RULES = {"network": network, "iam": iam, "storage": storage}
