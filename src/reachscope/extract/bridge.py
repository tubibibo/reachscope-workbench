"""JS 桥提取（PLAN §5.5 / TASKS T2.4）。

主导键是**注册点** `addJavascriptInterface`：
- 有注册点 → 产出 `Bridge`；`impl_class` 由 obj 寄存器回溯 `new-instance` 得到
- 只有 `@JavascriptInterface` 方法、从未被注册的类 → **不产出**（不可达），
  但记一条 warning（可能是反射注册），warning 最终进 `Meta.warnings`（§9.2 / D-043）

`revoked` 在**全 APK 范围**匹配 `removeJavascriptInterface` 的名字参数。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..graph import regflow
from ..ingest.smali import ClassInfo, Instruction, MethodInfo, SmaliIndex
from ..ir.model import Bridge, BridgeMethod, ExposedTo, OriginCheck, SourceLoc
from ..ir.serialize import stable_id
from .components import class_name_of
from .webview import WEBVIEW_DESCRIPTOR

logger = logging.getLogger("reachscope.extract.bridge")

#: `@JavascriptInterface` 的注解描述符。
JAVASCRIPT_INTERFACE = "Landroid/webkit/JavascriptInterface;"

ADD_METHOD = "addJavascriptInterface"
REMOVE_METHOD = "removeJavascriptInterface"


@dataclass
class _Registration:
    """一个 `addJavascriptInterface` 注册点。"""

    name: str
    obj_register: str
    site: regflow.InvokeSite
    location: SourceLoc
    method: MethodInfo


@dataclass
class _Draft:
    """聚合中的桥。"""

    impl_class: str
    name: str
    registered_in: SourceLoc
    methods: list[BridgeMethod] = field(default_factory=list)


def extract_bridges(index: SmaliIndex, warnings: list[str] | None = None) -> list[Bridge]:
    """扫描全 APK 产出 `Bridge` 列表（按 `impl_class, name, id` 排序）。

    `warnings` 用于承载 §9.2 的告警（最终进 `Meta.warnings`）；传 None 时只写日志。
    """
    registrations, removals = _scan_callsites(index)
    annotated = _annotated_classes(index)

    drafts: list[_Draft] = []
    for registration in registrations:
        location = registration.location
        descriptor = regflow.backtrack_new_instance(
            registration.method, registration.site.index, registration.obj_register
        )
        impl_class = class_name_of(descriptor) if descriptor else ""
        if not impl_class:
            _warn(
                warnings,
                "addJavascriptInterface 的 obj 寄存器无法回溯到 new-instance"
                f"（{location.file}:{location.line}），impl_class 留空",
            )
        if not registration.name:
            _warn(
                warnings,
                "addJavascriptInterface 的桥名不是常量字符串"
                f"（{location.file}:{location.line}），桥名留空",
            )
        drafts.append(
            _Draft(
                impl_class=impl_class,
                name=registration.name,
                registered_in=location,
                methods=_bridge_methods(index.get_class(descriptor)) if descriptor else [],
            )
        )

    _warn_unregistered(annotated, drafts, warnings)

    bridges = [_build(draft, removals) for draft in drafts]
    # §4.7 的 Bridge 没有“JS 名”字段，注册名只用于 revoke 匹配与 id 键（D-044）。
    bridges.sort(key=lambda bridge: (bridge.impl_class, bridge.id))
    return bridges


def _build(draft: _Draft, removals: dict[str, SourceLoc]) -> Bridge:
    """把草稿定形成 `Bridge`（含 revoke 匹配）。"""
    revoke_at = removals.get(draft.name)
    file_line = f"{draft.registered_in.file}:{draft.registered_in.line}"
    return Bridge(
        id=stable_id("bridge", f"{draft.impl_class}|{draft.name}|{file_line}"),
        impl_class=draft.impl_class,
        registered_in=draft.registered_in,
        # v0.1 恒为 all_pages：§5.5 没给区分规则，不臆造（D-044）。
        exposed_to=ExposedTo.ALL_PAGES,
        origin_check=OriginCheck(),  # 由 T2.5 填
        revoked=revoke_at is not None,
        revoke_at=revoke_at,
        methods=sorted(draft.methods, key=lambda m: (m.name, ",".join(m.params))),
        source=draft.registered_in,
    )


def _scan_callsites(index: SmaliIndex) -> tuple[list[_Registration], dict[str, SourceLoc]]:
    """扫全 APK：注册点列表 + `桥名 → 撤销位置`。"""
    registrations: list[_Registration] = []
    removals: dict[str, SourceLoc] = {}

    for descriptor in sorted(index.class_by_descriptor):
        class_info = index.class_by_descriptor[descriptor]
        for method in class_info.methods:
            for instruction in method.instructions:
                site = regflow.parse_invoke(instruction)
                if site is None or site.class_descriptor != WEBVIEW_DESCRIPTOR:
                    continue
                if site.method == ADD_METHOD:
                    registrations.append(
                        _Registration(
                            # addJavascriptInterface(obj, name) → 名字是第二个实参
                            name=_bridge_name(method, site, 1),
                            obj_register=site.value_args[0] if site.value_args else "",
                            site=site,
                            location=_location(method, instruction),
                            method=method,
                        )
                    )
                elif site.method == REMOVE_METHOD:
                    # removeJavascriptInterface(name) → 名字是唯一实参
                    name = _bridge_name(method, site, 0)
                    if name:
                        removals.setdefault(name, _location(method, instruction))
    return registrations, removals


def _bridge_name(method: MethodInfo, site: regflow.InvokeSite, position: int) -> str:
    """取桥名参数的常量字符串（`position` 是除 receiver 之外的实参下标）。

    取不到（不是常量字符串）返回空串，不猜。
    """
    if len(site.value_args) <= position:
        return ""
    const = regflow.backtrack_const_string(method, site.index, site.value_args[position])
    return const[1] if const else ""


def _annotated_classes(index: SmaliIndex) -> dict[str, ClassInfo]:
    """含 `@JavascriptInterface` 方法的类：描述符 → 类。"""
    annotated: dict[str, ClassInfo] = {}
    for descriptor in sorted(index.class_by_descriptor):
        class_info = index.class_by_descriptor[descriptor]
        if any(method.has_annotation(JAVASCRIPT_INTERFACE) for method in class_info.methods):
            annotated[descriptor] = class_info
    return annotated


def _bridge_methods(class_info: ClassInfo | None) -> list[BridgeMethod]:
    """取该类里带 `@JavascriptInterface` 的方法。"""
    if class_info is None:
        return []
    return [
        BridgeMethod(
            name=method.name,
            params=regflow.param_types(method.signature),
            source=method.source,
        )
        for method in class_info.methods
        if method.has_annotation(JAVASCRIPT_INTERFACE)
    ]


def _warn_unregistered(
    annotated: dict[str, ClassInfo], drafts: list[_Draft], warnings: list[str] | None
) -> None:
    """声明了注解但从未注册的类：不产出 Bridge，只记 warning（D-043）。"""
    registered = {draft.impl_class for draft in drafts}
    for descriptor in sorted(annotated):
        name = class_name_of(descriptor)
        if name not in registered:
            _warn(warnings, f"类 {name} 有 @JavascriptInterface 方法但未被注册，不产出桥")


def _warn(warnings: list[str] | None, message: str) -> None:
    """warning 进列表（→ Meta.warnings），同时进日志。"""
    logger.warning(message)
    if warnings is not None:
        warnings.append(message)


def _location(method: MethodInfo, instruction: Instruction) -> SourceLoc:
    """注册点/撤销点的证据位置（file 是相对路径，见 D-036）。"""
    return SourceLoc(
        file=method.source.file,
        line=instruction.file_line,
        snippet=f"{instruction.opcode} {instruction.operands_raw}".strip(),
    )



