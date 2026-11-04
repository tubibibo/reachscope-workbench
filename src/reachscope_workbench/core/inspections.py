"""Application use cases for saved inputs, preflight and asset inspections.

This layer has no HTTP or module-implementation imports. Modules own validation;
the use case owns input binding and local readiness. Preflight never probes targets.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .assets import AssetRepository
from .catalog import profile_by_id
from .models import LocalInputPreview, WorkbenchError
from .registry import ModuleRegistry

_INPUT_FIELDS = {"profile_id", "mode", "upload_id", "filename", "targets", "sample", "apktool",
                 "allow_private", "timeout", "concurrency", "host_id"}


class InspectionService:
    def __init__(self, inventory: AssetRepository, modules: ModuleRegistry, uploads: Path) -> None:
        self.inventory, self.modules, self.uploads = inventory, modules, uploads

    def prepare_asset(self, kind: str, name: str, source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        name = name.strip()
        if not name or len(name) > 120:
            raise WorkbenchError("INVALID_ASSET", "资产名称须为 1–120 个字符")
        profile_id = source.get("profile_id")
        if not isinstance(profile_id, str):
            raise WorkbenchError("INVALID_ASSET", "请选择资产输入方式")
        profile = profile_by_id(profile_id)
        if profile["asset_kind"] != kind or source.get("mode", profile["mode"]) != profile["mode"]:
            raise WorkbenchError("ASSET_MISMATCH", "资产类别与输入方式不一致")
        if source.keys() - _INPUT_FIELDS:
            raise WorkbenchError("INVALID_ASSET", "资产包含不支持的输入字段")
        fields = set(profile["source_fields"])
        for key in source.keys() - fields:
            value = source[key]
            if value is not None and value is not False and value != "" and value != [] and value != {}:
                raise WorkbenchError("ASSET_MISMATCH", "输入字段与所选入口不一致；请只提供该入口的网址、文件或合成样例")
        configuration = {key: value for key, value in source.items() if key in fields and key != "profile_id"}
        configuration["mode"] = profile["mode"]
        upload_id = configuration.get("upload_id")
        if upload_id:
            if not isinstance(upload_id, str):
                raise WorkbenchError("INVALID_ID", "上传文件标识无效")
            upload = self.inventory.jobs.get_upload(upload_id)
            if configuration.get("filename", upload["filename"]) != upload["filename"]:
                raise WorkbenchError("ASSET_MISMATCH", "文件名称与上传记录不一致")
            configuration["filename"] = upload["filename"]
            if profile["input"] == "apk" and not upload["filename"].lower().endswith(".apk"):
                raise WorkbenchError("UPLOAD_TYPE", "这个入口需要 APK 文件")
            if profile["input"] != "apk" and upload["size"] > 2 * 1024 * 1024:
                raise WorkbenchError("UPLOAD_LIMIT", "配置或资产导入文件不得超过 2 MiB")
        normalized = self.modules.get(profile["module"]).validate(configuration)
        normalized.pop("checks", None)
        normalized["profile_id"] = profile_id
        return name, normalized

    def prepare_inspection(
        self, asset_id: str, checks: list[str], options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        asset = self.inventory.get(asset_id)
        profile = profile_by_id(asset["source"]["profile_id"])
        options = options or {}
        if options.keys() - {"timeout", "concurrency"}:
            raise WorkbenchError("INVALID_CONFIG", "仅支持调整本次超时与并发参数")
        if options and profile["mode"] != "probe":
            raise WorkbenchError("INVALID_CONFIG", "这些运行参数仅适用于 URL 观察任务")
        source = {key: value for key, value in asset["source"].items() if key != "profile_id"}
        config = self.modules.get(profile["module"]).validate({**source, **options, "checks": checks})
        return asset, profile, config

    def preflight(self, asset_id: str, checks: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
        _asset, profile, config = self.prepare_inspection(asset_id, checks, options)
        items: list[dict[str, str]] = []

        def add(identifier: str, label: str, status: str, message: str) -> None:
            items.append({"id": identifier, "label": label, "status": status, "message": message})

        add("selection", "检查范围", "ready", "检查选项有效；必要依赖已补齐。")
        if config.get("upload_id"):
            self._file_readiness(config["upload_id"], add)
        else:
            add("input", "输入资料", "ready", "使用保存的地址或内置合成样例。")
        if config["mode"] == "apk":
            add("java", "Java 环境", "ready" if shutil.which("java") else "blocked",
                "已找到 Java。" if shutil.which("java") else "未找到 Java，请安装后重新预检。")
            jar = config.get("apktool") or os.environ.get("APKTOOL_JAR")
            if jar:
                try:
                    available = Path(jar).is_file() and Path(jar).suffix.lower() == ".jar"
                except (OSError, ValueError):
                    available = False
            else:
                available = shutil.which("apktool") is not None
            add("decoder", "APK 解码器", "ready" if available else "blocked",
                "本机解码器可用；实际解码兼容性将在任务中验证。" if available else "未找到配置的 Apktool；请配置有效 JAR 或本机命令。")
        if profile["network"]:
            add("network", "网络范围", "warning", "执行时仅请求保存的精确 HTTP(S) 地址；DNS、范围和连接结果将在任务中验证。")
        if profile["module"] == "cloud":
            add("cloud_scope", "云配置范围", "warning", "只解析本地静态文件，不连接云账号；安全规则与实际部署验证仍未执行。")
        input_preview: dict[str, Any] | None = None
        module = self.modules.get(profile["module"])
        if isinstance(module, LocalInputPreview) and not any(item["status"] == "blocked" for item in items):
            try:
                input_preview = module.preview(config, self.uploads)
                if config.get("upload_id") and input_preview.get("sha256") != self.inventory.jobs.get_upload(config["upload_id"])["sha256"]:
                    input_preview = None
                    add("input_preview", "输入格式与覆盖预览", "blocked", "文件在预检读取中发生变化，请重新上传原始文件。")
                else:
                    add("input_preview", "输入格式与覆盖预览", "ready", "已识别输入格式与资源；字段缺口将在预览中列明，尚未执行安全规则。")
            except WorkbenchError as exc:
                input_preview = None
                add("input_preview", "输入格式与覆盖预览", "blocked", f"{exc.message}。请提供支持格式的完整 JSON 后重新上传。")
            except OSError:
                input_preview = None
                add("input_preview", "输入格式与覆盖预览", "blocked", "无法读取输入预览，请检查本机权限或重新上传文件。")
        labels = {check["id"]: check["label"] for check in profile["checks"]}
        limits = {"max_targets": 20, "timeout": config.get("timeout"), "concurrency": config.get("concurrency")} if profile["network"] else {
            "upload_bytes": 256 * 1024 * 1024 if config["mode"] == "apk" else 2 * 1024 * 1024,
        }
        return {
            "ready": not any(item["status"] == "blocked" for item in items), "asset_id": asset_id,
            "module": profile["module"], "checks": config["checks"], "network": profile["network"], "items": items,
            "scope": {"profile_id": profile["id"], "label": profile["label"], "limits": limits,
                      "selected_checks": [{"id": identifier, "label": labels[identifier]} for identifier in config["checks"]]},
            "limitations": ["预检只确认当前输入与本机前置条件，不保证后续分析、网络连接或所有检查均能成功。",
                            "执行前后文件或环境可能变化；任务仍会进行自己的输入与范围校验。"],
            **({"input_preview": input_preview} if input_preview is not None else {}),
        }

    def _file_readiness(self, upload_id: str, add: Callable[[str, str, str, str], None]) -> None:
        metadata = self.inventory.jobs.get_upload(upload_id)
        path = self.uploads / upload_id
        try:
            if path.is_symlink() or path.resolve().parent != self.uploads.resolve() or not path.is_file():
                add("upload", "保存的输入文件", "blocked", "输入文件已丢失或路径异常，请重新选择文件另建资产。")
                return
            if path.stat().st_size != metadata["size"]:
                add("upload", "保存的输入文件", "blocked", "文件大小与上传记录不一致，请重新选择原始文件。")
                return
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                remaining = metadata["size"]
                while chunk := handle.read(min(1024 * 1024, remaining + 1)):
                    if len(chunk) > remaining:
                        add("upload", "保存的输入文件", "blocked", "文件在读取中发生变化，请重新选择原始文件。")
                        return
                    digest.update(chunk)
                    remaining -= len(chunk)
            if digest.hexdigest() != metadata["sha256"]:
                add("upload", "保存的输入文件", "blocked", "文件摘要与上传记录不一致，请重新选择原始文件。")
            else:
                add("upload", "保存的输入文件", "ready", "文件存在、可读取且摘要与上传记录一致。")
        except OSError:
            add("upload", "保存的输入文件", "blocked", "无法读取已保存输入，请检查本机文件权限或重新上传。")
