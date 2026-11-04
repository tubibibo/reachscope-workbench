"""Cloud module: bounded offline input, explicit rule selection and saved evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ...core.models import (
    Evidence,
    ModuleResult,
    ModuleSpec,
    Observation,
    RunContext,
    WorkbenchError,
)
from .guidance import implementation_guide
from .input import MAX_BYTES, REDACTED, UNKNOWN, parse_input
from .preview import preview_input
from .rules import GROUPS, RULES
from .sample import demo_document

_UPLOAD_ID = re.compile(r"[a-f0-9]{32}\Z")
_LIMITATIONS = [
    "本模块只检查上传的静态 AWS 配置，不连接云账号，不验证部署实况或漏洞可利用性。",
    "安全组规则允许来源不等于公网可达；路由、公网地址、监听服务和其他关联规则未完整评估。",
    "IAM 规则不是有效权限求值器；Condition、显式 Deny、权限边界、会话策略和组织策略需结合上下文复核。",
    "S3 桶级保护与策略不代表完整访问状态；账号/组织/访问点保护可能进一步限制，缺少加密声明不等于未加密。",
    "只检查明确支持的资源类型和有限规则；未知值、脱敏值、未提供的关联资源与不支持类型保留为覆盖缺口。",
    "结果证据仅保留相关字段白名单并脱敏，但上传原文件仍按工作台的本地文件保存策略保存在本机。",
]


def _identity(kind: str, value: str) -> str:
    return kind + "-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _read(path: Path) -> bytes:
    try:
        with path.open("rb") as file:
            data = file.read(MAX_BYTES + 1)
    except OSError as exc:
        raise WorkbenchError("UPLOAD_NOT_FOUND", "云配置上传文件不可读取") from exc
    if len(data) > MAX_BYTES:
        raise WorkbenchError("CLOUD_INPUT_LIMIT", "云配置 JSON 不得超过 2 MiB")
    return data


class CloudModule:
    spec = ModuleSpec(id="cloud", name="云配置与权限", description="离线 AWS 配置、IAM 与存储审查，保留字段证据和未知值",
                      capabilities=["cloud_inventory", "network_rules", "iam_policy_review", "storage_configuration", "field_evidence", "selective_checks"],
                      input_modes=["demo", "import"], version="1.0")

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = config.get("mode", "demo")
        if mode not in self.spec.input_modes:
            raise WorkbenchError("INVALID_CONFIG", "云配置模式必须为 demo 或 import")
        checks = config.get("checks", list(GROUPS))
        if not isinstance(checks, list) or not 1 <= len(checks) <= 10 or any(not isinstance(check, str) or check not in GROUPS for check in checks):
            raise WorkbenchError("INVALID_CONFIG", "请选择 network、iam、storage 中至少一个检查项目")
        normalized: dict[str, Any] = {"mode": mode, "checks": list(dict.fromkeys(checks))}
        if mode == "import":
            upload_id, filename = config.get("upload_id"), config.get("filename")
            if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
                raise WorkbenchError("INVALID_CONFIG", "云配置检查需要有效的上传文件 ID")
            if not isinstance(filename, str) or len(filename) > 255 or Path(filename).suffix.lower() != ".json":
                raise WorkbenchError("INVALID_CONFIG", "云配置文件必须为 .json")
            normalized.update(upload_id=upload_id, filename=Path(filename.replace("\\", "/")).name)
        return normalized

    def preview(self, config: dict[str, Any], uploads: Path) -> dict[str, Any]:
        """Pure local coverage preparation, before any job/rule/evidence creation."""
        clean = self.validate(config)
        if clean["mode"] == "demo":
            data = json.dumps(demo_document()).encode("utf-8")
        else:
            path = uploads / clean["upload_id"]
            if path.is_symlink() or not path.is_file() or path.resolve().parent != uploads.resolve():
                raise WorkbenchError("UPLOAD_NOT_FOUND", "云配置输入不可读取，请重新上传原始 JSON。")
            data = _read(path)
        return preview_input(data, clean["checks"])

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        clean = self.validate(config)
        context.progress(5, "准备本地云配置，不连接云账号")
        if clean["mode"] == "demo":
            data = json.dumps(demo_document()).encode()
            target = "AWS 配置合成样例 / 未连接云环境"
        else:
            path = context.uploads / clean["upload_id"]
            if path.is_symlink() or not path.is_file() or path.resolve().parent != context.uploads.resolve():
                raise WorkbenchError("UPLOAD_NOT_FOUND", "云配置上传文件不存在或路径无效")
            data = await asyncio.to_thread(_read, path)
            target = clean["filename"]
        context.progress(25, "解析资源与字段，保留敏感标记和计划未知值")
        result = await asyncio.to_thread(self._analyze, data, clean, target)
        context.progress(100, "云配置审查完成，可以回查字段证据")
        return result

    @staticmethod
    def _analyze(data: bytes, config: dict[str, Any], target: str) -> ModuleResult:
        resources, input_kind = parse_input(data)
        inventory, checks, evidence, observations, execution = [], [], [], [], []
        group_counts = dict.fromkeys(GROUPS, 0)
        seen = set()
        for resource in resources:
            if resource.address in seen:
                raise WorkbenchError("INVALID_CLOUD_INPUT", "资源地址重复，无法唯一绑定证据")
            seen.add(resource.address)
            eid = _identity("cloud", resource.address + resource.pointer)
            evidence.append(Evidence(id=eid, kind="cloud_static_configuration", title=resource.address,
                                     source=target + "#" + resource.pointer,
                                     data={"resource_type": resource.type, "address": resource.address, "pointer": resource.pointer,
                                           "values": resource.values, "source_kind": input_kind, "deployed_state_verified": False},
                                     sha256=hashlib.sha256(data).hexdigest()))
            inventory.append({"id": resource.address, "address": resource.address, "type": resource.type,
                              "name": resource.name, "provider": "aws" if resource.type.startswith("aws_") else "unknown",
                              "source_pointer": resource.pointer, "supported": resource.supported, "evidence_ids": [eid]})
            for group in config["checks"]:
                for check in RULES[group](resource):
                    group_counts[group] += 1
                    check["evidence_ids"] = [eid]
                    guide = implementation_guide(check)
                    if guide is not None:
                        check["guidance"] = guide
                    checks.append(check)
                    if check["status"] in {"review", "unknown"}:
                        observations.append(Observation(
                            id=_identity("cloud-check", resource.address + check["id"]), title=check["title"],
                            severity=check["severity"], category=group, description=check["description"],
                            evidence_ids=[eid], confidence="static_config", recommendation=check["recommendation"],
                        ))
        for group, label in GROUPS.items():
            count = group_counts[group]
            execution.append({"id": group, "label": label, "status": "completed" if group in config["checks"] else "skipped",
                              "reason": f"执行所选规则，产生 {count} 条检查；无匹配资源时不作安全结论。" if group in config["checks"] else "本次未选择，未执行该组规则。",
                              "checks": count})
        unsupported = sum(not resource.supported for resource in resources)
        return ModuleResult(module="cloud", target=target,
                            summary={"resources": len(inventory), "checks": len(checks),
                                     "review_checks": sum(check["status"] == "review" for check in checks),
                                     "unknown_checks": sum(check["status"] == "unknown" for check in checks),
                                     "unsupported_resources": unsupported},
                            evidence=evidence, observations=observations,
                            details={"resources": inventory, "checks": checks, "execution": execution,
                                     "input_kind": input_kind, "redaction": {"sensitive_marker": REDACTED, "unknown_marker": UNKNOWN,
                                         "evidence_fields": "allowlisted", "condition_values": "omitted", "original_upload_retained_locally": True},
                                     "deployed_state_verified": False},
                            limitations=[*_LIMITATIONS, *([f"{unsupported} 个资源类型仅列入清单，未执行专用安全规则。"] if unsupported else [])])
