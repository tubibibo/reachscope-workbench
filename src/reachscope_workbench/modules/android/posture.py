"""Bounded, deterministic Android configuration review; never a runtime verdict.

Defaults and declarations are evaluated separately from code-path inference. XML
resources are read only from the actual decoded input; missing/qualified resources
are not replaced by guessed settings. No app, intent or network request is run.
"""

from __future__ import annotations

import hashlib
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from reachscope.extract.components import normalize_class_name
from reachscope.ingest.apk import IngestError
from reachscope.ingest.manifest import ANDROID_NS, KNOWN_PERMISSIONS, validate_manifest_structure

MANIFEST_LIMIT = 2 * 1024 * 1024
RESOURCE_LIMIT = 256 * 1024
MAX_COMPONENTS = 200
MAX_FILTERS = 200
MAX_FACTS = 80
MAX_RESOURCE_VARIANTS = 16
REVIEW_IDS = frozenset(f"android.{key}" for key in (
    "debuggable", "test_only", "backup", "cleartext", "trust_anchors", "debug_overrides", "exported_components", "deeplinks",
))
_XML_REF = re.compile(r"@xml/([a-zA-Z0-9_]+)\Z")
_COMPONENT_TAGS = {"activity", "activity-alias", "service", "receiver", "provider"}
_DOCS = {
    "application": "https://developer.android.com/guide/topics/manifest/application-element",
    "network": "https://developer.android.com/privacy-and-security/security-config",
    "backup": "https://developer.android.com/identity/data/autobackup",
    "exported": "https://developer.android.com/privacy-and-security/risks/android-exported",
    "provider": "https://developer.android.com/guide/topics/manifest/provider-element",
    "links": "https://developer.android.com/training/app-links/verify-applinks",
}


def _attr(element: ET.Element, name: str) -> str | None:
    raw = element.get(f"{{{ANDROID_NS}}}{name}")
    return "@unresolved:attribute_limit" if raw is not None and len(raw) > 1000 else raw


def _boolean(raw: str | None, default: bool | None = None) -> bool | None:
    if raw is None:
        return default
    return {"true": True, "false": False}.get(raw.strip().lower())


def _safe_xml(path: Path, limit: int) -> tuple[ET.Element, str]:
    for current in (path, *path.parents):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise IngestError("unsafe XML", "XML input cannot contain links or reparse points")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise IngestError("XML limit", "XML must be a regular file within its byte budget")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit or len(raw) != info.st_size:
        raise IngestError("XML limit", "XML grew or changed while reading")
    declarations = raw.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise IngestError("XML declarations", "Document declarations are not accepted")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise IngestError("XML invalid", "XML could not be parsed") from exc
    pending = [(root, 1)]
    nodes = 0
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if nodes > 10_000 or depth > 40:
            raise IngestError("XML limit", "XML exceeds the node/depth budget")
        pending.extend((child, depth + 1) for child in node)
    return root, hashlib.sha256(raw).hexdigest()


def _fact(pointer: str, value: Any, source: str = "AndroidManifest.xml") -> dict[str, Any]:
    return {"source": source, "pointer": pointer, "value": value}


def _check(
    package: str, key: str, title: str, status: str, description: str,
    facts: list[dict[str, Any]], steps: list[str], *, docs: str = "application",
) -> dict[str, Any]:
    truncated = len(facts) > MAX_FACTS
    if truncated and status == "pass":
        status = "unknown"
    return {
        "id": f"android.{key}", "resource_id": package,
        "title": title, "status": status, "description": description,
        "recommendation": steps[0], "evidence_ids": [f"android-review:android.{key}"],
        "source": "AndroidManifest.xml", "pointer": facts[0]["pointer"] if facts else "/manifest/application",
        "facts": facts[:MAX_FACTS], "facts_truncated": truncated,
        "complete": status in {"pass", "review", "not_applicable"} and not truncated,
        "guidance": {
            "red_review": ["仅在获得授权的测试构建与设备中核对配置对应的业务入口；结合源码、身份条件和运行版本验证，不把声明当作可利用漏洞。"],
            "blue_steps": steps,
            "verification": ["用相同检查项重新分析修订后的同一应用；确认目标项不再观察到、没有未知或缺失证据。", "在支持的真实 Android 版本上回归相关业务；本工具未安装或执行目标应用。"],
            "rollback": ["保留原配置与构建版本，若业务回归失败，通过正常构建发布流程恢复，并重新复核。"],
            "limitations": ["静态清单/资源事实不能证明运行时可达性、实际数据泄漏或修复完成。"],
        },
        "references": [{"title": "Android 官方配置说明", "url": _DOCS[docs]}],
    }


def _permission_level(name: str | None, declared: dict[str, str]) -> str:
    if not name:
        return "none"
    raw = declared.get(name, KNOWN_PERMISSIONS.get(name, "unknown"))
    try:
        numeric = int(raw, 0) & 0xF
        return {0: "normal", 1: "dangerous", 2: "signature", 3: "signature"}.get(numeric, "unknown")
    except ValueError:
        values = raw.lower().split("|")
        for kind in ("signature", "signatureorsystem", "dangerous", "normal"):
            if kind in values:
                return "signature" if kind == "signatureorsystem" else kind
        return "normal" if raw == "" else "unknown"


def component_assessments(root: ET.Element, target_sdk: int | None, min_sdk: int | None) -> list[dict[str, Any]]:
    """Keep unresolved/invalid export declarations distinct from exported=false."""
    app = root.find("application")
    if app is None:
        return []
    package = root.get("package", "")
    declared = {_attr(item, "name") or "": _attr(item, "protectionLevel") or "" for item in root.findall("permission")}
    records: list[dict[str, Any]] = []
    for element in app:
        if element.tag not in _COMPONENT_TAGS:
            continue
        explicit = _attr(element, "exported")
        filtered = element.find("intent-filter") is not None
        exported = _boolean(explicit)
        reason = "显式 exported 声明" if exported is not None else "无法解析 exported 声明"
        if explicit is None:
            if element.tag == "provider":
                if target_sdk is None:
                    exported, reason = None, "缺少可解析 target SDK，无法应用 Provider 默认值"
                elif target_sdk <= 16:
                    exported, reason = True, "target SDK≤16 的 Provider 旧版默认导出"
                elif min_sdk is None or min_sdk <= 16:
                    exported, reason = None, "Provider 默认值随设备版本变化；API≤16 忽略 exported，需核对支持范围"
                else:
                    exported, reason = False, "target SDK≥17 且 min SDK≥17 的 Provider 默认不导出"
            elif filtered and target_sdk is not None and target_sdk >= 31:
                exported, reason = None, "target SDK≥31 的带过滤器组件必须显式声明 exported；缺失不是安全关闭"
            elif filtered and target_sdk is None:
                exported, reason = None, "缺少可解析 target SDK，无法判断带过滤器组件的默认导出行为"
            else:
                exported, reason = filtered, "旧版带过滤器默认导出" if filtered else "无过滤器默认不导出"
        if element.tag == "provider" and exported is False and (min_sdk is None or min_sdk <= 16):
            exported, reason = None, "API≤16 设备忽略 Provider exported=false；支持版本范围未排除此行为"
        permission = _attr(element, "permission")
        inherited = _attr(app, "permission") if element.tag != "activity-alias" else None
        effective_permission = permission if permission is not None else inherited
        permissions = [effective_permission]
        if element.tag == "provider":
            permissions = [_attr(element, "readPermission") if _attr(element, "readPermission") is not None else effective_permission,
                           _attr(element, "writePermission") if _attr(element, "writePermission") is not None else effective_permission]
        levels = [_permission_level(value, declared) for value in permissions]
        enabled = _boolean(_attr(element, "enabled"), True)
        app_enabled = _boolean(_attr(app, "enabled"), True)
        if enabled is False or app_enabled is False:
            status = "not_applicable"
        elif exported is None or enabled is None or app_enabled is None:
            status = "unknown"
        elif not exported:
            status = "pass"
        elif any(level == "unknown" for level in levels):
            status = "unknown"
        elif all(level == "signature" for level in levels) and not element.findall("path-permission"):
            status = "pass"
        else:
            status = "review"
        records.append({
            "name": normalize_class_name(_attr(element, "name") or "", package), "type": element.tag,
            "effective_exported": exported, "export_reason": reason, "exported_assessment": status,
            "inherited_permission": inherited, "effective_permission": effective_permission,
            "permission_levels": levels, "read_permission": permissions[0] if element.tag == "provider" else None,
            "write_permission": permissions[1] if element.tag == "provider" else None,
            "path_permissions": len(element.findall("path-permission")),
            "grant_uri_permissions": _boolean(_attr(element, "grantUriPermissions"), False),
        })
    return records


def _resources(directory: Path, reference: str | None, expected: str) -> dict[str, Any]:
    result: dict[str, Any] = {"reference": reference, "status": "not_applicable", "variants": [], "total": 0, "complete": True}
    if reference is None or reference == "false":
        return result
    match = _XML_REF.fullmatch(reference)
    if not match:
        return {**result, "status": "unknown", "complete": False, "reason": "资源引用未解析；仅支持当前包 @xml/name"}
    root = directory / "res"
    # Do not follow directory links, including a linked res root.
    try:
        if not root.exists():
            return {**result, "status": "unknown", "complete": False, "reason": "解码输入未提供 XML 资源"}
        info = root.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return {**result, "status": "unknown", "complete": False, "reason": "资源目录为链接，未读取"}
        variants = []
        for index, folder in enumerate(root.iterdir()):
            if index >= 2048:
                return {**result, "status": "unknown", "complete": False, "reason": "资源目录项超过预算"}
            if folder.name == "xml" or folder.name.startswith("xml-"):
                variants.append(folder / (match.group(1) + ".xml"))
                if len(variants) > 256:
                    return {**result, "status": "unknown", "complete": False, "reason": "资源变体目录超过预算"}
        candidates = [path for path in sorted(variants) if path.exists()]
        result["total"] = len(candidates)
        result["complete"] = 0 < len(candidates) <= MAX_RESOURCE_VARIANTS and any(path.parent.name == "xml" for path in candidates)
        for path in candidates[:MAX_RESOURCE_VARIANTS]:
            source = path.relative_to(directory).as_posix()
            try:
                xml, digest = _safe_xml(path, RESOURCE_LIMIT)
                if xml.tag != expected:
                    raise IngestError("XML root", "Unexpected resource XML root")
                if expected == "network-security-config" and (len(xml.findall("base-config")) > 1 or len(xml.findall("debug-overrides")) > 1):
                    raise IngestError("XML structure", "Duplicate network configuration singleton")
                result["variants"].append({"source": source, "sha256": digest, "root": xml, "status": "parsed"})
            except (IngestError, OSError):
                result["variants"].append({"source": source, "status": "unknown"})
                result["complete"] = False
        result["status"] = "parsed" if result["complete"] else "unknown"
        return result
    except OSError:
        return {**result, "status": "unknown", "complete": False, "reason": "资源不可读取"}


def inspect_security_review(path: Path, *, target_sdk: int | None = None, min_sdk: int | None = None) -> dict[str, Any]:
    root, _ = _safe_xml(path, MANIFEST_LIMIT)
    if root.tag != "manifest":
        raise IngestError("manifest parse failed", "XML root must be manifest")
    validate_manifest_structure(root)
    sdk_element = root.find("uses-sdk")
    if sdk_element is not None:
        for name in ("targetSdkVersion", "minSdkVersion"):
            raw = _attr(sdk_element, name)
            parsed = int(raw) if raw is not None and raw.isascii() and raw.isdecimal() and len(raw) <= 4 else None
            if name == "targetSdkVersion" and target_sdk is None:
                target_sdk = parsed
            elif name == "minSdkVersion" and min_sdk is None:
                min_sdk = parsed
    app = root.find("application")
    if app is None:
        app = ET.Element("application")
    package = root.get("package", "")[:300]
    checks: list[dict[str, Any]] = []
    missing_app = root.find("application") is None
    for attribute, key, title in (("debuggable", "debuggable", "发布构建调试标记"), ("testOnly", "test_only", "测试专用安装标记")):
        value = _boolean(_attr(app, attribute), False)
        status = "unknown" if missing_app or value is None else "review" if value else "pass"
        checks.append(_check(package, key, title, status, "记录显式声明或平台默认值；未证明设备是否允许调试或安装。",
                             [_fact(f"/manifest/application/@android:{attribute}", {"declared": _attr(app, attribute), "effective": None if missing_app else value})],
                             [f"确认发布构建将 android:{attribute} 关闭；从构建变体配置修正并重新打包，而不是直接改动已签名 APK。", "开发/测试构建如需开启，应限制分发范围并与发布签名、数据隔离。 "]))
    components = component_assessments(root, target_sdk, min_sdk)
    captured = components[:MAX_COMPONENTS]
    statuses = [item["exported_assessment"] for item in captured]
    export_status = "review" if "review" in statuses else "unknown" if "unknown" in statuses or len(components) > MAX_COMPONENTS or missing_app else "pass"
    checks.append(_check(package, "exported_components", "组件导出与声明权限边界", export_status,
                         "逐项结合 target/min SDK、过滤器、继承权限和 Provider 读写声明；导出本身是入口事实。签名权限只表明声明门槛，不验证签名关系或业务授权。",
                         [_fact(f"/manifest/application/{item['type']}[{index}]", item) for index, item in enumerate(captured)],
                         ["仅对确需外部调用的组件保留导出；为跨应用接口明确认证、授权、输入校验与最小权限。", "核对应用继承权限、Provider 读/写/path-permission 与临时 URI 授权；不要仅依赖 exported=false 判断所有访问。", "target SDK≥31 的带过滤器入口显式填写 exported；同时回归启动器、通知、深链与集成调用。"], docs="exported"))
    _backup_check(checks, path, app, package, target_sdk, missing_app)
    resource_counts = _network_checks(checks, path, app, package, target_sdk, min_sdk, missing_app)
    link_count = _link_check(checks, app, package, missing_app)
    return {
        "version": 1, "package": package, "checks": checks,
        "coverage": {"components_total": len(components), "components_returned": len(captured),
                     "deeplink_filters_total": link_count, "deeplink_filters_returned": min(link_count, MAX_FILTERS),
                     **resource_counts, "truncated": len(components) > MAX_COMPONENTS or link_count > MAX_FILTERS or
                     resource_counts["resources_total"] > resource_counts["resources_returned"] or any(check["facts_truncated"] for check in checks)},
        "limitations": ["仅评估已采集清单与 XML 资源；未安装/执行 APK、验证系统实际版本、签名、证书或域名归属。", "pass 表示当前静态条件未观察到该复核项，不代表应用整体安全。未知字段、资源变体缺失和截断不能作为修复证明。", "组件默认行为与设备/目标 SDK 有关；原候选代码图仍保留其静态分析范围，不因本清单复核自动扩张。"],
    }


def _backup_check(checks: list[dict[str, Any]], path: Path, app: ET.Element, package: str, sdk: int | None, missing: bool) -> None:
    allow = _boolean(_attr(app, "allowBackup"), True)
    facts = [_fact("/manifest/application/@android:allowBackup", {"declared": _attr(app, "allowBackup"), "effective": allow})]
    refs = [("fullBackupContent", "full-backup-content"), ("dataExtractionRules", "data-extraction-rules")]
    complete = True
    for attribute, expected in refs:
        reference = _attr(app, attribute)
        resource = _resources(path.parent, reference, expected)
        if reference is not None and resource["status"] == "unknown":
            complete = False
        facts.append(_fact(f"/manifest/application/@android:{attribute}", {"reference": reference, "status": resource["status"]}))
        for variant in resource["variants"]:
            rules = []
            if variant["status"] == "parsed":
                xml = variant["root"]
                rules = [{"kind": item.tag, "domain": item.get("domain"), "path": item.get("path")[:200] if item.get("path") else None}
                         for item in xml.iter() if item.tag in {"include", "exclude"}][:30]
            facts.append(_fact("/" + expected, {"status": variant["status"], "sha256": variant.get("sha256"), "rules": rules}, variant["source"]))
    if missing or allow is None or sdk is None or not complete:
        status = "unknown"
    elif allow:
        status = "review"
    elif sdk >= 31:
        status = "unknown"
    else:
        status = "pass"
    checks.append(_check(package, "backup", "备份与设备迁移数据范围", status,
                         "备份默认允许，排除规则需结合真实敏感数据核对；target SDK≥31 时 allowBackup=false 在部分厂商设备上不能证明关闭设备迁移。仅声明规则不代表已排除所有敏感数据。",
                         facts, ["按业务数据分类配置 fullBackupContent 与 dataExtractionRules，明确云备份及设备迁移的敏感路径排除。", "在支持的真实设备版本验证恢复与迁移；保留必要用户数据，不应机械地关闭全部备份。"], docs="backup"))


def _network_checks(checks: list[dict[str, Any]], path: Path, app: ET.Element, package: str, sdk: int | None, min_sdk: int | None, missing: bool) -> dict[str, int]:
    reference = _attr(app, "networkSecurityConfig")
    resource = _resources(path.parent, reference, "network-security-config")
    declared = _boolean(_attr(app, "usesCleartextTraffic"))
    default_clear = sdk <= 27 if sdk is not None else None
    clear = declared if _attr(app, "usesCleartextTraffic") is not None else default_clear
    clear_values: list[bool | None] = []
    trust_values: list[str | None] = []
    debug_values: list[str | None] = []
    common = [_fact("/manifest/application/@android:networkSecurityConfig", {"reference": reference, "status": resource["status"], "complete": resource["complete"]})]
    clear_facts = common + [_fact("/manifest/application/@android:usesCleartextTraffic", {"declared": _attr(app, "usesCleartextTraffic"), "platform_default": default_clear})]
    trust_facts = list(common)
    debug_facts = list(common)
    if reference is None:
        clear_values.append(clear)
        trust_values.append("user" if sdk is not None and sdk <= 23 else "system" if sdk is not None else None)
    else:
        for variant in resource["variants"]:
            if variant["status"] != "parsed":
                clear_values.append(None)
                trust_values.append(None)
                continue
            xml = variant["root"]
            base = xml.find("base-config")
            base_clear = _boolean(base.get("cleartextTrafficPermitted"), default_clear) if base is not None else default_clear
            clear_values.append(base_clear)
            clear_facts.append(_fact("/network-security-config/base-config/@cleartextTrafficPermitted", {"effective": base_clear, "sha256": variant["sha256"]}, variant["source"]))
            certs = [node.get("src") for node in xml.findall("./base-config/trust-anchors/certificates")]
            if base is not None and base.find("trust-anchors") is not None and not certs:
                certs = [None]
            default_certs: list[str | None] = ["system", "user"] if sdk is not None and sdk <= 23 else ["system"] if sdk is not None else [None]
            trust_values.extend(certs if certs else default_certs)
            for domain, value, inherited_certs in _domain_values(xml, base_clear, certs or default_certs):
                clear_values.append(value)
                trust_values.extend(inherited_certs)
                clear_facts.append(_fact("/network-security-config/domain-config", {"domains": domain, "effective_cleartext": value}, variant["source"]))
            trust_facts.append(_fact("/network-security-config/trust-anchors", {"certificate_sources": [node.get("src") for node in xml.iter("certificates") if node not in list(xml.findall("./debug-overrides/trust-anchors/certificates"))], "base_effective_sources": certs or default_certs}, variant["source"]))
            debug = [node.get("src") for node in xml.findall("./debug-overrides/trust-anchors/certificates")]
            debug_values.extend(debug)
            debug_facts.append(_fact("/network-security-config/debug-overrides", {"certificate_sources": debug, "active_when_debuggable": True, "sha256": variant["sha256"]}, variant["source"]))
    incomplete = missing or (reference is not None and not resource["complete"])
    # NSC is only honored on API>=24; manifest usesCleartextTraffic starts at
    # API23. Retain the older supported-device branch, not just the target SDK.
    range_unknown = min_sdk is None or min_sdk < 23
    if reference is not None and min_sdk is not None and min_sdk <= 23:
        clear_values.append(clear if min_sdk == 23 else None)
        trust_values.append("user")
        clear_facts.append(_fact("/manifest/uses-sdk/@android:minSdkVersion", {"value": min_sdk, "legacy_manifest_cleartext": clear, "network_security_config_supported_from": 24}))
    if range_unknown:
        clear_values.append(None)
        trust_values.append(None)
    clear_status = "review" if True in clear_values else "unknown" if incomplete or not clear_values or None in clear_values or (sdk is not None and sdk >= 38 and reference is None) else "pass"
    trust_unknown = any(value is None or value not in {"system", "user"} for value in trust_values)
    trust_status = "review" if "user" in trust_values else "unknown" if incomplete or trust_unknown or not trust_values else "pass"
    debuggable = _boolean(_attr(app, "debuggable"), False)
    debug_status = "not_applicable" if debuggable is False and not missing else "unknown" if incomplete or debuggable is None else "review" if debug_values else "pass"
    added = [
        _check(package, "cleartext", "明文传输声明与域级例外", clear_status,
               "按 target SDK、Network Security Config 继承关系及资源变体评估声明；API≥24 配置资源优先于 manifest 标记。库与真实设备是否遵守未验证。",
               clear_facts, ["优先使用 HTTPS，移除不必要的明文域级例外；确需兼容时将例外限定到业务域并记录理由。", "在目标系统与实际网络库中验证策略；避免仅改 usesCleartextTraffic 却保留允许明文的资源配置。"], docs="network"),
        _check(package, "trust_anchors", "生产网络信任锚范围", trust_status,
               "用户证书信任需要业务复核；自定义原始证书或无法解析的资源保持未知，未判定证书有效性或实施中间人测试。",
               trust_facts, ["生产配置优先使用符合业务要求的信任锚；避免无业务理由信任用户证书。", "自定义 CA 与证书轮换需验证完整证书链及兼容性，勿直接删除企业必要 CA 或盲目增加证书锁定。"], docs="network"),
        _check(package, "debug_overrides", "调试专用网络信任配置", debug_status,
               "debug-overrides 仅在 debuggable=true 时生效，关闭调试的发布构建中不会启用；未执行 TLS 请求。",
               debug_facts + [_fact("/manifest/application/@android:debuggable", debuggable)],
               ["将测试信任锚限制在调试构建，并确认发布构建 debuggable=false。", "分别回归测试与发布变体，确保调试证书未作为生产 base/domain 信任锚。"], docs="network"),
    ]
    for check in added:
        if check["id"] != "android.debug_overrides" or check["status"] != "not_applicable":
            check["complete"] = check["complete"] and not incomplete and not range_unknown
    checks.extend(added)
    return {"resources_total": resource["total"], "resources_returned": len(resource["variants"])}


def _domain_values(root: ET.Element, inherited: bool | None, certs: list[str | None]) -> list[tuple[list[str], bool | None, list[str | None]]]:
    values: list[tuple[list[str], bool | None, list[str | None]]] = []
    pending = [(node, inherited, certs) for node in root.findall("domain-config")]
    while pending:
        node, parent_clear, parent_certs = pending.pop(0)
        clear = _boolean(node.get("cleartextTrafficPermitted"), parent_clear)
        sources = [item.get("src") for item in node.findall("./trust-anchors/certificates")] or parent_certs
        if node.find("trust-anchors") is not None and not node.findall("./trust-anchors/certificates"):
            sources = [None]
        values.append(([(item.text or "").strip()[:200] for item in node.findall("domain")], clear, sources))
        pending.extend((child, clear, sources) for child in node.findall("domain-config"))
    return values


def _link_check(checks: list[dict[str, Any]], app: ET.Element, package: str, missing: bool) -> int:
    filters = []
    for component in app:
        if component.tag not in {"activity", "activity-alias"}:
            continue
        for item in component.findall("intent-filter"):
            actions = [_attr(action, "name") for action in item.findall("action")]
            categories = [_attr(category, "name") for category in item.findall("category")]
            if "android.intent.action.VIEW" not in actions or "android.intent.category.BROWSABLE" not in categories:
                continue
            schemes = sorted({_attr(data, "scheme") or "" for data in item.findall("data")} - {""})
            hosts = sorted({_attr(data, "host") or "" for data in item.findall("data")} - {""})
            auto = _boolean(_attr(item, "autoVerify"), False)
            status = "review" if any(scheme not in {"https", "http"} for scheme in schemes) or any("*" in host for host in hosts) or auto is False else "unknown"
            filters.append({"component": normalize_class_name(_attr(component, "name") or "", package), "schemes": schemes[:20], "hosts": hosts[:20], "auto_verify_declared": auto, "domain_verification": "not_performed", "status": status,
                            "combination": "同一过滤器的 data 属性由 Android 合并匹配，未枚举 URL 笛卡尔积。"})
    status = "review" if any(item["status"] == "review" for item in filters[:MAX_FILTERS]) else "unknown" if filters or missing else "not_applicable"
    checks.append(_check(package, "deeplinks", "深链过滤器与域名验证边界", status,
                         "记录 VIEW+BROWSABLE 过滤器的合并 scheme/host 声明；HTTP scheme 本身不等于应用发出明文请求。autoVerify=true 只是请求系统验证，域名归属与实际验证结果始终未验证。",
                         [_fact(f"/manifest/application/intent-filter[{index}]", item) for index, item in enumerate(filters[:MAX_FILTERS])],
                         ["优先使用经过系统域名验证的 App Links；复核自定义 scheme、通配 host、路径及所有同过滤器组合。", "在受控设备核对域名验证结果及 assetlinks 关系，并在入口校验来源、授权和所有传入参数；本工具不会自动请求域名或触发链接。"], docs="links"))
    return len(filters)
