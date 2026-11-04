"""组件与实现存在性（PLAN §5.1 / TASKS T2.1）。

两件事：
1. **类名规范化**：manifest 里的 `.MainActivity` 与 `MainActivity` 都必须展开成
   `<package>.MainActivity` 再进 IR —— `Deeplink.component` 复用**同一个**函数，
   `stable_id` 才稳定（用户硬要求，见 D-034）。
2. **实现存在性**：`impl_present` 与失败理由 `impl_reason`（J2 的证据）。
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ..ingest.manifest import ManifestInfo
from ..ingest.smali import ClassInfo, SmaliIndex
from ..ir.model import Component, ComponentType

logger = logging.getLogger("reachscope.extract.components")

#: J2 的两种失败理由，与 PLAN §6.3 用词**逐字一致**（D-032）；
#: 只在 `impl_present=False` 时非空。
REASON_NOT_FOUND = "implementation class not found in APK"
REASON_NO_CONCRETE = "no concrete implementation"


def normalize_class_name(name: str, package: str) -> str:
    """把 manifest 里的类名展开成全限定名（D-034）。

    | 输入                 | package            | 输出                     |
    |----------------------|--------------------|--------------------------|
    | `.MainActivity`      | `com.example.app`  | `com.example.app.MainActivity` |
    | `MainActivity`       | `com.example.app`  | `com.example.app.MainActivity` |
    | `com.other.Foo`      | `com.example.app`  | `com.example.app` 下原样 `com.other.Foo` |
    | `.Outer$Inner`       | `com.example.app`  | `com.example.app.Outer$Inner` |

    `package` 为空时无法规范化，原样返回（调用方负责记 warning，不猜）。
    """
    text = name.strip()
    if not text or not package:
        return text
    if text.startswith("."):
        return f"{package}{text}"
    if "." in text:
        return text  # 已是全限定名（可能是别的包）
    return f"{package}.{text}"


def descriptor_of(class_name: str) -> str:
    """点分类名 → smali 描述符（`com.a.B` → `Lcom/a/B;`）。"""
    return f"L{class_name.replace('.', '/')};"


def class_name_of(descriptor: str) -> str:
    """smali 描述符 → 点分类名（`Lcom/a/B;` → `com.a.B`）。"""
    text = descriptor.removeprefix("L").removesuffix(";")
    return text.replace("/", ".")


def resolve_components(manifest_info: ManifestInfo, index: SmaliIndex) -> list[Component]:
    """规范化组件名并回填 `impl_present` / `impl_reason`。

    `activity-alias` 用 `android:targetActivity` 查实现（别名自身在 APK 里没有类，
    否则每条 alias 都会被误判成悬空声明 —— D-032b）。
    warning 追加到 `manifest_info.warnings`（最终进 `Meta.warnings`，§9.2）。
    """
    subclass_map = _subclass_map(index)
    resolved: list[Component] = []

    for component in manifest_info.components:
        name = normalize_class_name(component.name, manifest_info.package)
        target: str | None = None
        if component.type is ComponentType.ACTIVITY_ALIAS:
            raw_target = component.target_activity
            if raw_target:
                target = normalize_class_name(raw_target, manifest_info.package)
            else:
                message = (
                    f"activity-alias {name} 未声明 android:targetActivity，"
                    "按别名自身名查找实现"
                )
                logger.warning(message)
                manifest_info.warnings.append(message)

        impl_present, reason = _impl_status(target or name, index, subclass_map)
        resolved.append(
            replace(
                component,
                name=name,
                target_activity=target,
                impl_present=impl_present,
                impl_reason=reason,
            )
        )
    return resolved


def has_concrete_implementation(class_name: str, index: SmaliIndex) -> bool:
    """该类是否有具体实现（自身具体，或存在具体子类 / 实现类）。"""
    return _impl_status(class_name, index, _subclass_map(index))[0]


def _impl_status(
    class_name: str, index: SmaliIndex, subclass_map: dict[str, list[str]]
) -> tuple[bool, str | None]:
    """判定实现存在性，返回 `(impl_present, impl_reason)`。"""
    descriptor = descriptor_of(class_name)
    class_info = index.get_class(descriptor)
    if class_info is None:
        return False, REASON_NOT_FOUND
    if _is_concrete(class_info):
        return True, None
    if _has_concrete_subclass(descriptor, index, subclass_map):
        return True, None
    return False, REASON_NO_CONCRETE


def _is_concrete(class_info: ClassInfo) -> bool:
    """具体 = 既不是 interface 也不是 abstract。"""
    return not class_info.is_interface and not class_info.is_abstract


def _subclass_map(index: SmaliIndex) -> dict[str, list[str]]:
    """父类/接口描述符 → 直接子类描述符列表（多 dex 已合并）。"""
    mapping: dict[str, list[str]] = {}
    for descriptor, class_info in index.class_by_descriptor.items():
        parents = [class_info.super_name, *class_info.interfaces]
        for parent in parents:
            if parent:
                mapping.setdefault(parent, []).append(descriptor)
    return mapping


def _has_concrete_subclass(
    descriptor: str, index: SmaliIndex, subclass_map: dict[str, list[str]]
) -> bool:
    """沿子类边做传递闭包搜索是否存在具体类（带 visited 防环，D-033）。"""
    pending = list(subclass_map.get(descriptor, ()))
    visited = {descriptor}
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        class_info = index.get_class(current)
        if class_info is None:
            continue
        if _is_concrete(class_info):
            return True
        pending.extend(subclass_map.get(current, ()))
    return False
