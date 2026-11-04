"""深链提取（PLAN §5.8 / TASKS T2.2）。

只认 `VIEW + BROWSABLE` 的 intent-filter；`scheme` 支持 http/https 与任意自定义
scheme（如 `myapp`）。`component` 用 `normalize_class_name()`（D-034），
保证与 `Component.name` 一致、`stable_id` 稳定。
"""

from __future__ import annotations

from itertools import product

from ..ir.model import Component, Deeplink, SourceLoc
from ..ir.serialize import stable_id
from .components import normalize_class_name

#: 深链入口的两个必要条件（PLAN §5.8）。
VIEW_ACTION = "android.intent.action.VIEW"
BROWSABLE_CATEGORY = "android.intent.category.BROWSABLE"
MAX_DEEPLINKS = 2000


def extract_deeplinks(components: list[Component], package: str) -> list[Deeplink]:
    """把组件的 intent-filter 展开成深链列表。

    - 缺 `VIEW` 或缺 `BROWSABLE` → 该 filter 不产出深链
    - 缺 `scheme` → 不产出（无法构造 URL，不默认 http，D-038）
    - `paths`（含 pathPrefix，见 D-023）与 `path_patterns` **各元素各一条**，
      `path_patterns` 原样保留（通配语义不能当字面量）；两者都空 → `path=""`
    - 同一 filter 的 data 属性合并，按 scheme × host × path 展开声明候选
    - 整份输入最多保留 MAX_DEEPLINKS 条；清单解析阶段记录覆盖预算警告
    - 结果按 `(component, scheme, host, path)` 排序，保证 §9.3 确定性
    """
    deeplinks: list[Deeplink] = []
    seen: set[str] = set()

    for component in components:
        name = normalize_class_name(component.name, package)
        for filter_ in component.intent_filters:
            if VIEW_ACTION not in filter_.actions:
                continue
            if BROWSABLE_CATEGORY not in filter_.categories:
                continue
            if not filter_.schemes:
                continue
            # Without a host Android ignores paths. Keep declaration candidates,
            # not concrete URLs or proof of App Links domain verification.
            hosts = filter_.hosts or [""]
            paths = ([*filter_.paths, *filter_.path_patterns] or [""]) if filter_.hosts else [""]
            for scheme, host, path in product(filter_.schemes, hosts, paths):
                if len(deeplinks) >= MAX_DEEPLINKS:
                    deeplinks.sort(key=lambda item: (item.component, item.scheme, item.host, item.path))
                    return deeplinks
                deeplink = Deeplink(
                    id=stable_id("deeplink", f"{name}|{scheme}://{host}{path}"),
                    scheme=scheme,
                    host=host,
                    path=path,
                    auto_verify=filter_.auto_verify,
                    component=name,
                    params=[],
                    # manifest 证据沿用组件自身的 SourceLoc（行号 0，见 D-024）。
                    source=_component_source(component),
                )
                if deeplink.id in seen:
                    continue
                seen.add(deeplink.id)
                deeplinks.append(deeplink)

    deeplinks.sort(key=lambda item: (item.component, item.scheme, item.host, item.path))
    return deeplinks


def _component_source(component: Component) -> SourceLoc | None:
    """深链的证据位置 = 组件在 manifest 里的位置。"""
    return component.source
