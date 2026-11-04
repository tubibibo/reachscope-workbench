"""User-facing asset/check catalogue, independent of analysis implementations."""

from __future__ import annotations

import copy
from typing import Any

from .models import WorkbenchError


def _check(identifier: str, label: str, description: str, *, required: bool = False,
           dependencies: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"id": identifier, "label": label, "description": description,
            "required": required, "depends_on": list(dependencies), "recommended": True}


_ANDROID = [
    _check("manifest", "清单配置、组件与深链", "复核调试、备份、网络安全、权限和入口声明；保留未知资源，不执行应用。", required=True),
    _check("code_paths", "WebView 与候选代码路径", "索引方法源码并分析静态候选路径。", dependencies=("manifest",)),
]
_WEB = [
    _check("http", "响应与服务信息", "向指定 HTTP(S) 地址发送有限 GET 请求，记录状态和跳转。", required=True),
    _check("headers", "响应头、Cookie 与证书", "复核已取得响应的配置条件，Cookie 不保存值。", dependencies=("http",)),
    _check("page", "页面表单与资源", "解析采集到的 HTML，不执行脚本、加载资源或提交表单。", dependencies=("http",)),
    _check("fingerprints", "技术线索与调查建议", "使用有限规则分类资产并给出待验证的调查路径。", dependencies=("http",)),
]
_INVENTORY = [_check("fingerprints", "资产分类与调查建议", "只分析输入记录，不联系目标地址。", required=True)]
_CLOUD = [
    _check("network", "网络访问规则", "检查文件中支持的安全组规则；不等同实际公网连通性。"),
    _check("iam", "身份与权限策略", "复核支持的 IAM 策略和信任关系；不计算完整有效权限。"),
    _check("storage", "对象存储配置", "复核文件中的公开访问保护等受支持配置。"),
]
_HOST_BASELINE = [
    _check("ssh", "SSH 配置基线", "复核提供的 sshd -T 配置导出；不连接或修改主机。"),
    _check("nginx", "Nginx 配置基线", "复核提供的配置文本及上下文；缺失 Include 或未知默认值保留为信息不足。"),
]
_HOST_ACCESS = [_check("web_logs", "Web 访问日志线索", "离线查看有限时间窗口中的状态码线索；不确认入侵或自动封禁。", required=True)]
_HOST_AUTH = [_check("auth_logs", "SSH 认证日志线索", "离线复核认证失败事件；缺少时区或年份不会补造时间。", required=True)]


def _profile(identifier: str, module: str, kind: str, mode: str, label: str,
             description: str, input_type: str, checks: list[dict[str, Any]], *, network: bool = False) -> dict[str, Any]:
    fields = {"profile_id", "mode"}
    if input_type == "urls":
        fields.update(("targets", "allow_private", "timeout", "concurrency"))
    elif input_type == "apk":
        fields.update(("upload_id", "filename", "apktool", "timeout"))
    elif input_type == "json":
        fields.update(("upload_id", "filename"))
    elif module == "android":
        fields.update(("sample", "timeout"))
    if module == "host":
        fields.add("host_id")
    return {"id": identifier, "module": module, "asset_kind": kind, "mode": mode,
            "label": label, "description": description, "input": input_type,
            "network": network, "checks": checks, "source_fields": sorted(fields)}


_PROFILES = [
    _profile("android-apk", "android", "android", "apk", "选择 APK 文件", "检查本机 APK 文件，应用不会被安装或执行。", "apk", _ANDROID),
    _profile("android-demo", "android", "android", "demo", "体验应用样例", "从内置源码样例开始，无需准备 APK。", "demo", _ANDROID),
    _profile("website-probe", "web", "website", "probe", "网站地址", "检查提供的精确 HTTP(S) URL。", "urls", _WEB, network=True),
    _profile("website-import", "web", "website", "import", "导入网站记录", "读取 HTTP(S) 网站 JSON、CSV 或扫描工具 JSONL；仅离线分类，不发送探测请求。", "json", _INVENTORY),
    _profile("website-demo", "web", "website", "demo", "体验网站合成样例", "仅使用虚构 HTTP(S) 网站记录体验分类和证据流程，不包含非 Web 服务。", "demo", _INVENTORY),
    _profile("cloud-external", "web", "cloud", "probe", "云服务器服务地址", "只观察该地址的 HTTP(S) 服务，不读取云账号内部配置，不扫描端口。", "urls", _WEB, network=True),
    _profile("cloud-config", "cloud", "cloud", "import", "上传云配置", "AWS Terraform Plan JSON、IAM 策略或受支持的配置导出。", "json", _CLOUD),
    _profile("cloud-demo", "cloud", "cloud", "demo", "体验云配置样例", "本地审查合成 AWS 配置，无需云账号或访问密钥。", "demo", _CLOUD),
    _profile("host-baseline", "host", "host", "baseline", "上传主机配置资料", "带主机标识的 SSH/Nginx 配置导出 JSON，离线检查。", "json", _HOST_BASELINE),
    _profile("host-access-log", "host", "host", "access_log", "导入 Nginx 访问日志", "支持标准 common/combined 日志；结果排除原始请求目标与查询参数。", "json", _HOST_ACCESS),
    _profile("host-auth-log", "host", "host", "auth_log", "导入 SSH 认证日志", "支持有限 OpenSSH 认证事件；无法确定时间的记录保留覆盖缺口。", "json", _HOST_AUTH),
    _profile("host-demo", "host", "host", "demo", "体验主机防御样例", "合成配置和日志，体验证据复核与人工整改。", "demo", [*_HOST_BASELINE, *_HOST_ACCESS, *_HOST_AUTH]),
]


def catalog() -> dict[str, Any]:
    return {"asset_kinds": [
        {"id": "android", "label": "安卓应用", "description": "APK 或应用源码样例"},
        {"id": "website", "label": "网站", "description": "HTTP(S) 网站地址或已保存的网站记录"},
        {"id": "cloud", "label": "云资产", "description": "云服务器服务地址或云配置文件"},
        {"id": "host", "label": "主机防御", "description": "本地配置导出、Web 访问日志或 SSH 认证日志"},
    ], "profiles": copy.deepcopy(_PROFILES)}


def profile_by_id(identifier: str) -> dict[str, Any]:
    for profile in _PROFILES:
        if profile["id"] == identifier:
            return copy.deepcopy(profile)
    raise WorkbenchError("PROFILE_NOT_FOUND", "找不到这个资产检查入口")


def validate_binding(asset: dict[str, Any], module: str, config: dict[str, Any]) -> None:
    """The saved asset must actually be the input to its associated task."""
    source = asset["source"]
    profile = profile_by_id(source["profile_id"])
    if profile["module"] != module or profile["asset_kind"] != asset["kind"] or source["mode"] != config.get("mode"):
        raise WorkbenchError("ASSET_MISMATCH", "资产类型或输入方式与任务不一致")
    for field in ("upload_id", "filename", "targets", "sample", "apktool", "allow_private", "host_id"):
        if field in source and source[field] != config.get(field):
            raise WorkbenchError("ASSET_MISMATCH", "任务输入与保存的资产不一致；请选择对应资产或另建资产")
