"""apktool 解码后的 AndroidManifest.xml 解析（PLAN §5.2 / TASKS T1.2）。

只依赖 `xml.etree.ElementTree` 标准库。产物是 IR：`Component` / `IntentFilter`。
`impl_present` 本卡恒为 True，由 T2.1 用 smali 索引回填。
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from ..ir.model import Component, ComponentType, IntentFilter, SourceLoc
from ..ir.serialize import IRSerializable, serialize
from .apk import IngestError

logger = logging.getLogger("reachscope.ingest.manifest")

#: Android 命名空间（PLAN §5.2）。
ANDROID_NS = "http://schemas.android.com/apk/res/android"

#: 组件标签 → IR 的 ComponentType。
COMPONENT_TAGS: dict[str, ComponentType] = {
    "activity": ComponentType.ACTIVITY,
    "activity-alias": ComponentType.ACTIVITY_ALIAS,
    "service": ComponentType.SERVICE,
    "receiver": ComponentType.RECEIVER,
    "provider": ComponentType.PROVIDER,
}

#: targetSdk 达到该值时，缺 `android:exported` 的组件默认不导出（PLAN §5.2）。
EXPORTED_DEFAULT_CHANGED_SDK = 31

#: apktool 把 `<uses-sdk>` 挪到了解码根目录的这个文件里（真实 APK 实测，D-054）。
APKTOOL_YML = "apktool.yml"

#: `apktool.yml` 的 `sdkInfo` 块里只认这两个键。
SDK_KEYS = ("minSdkVersion", "targetSdkVersion")

#: 内置权限保护级别表（PLAN §5.2：只收录 v0.1 需要的，其余回落 unknown）。
KNOWN_PERMISSIONS: dict[str, str] = {
    "android.permission.INTERNET": "normal",
    "android.permission.ACCESS_NETWORK_STATE": "normal",
    "android.permission.ACCESS_WIFI_STATE": "normal",
    "android.permission.BLUETOOTH": "normal",
    "android.permission.VIBRATE": "normal",
    "android.permission.WAKE_LOCK": "normal",
    "android.permission.FOREGROUND_SERVICE": "normal",
    "android.permission.POST_NOTIFICATIONS": "dangerous",
    "android.permission.CAMERA": "dangerous",
    "android.permission.RECORD_AUDIO": "dangerous",
    "android.permission.READ_CONTACTS": "dangerous",
    "android.permission.WRITE_CONTACTS": "dangerous",
    "android.permission.ACCESS_FINE_LOCATION": "dangerous",
    "android.permission.ACCESS_COARSE_LOCATION": "dangerous",
    "android.permission.READ_PHONE_STATE": "dangerous",
    "android.permission.CALL_PHONE": "dangerous",
    "android.permission.SEND_SMS": "dangerous",
    "android.permission.READ_SMS": "dangerous",
    "android.permission.SYSTEM_ALERT_WINDOW": "signature",
    "android.permission.WRITE_SECURE_SETTINGS": "signature",
    "android.permission.BIND_ACCESSIBILITY_SERVICE": "signature",
    "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE": "signature",
    "android.permission.BIND_DEVICE_ADMIN": "signature",
    "android.permission.BIND_VPN_SERVICE": "signature",
    "android.permission.CHANGE_COMPONENT_ENABLED_STATE": "signature",
    "android.permission.INSTALL_PACKAGES": "signature",
    "android.permission.DELETE_PACKAGES": "signature",
}

#: protectionLevel 的数值写法（AOSP 定义），apktool 偶有输出。
_NUMERIC_PROTECTION = {"0": "normal", "1": "dangerous", "2": "signature", "3": "signature"}

#: 保护级别的优先级，取最高一档（含 signature 即签名级）。
_PROTECTION_PRIORITY = ("signature", "dangerous", "normal")


@dataclass(frozen=True)
class ManifestInfo(IRSerializable):
    """manifest 解析结果。

    除了组件列表，还带上 exported 推断与 Meta 需要的包信息/SDK 版本/警告。
    """

    package: str = ""
    version_name: str = ""
    version_code: str = ""
    min_sdk: int | None = None
    target_sdk: int | None = None
    permissions: dict[str, str] = field(default_factory=dict)
    components: list[Component] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", serialize(self))


def validate_manifest_structure(root: ET.Element) -> None:
    """Reject ambiguous singleton declarations instead of selecting the first."""
    if any(len(root.findall(tag)) > 1 for tag in ("application", "uses-sdk")):
        raise IngestError("manifest parse failed", "Manifest contains duplicate singleton elements")


def parse_manifest(path: str | Path) -> ManifestInfo:
    """解析 manifest，返回 :class:`ManifestInfo`（含全部组件）。"""
    manifest_path = Path(path)
    try:
        root = ET.parse(manifest_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise IngestError("manifest parse failed", f"{manifest_path} ({exc})") from exc
    if root.tag != "manifest":
        raise IngestError("manifest parse failed", f"{manifest_path} 根节点是 {root.tag}")
    validate_manifest_structure(root)

    uses_sdk = root.find("uses-sdk")
    warnings: list[str] = []
    target_sdk = _sdk_level(uses_sdk, "targetSdkVersion", warnings, manifest_path)
    min_sdk = _sdk_level(uses_sdk, "minSdkVersion", warnings, manifest_path)
    if target_sdk is None or min_sdk is None:
        # apktool 2.x 把 <uses-sdk> 挪进了 apktool.yml，解码后的 manifest 里没有该元素
        # （真实 APK 实测，D-054）。优先级：manifest 显式值 > apktool.yml > None。
        from_yml = _sdk_from_apktool_yml(manifest_path.parent / APKTOOL_YML, warnings)
        if from_yml:
            logger.info("manifest 内没有 <uses-sdk>，改用 %s 的 sdkInfo：%s", APKTOOL_YML, from_yml)
        target_sdk = target_sdk if target_sdk is not None else from_yml.get("targetSdkVersion")
        min_sdk = min_sdk if min_sdk is not None else from_yml.get("minSdkVersion")
    declared = _declared_permissions(root)

    components: list[Component] = []
    application = root.find("application")
    if application is None:
        message = f"{manifest_path}：manifest 中没有 <application> 节点"
        logger.warning(message)
        warnings.append(message)
    else:
        for element in application:
            component_type = COMPONENT_TAGS.get(element.tag)
            if component_type is None:
                continue
            components.append(
                _build_component(
                    element, component_type, declared, target_sdk, manifest_path, warnings,
                    application_permission=_attr(application, "permission"),
                )
            )

    declared_routes = sum(
        len(filter_.schemes) * max(1, len(filter_.hosts))
        * (max(1, len(filter_.paths) + len(filter_.path_patterns)) if filter_.hosts else 1)
        for component in components for filter_ in component.intent_filters
        if "android.intent.action.VIEW" in filter_.actions
        and "android.intent.category.BROWSABLE" in filter_.categories
    )
    if declared_routes > 2000:
        warnings.append("深链声明组合总量超过 2000 条预算，候选路径清单截断；缺少条目不能作为不存在的证据")
    return ManifestInfo(
        # `package` 不在 android 命名空间下，是 <manifest> 的普通属性。
        package=root.get("package") or "",
        version_name=_attr(root, "versionName") or "",
        version_code=_attr(root, "versionCode") or "",
        min_sdk=min_sdk,
        target_sdk=target_sdk,
        permissions=declared,
        components=components,
        warnings=warnings,
    )


def resolve_permission_protection(name: str | None, declared: dict[str, str]) -> str | None:
    """解析权限的保护级别。

    - 应用自己声明的 `<permission>` → 用其 protectionLevel
    - `android.permission.*` → 查内置表
    - 其它 / 查不到 → `"unknown"`（显式状态，不用 None 冒充）
    """
    if not name:
        return None
    if name in declared:
        return normalize_protection_level(declared[name])
    if name.startswith("android.permission."):
        return KNOWN_PERMISSIONS.get(name, "unknown")
    return "unknown"


def normalize_protection_level(raw: str) -> str:
    """把 protectionLevel 规范成 `normal` / `dangerous` / `signature` / `unknown`。

    支持多值组合（`signature|privileged`）与数值写法（`0x2` / `2`）。
    """
    flags = [part.strip().lower() for part in raw.split("|") if part.strip()]
    if not flags:
        return "unknown"
    normalized = [_normalize_flag(flag) for flag in flags]
    for level in _PROTECTION_PRIORITY:
        if level in normalized:
            return level
    return "unknown"


def expand_intent_filters(element: ET.Element) -> list[IntentFilter]:
    """Retain one filter per XML element; sibling data contributes shared sets.

    Android combines schemes, authorities and paths across sibling ``data``
    elements. Treating each element as an independent filter loses valid declared
    routes (https://developer.android.com/guide/topics/manifest/data-element).
    These lists are declarations, not a complete platform URI matcher.
    """
    filters: list[IntentFilter] = []
    for filter_element in element.findall("intent-filter"):
        actions = [_attr(child, "name") for child in filter_element.findall("action")]
        categories = [_attr(child, "name") for child in filter_element.findall("category")]
        auto_verify = (_attr(filter_element, "autoVerify") or "").lower() == "true"
        data_elements = filter_element.findall("data")
        filters.append(IntentFilter(
            actions=list(dict.fromkeys(a for a in actions if a)),
            categories=list(dict.fromkeys(c for c in categories if c)),
            schemes=_data_values(data_elements, "scheme"), hosts=_data_values(data_elements, "host"),
            ports=_data_values(data_elements, "port"), paths=_data_values(data_elements, "path", "pathPrefix"),
            path_patterns=_data_values(data_elements, "pathPattern"),
            auto_verify=auto_verify,
        ))
    return filters


def _build_component(
    element: ET.Element,
    component_type: ComponentType,
    declared: dict[str, str],
    target_sdk: int | None,
    manifest_path: Path,
    warnings: list[str],
    *,
    application_permission: str | None = None,
) -> Component:
    """按 §5.2 的规则构造一个 `Component`。"""
    name = _attr(element, "name") or ""
    intent_filters = expand_intent_filters(element)
    exported, exported_inferred = _infer_exported(
        element, intent_filters, target_sdk, name, warnings
    )
    permission = _attr(element, "permission")
    # Alias permission has independent semantics: an unset attribute does not
    # inherit the target activity's restriction. Other components inherit the
    # application default; an explicitly empty value clears that default.
    if permission is None and component_type is not ComponentType.ACTIVITY_ALIAS:
        permission = application_permission
    permission = permission or None
    protection = resolve_permission_protection(permission, declared)
    if component_type is ComponentType.PROVIDER:
        directional = [_attr(element, name) for name in ("readPermission", "writePermission")]
        if any(value is not None and (value or None) != permission for value in directional):
            # One legacy IR permission cannot represent separate read/write
            # access. Never let a single signature gate prove both directions.
            protection = "unknown"
            warnings.append(f"{name}：provider 读写权限覆盖不同，单一权限字段不能证明完整访问控制；需逐方向复核")
        if element.find("path-permission") is not None or element.find("grant-uri-permission") is not None or _attr(element, "grantUriPermissions") == "true":
            protection = "unknown"
            warnings.append(f"{name}：provider 含路径或临时 URI 授权，基础权限不代表完整有效访问控制")
    for filter_ in intent_filters:
        combinations = len(filter_.schemes) * max(1, len(filter_.hosts)) * max(1, len(filter_.paths) + len(filter_.path_patterns))
        if combinations > 2000:
            warnings.append(f"{name}：深链声明组合超过 2000 条预算，路径清单将截断；未列出不代表不存在")
    for filter_element in element.findall("intent-filter"):
        if filter_element.find("uri-relative-filter-group") is not None or any(
            _attr(data, attr) is not None for data in filter_element.findall("data")
            for attr in ("mimeType", "pathSuffix", "pathAdvancedPattern")
        ):
            warnings.append(f"{name}：深链含 MIME、后缀、高级模式或 URI 相对分组；候选 URL 不等于完整系统匹配结果")

    return Component(
        name=name,
        type=component_type,
        exported=exported,
        exported_inferred=exported_inferred,
        permission=permission,
        permission_protection=protection,
        intent_filters=intent_filters,
        impl_present=True,
        # `<activity-alias>` 的 android:name 在 APK 里没有对应类，实现是 targetActivity
        # （D-032b）：T2.1 对 alias 用规范化后的 target 类判定 impl_present。
        target_activity=(_attr(element, "targetActivity") or None)
        if component_type is ComponentType.ACTIVITY_ALIAS
        else None,
        # SourceLoc.file 必须是相对解码根目录的路径，绝对临时路径会破坏 §9.3 确定性（D-036）。
        source=SourceLoc(file=manifest_path.name, line=0, snippet=_snippet(element)),
    )


def _infer_exported(
    element: ET.Element,
    intent_filters: list[IntentFilter],
    target_sdk: int | None,
    name: str,
    warnings: list[str],
) -> tuple[bool, bool]:
    """exported 推断三分支（PLAN §5.2）。"""
    raw = _attr(element, "exported")
    if raw is not None:
        if raw.strip().lower() not in {"true", "false"}:
            warnings.append(f"{name}：exported 不是已解析布尔值；旧布尔 IR 保守保留候选，不能证明实际导出")
            return True, True
        return raw.strip().lower() == "true", False

    if element.tag == "provider":
        if target_sdk is None:
            warnings.append(f"{name}：provider 缺少 targetSdkVersion，导出默认依赖系统/目标版本；保守保留候选")
            return True, True
        return target_sdk <= 16, True

    if not intent_filters:
        return False, False

    if target_sdk is None:
        warnings.append(
            f"{name}：未声明 targetSdkVersion，按 < {EXPORTED_DEFAULT_CHANGED_SDK} 处理，推断 exported=true"
        )
        logger.warning("%s：未声明 targetSdkVersion，按旧规则推断 exported=true", name)
        return True, True

    if target_sdk >= EXPORTED_DEFAULT_CHANGED_SDK:
        warnings.append(f"{name}：targetSdk>=31 且含 intent-filter，但缺少显式 android:exported；Android 12+ 安装要求不满足，不能解释为安全的未导出")
        return False, True
    return True, True


def _declared_permissions(root: ET.Element) -> dict[str, str]:
    """收集应用自己声明的 `<permission>`：name → protectionLevel 原文。"""
    declared: dict[str, str] = {}
    for element in root.findall("permission"):
        name = _attr(element, "name")
        if name:
            declared[name] = _attr(element, "protectionLevel") or "normal"
    return declared


def _normalize_flag(flag: str) -> str:
    """把单个 protectionLevel 标记规范成文字。

    数值写法按 AOSP 语义取**基础级别**：`protectionLevel & 0xf`，
    所以 `0x12`（privileged|signature）判 signature，而不是 unknown（D-037）。
    """
    text = flag.removeprefix("0x")
    try:
        return _NUMERIC_PROTECTION[str(int(text, 16) & 0xF)]
    except (ValueError, KeyError):
        return _NUMERIC_PROTECTION.get(text, flag)


def _sdk_level(
    uses_sdk: ET.Element | None,
    attr: str,
    warnings: list[str] | None = None,
    manifest_path: Path | None = None,
) -> int | None:
    """读 SDK 版本，非数字返回 None（显式“未解析”，并记 warning，§9.2）。"""
    if uses_sdk is None:
        return None
    raw = _attr(uses_sdk, attr)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        message = f"{manifest_path or 'manifest'}：无法解析 {attr}={raw!r}，按未声明处理"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None


def _sdk_from_apktool_yml(path: Path, warnings: list[str]) -> dict[str, int]:
    """从 `apktool.yml` 的 `sdkInfo` 块读 `minSdkVersion` / `targetSdkVersion`。

    手写解析（不引入 PyYAML，§9.1）：只认 `sdkInfo:` 顶层键下面的两行，
    允许任意缩进与可选引号；文件不存在或不可解析 → 返回空字典，不加 warning
    （那是正常情况，后续的 D-022 “未声明 targetSdk”路径仍会按旧规则告警）。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    levels: dict[str, int] = {}
    in_sdk_info = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[:1].isspace():
            # 顶层键：只在 sdkInfo 块内才继续解析
            in_sdk_info = stripped.rstrip(":").strip("'\"") == "sdkInfo"
            continue
        if not in_sdk_info:
            continue
        key, separator, value = stripped.partition(":")
        key = key.strip().strip("'\"")
        if not separator or key not in SDK_KEYS:
            continue
        number = _parse_int(value)
        if number is None:
            message = f"{path.name}：sdkInfo 里 {key}={value.strip()!r} 无法解析，按未声明处理"
            logger.warning(message)
            warnings.append(message)
        else:
            levels[key] = number
    return levels


def _parse_int(raw: str) -> int | None:
    """`23` / `'23'` / `"23"` → 23；其它（含非数字）→ None。"""
    text = raw.strip().strip("'\"").strip()
    if not text:
        return None
    try:
        return int(text, 10)
    except ValueError:
        return None


def _single(data: ET.Element, attr: str) -> list[str]:
    """取 `<data>` 上的单值属性，返回 0 或 1 个元素的列表。"""
    value = _attr(data, attr)
    return [value] if value else []


def _data_values(elements: list[ET.Element], *attributes: str) -> list[str]:
    return list(dict.fromkeys(value for data in elements for attribute in attributes
                              for value in _single(data, attribute)))


def _attr(element: ET.Element, name: str) -> str | None:
    """读 android 命名空间下的属性。"""
    return element.get(f"{{{ANDROID_NS}}}{name}")


def _snippet(element: ET.Element) -> str:
    """组件节点的 XML 片段（SourceLoc 会自动截断到 200 字符）。"""
    return ET.tostring(element, encoding="unicode").strip()
