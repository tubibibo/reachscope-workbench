"""数据汇点（PLAN §5.7 / TASKS T2.6）。

八类汇点按 §5.7 的表匹配；数据归属用 `Ownership`（D-011）表达，
**§5.7 表里的 medium ≡ shared**（D-050，三类都表示数据流出 App 私有边界）。

判不出来就是 `unknown`，**绝不默认 own**（会把 impact 静默压低）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from ..graph import regflow
from ..ingest.smali import ClassInfo, MethodInfo, SmaliIndex
from ..ir.model import Bridge, Ownership, Sink, SinkKind, SourceLoc
from .components import descriptor_of

logger = logging.getLogger("reachscope.extract.sinks")

#: `File` 类汇点（归属由方法内的目录信号决定，见 `_file_ownership`）。
FILE_SINKS = {
    ("Ljava/io/FileInputStream;", "<init>"),
    ("Ljava/io/FileOutputStream;", "<init>"),
    ("Ljava/io/FileReader;", "<init>"),
    ("Ljava/io/FileWriter;", "<init>"),
    ("Ljava/io/File;", "<init>"),
}

#: 指向应用私有目录的信号（→ own）。
OWN_DIR_SIGNALS = {
    ("Landroid/content/Context;", "getFilesDir"),
    ("Landroid/content/Context;", "getCacheDir"),
    ("Landroid/content/Context;", "getDir"),
    ("Landroid/content/Context;", "getNoBackupFilesDir"),
    ("Landroid/content/Context;", "getCodeCacheDir"),
}

#: 外部存储（→ shared）。
EXTERNAL_STORAGE_SINKS = {
    ("Landroid/content/Context;", "getExternalFilesDir"),
    ("Landroid/content/Context;", "getExternalCacheDir"),
    ("Landroid/os/Environment;", "getExternalStorageDirectory"),
    ("Landroid/os/Environment;", "getExternalStoragePublicDirectory"),
}

#: 内容提供者（→ cross-app，除非 authority 指向自身）。
CONTENT_PROVIDER_SINKS = {
    ("Landroid/content/ContentResolver;", "query"),
    ("Landroid/content/ContentResolver;", "insert"),
    ("Landroid/content/ContentResolver;", "update"),
    ("Landroid/content/ContentResolver;", "delete"),
    ("Landroid/content/ContentResolver;", "openInputStream"),
    ("Landroid/content/ContentResolver;", "openOutputStream"),
}

#: 命令执行（→ high）。
COMMAND_EXEC_SINKS = {
    ("Ljava/lang/Runtime;", "exec"),
    ("Ljava/lang/ProcessBuilder;", "start"),
    ("Ljava/lang/ProcessBuilder;", "<init>"),
}

#: 跨组件（携带数据时 → shared，即 §5.7 的 medium）。
CROSS_COMPONENT_SINKS = {
    ("Landroid/app/Activity;", "startActivity"),
    ("Landroid/app/Activity;", "startActivityForResult"),
    ("Landroid/app/Activity;", "sendBroadcast"),
    ("Landroid/app/Activity;", "startService"),
    ("Landroid/content/Context;", "startActivity"),
    ("Landroid/content/Context;", "sendBroadcast"),
    ("Landroid/content/Context;", "startService"),
}

#: WebView（→ shared，即 §5.7 的 medium）。
WEBVIEW_SINKS = {
    ("Landroid/webkit/WebView;", "loadUrl"),
    ("Landroid/webkit/WebView;", "loadData"),
    ("Landroid/webkit/WebView;", "loadDataWithBaseURL"),
}

#: 剪贴板（→ shared，即 §5.7 的 medium）。
CLIPBOARD_SINKS = {
    ("Landroid/content/ClipboardManager;", "getPrimaryClip"),
    ("Landroid/content/ClipboardManager;", "setPrimaryClip"),
    ("Landroid/text/ClipboardManager;", "getText"),
    ("Landroid/text/ClipboardManager;", "setText"),
}

#: 回传调用方（携带数据时 → high）。
RESULT_CALLBACK_SINKS = {
    ("Landroid/app/Activity;", "setResult"),
}

#: Intent 携带数据的判定（D-051）：这些调用说明 Intent 里确实带了数据。
INTENT_DATA_METHODS = frozenset({"setData", "setDataAndType"})


def scan_method_sinks(
    method: MethodInfo,
    *,
    own_authorities: frozenset[str] | set[str] = frozenset(),
    package: str = "",
    attacker_controlled_params: bool = False,
) -> list[Sink]:
    """扫描一个方法，产出八类汇点（按指令顺序，同 `(kind, ownership, 行号)` 去重）。

    `attacker_controlled_params=True`：本方法的形参来自攻击者（`@JavascriptInterface`
    方法的 JS 实参）。此时**文件路径直接由形参给出**且没有任何目录信号 ⇒
    路径完全可控（可指向任意位置）→ `cross_app`（D-057）；有私有/外部目录信号时
    仍按信号判，信号优先。
    """
    signals = _ownership_signals(method)
    carries_data = _carries_intent_data(method)
    authority = _content_authority(method)

    sinks: list[Sink] = []
    seen: set[tuple[SinkKind, Ownership, int]] = set()

    for instruction in method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue
        key = (site.class_descriptor, site.method)
        kind = _kind_of(key)
        if kind is None:
            continue
        ownership = _ownership_of(
            kind,
            key,
            signals=signals,
            carries_data=carries_data,
            authority=authority,
            own_authorities=own_authorities,
            package=package,
            path_from_param=(
                attacker_controlled_params
                and kind is SinkKind.FILE
                and _path_is_parameter(site)
            ),
        )
        dedup_key = (kind, ownership, instruction.file_line)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        sinks.append(
            Sink(
                kind=kind,
                ownership=ownership,
                source=SourceLoc(
                    file=method.source.file,
                    line=instruction.file_line,
                    snippet=f"{instruction.opcode} {instruction.operands_raw}".strip(),
                ),
            )
        )
    return sinks


def directory_signal(method: MethodInfo) -> SourceLoc | None:
    """文件归属所依据的目录信号位置（`getCacheDir` 等），没有则 None。

    T3.5 用它把“为什么判 own/shared”钉成链上的一步证据（§6.4 每步都要 SourceLoc）。
    """
    for instruction in method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue
        key = (site.class_descriptor, site.method)
        if key in OWN_DIR_SIGNALS or key in EXTERNAL_STORAGE_SINKS:
            return SourceLoc(
                file=method.source.file,
                line=instruction.file_line,
                snippet=f"{instruction.opcode} {instruction.operands_raw}".strip(),
            )
    return None


def attach_bridge_sinks(
    bridges: list[Bridge],
    index: SmaliIndex,
    *,
    own_authorities: frozenset[str] | set[str] = frozenset(),
    package: str = "",
) -> list[Bridge]:
    """把汇点回填到每个桥方法（T2.4 阶段 `sinks` 留空，见 D-044）。"""
    updated: list[Bridge] = []
    for bridge in bridges:
        class_info = index.get_class(descriptor_of(bridge.impl_class))
        methods = []
        for method in bridge.methods:
            impl = _find_method(class_info, method.name) if class_info else None
            sinks = (
                scan_method_sinks(
                    impl,
                    own_authorities=own_authorities,
                    package=package,
                    # 桥方法的形参就是页面 JS 的实参 → 攻击者可控（D-057）
                    attacker_controlled_params=True,
                )
                if impl is not None
                else []
            )
            methods.append(replace(method, sinks=sinks))
        updated.append(replace(bridge, methods=methods))
    return updated


def _kind_of(key: tuple[str, str]) -> SinkKind | None:
    """`(类描述符, 方法名)` → 汇点类别。"""
    if key in FILE_SINKS:
        return SinkKind.FILE
    if key in EXTERNAL_STORAGE_SINKS:
        return SinkKind.EXTERNAL_STORAGE
    if key in CONTENT_PROVIDER_SINKS:
        return SinkKind.CONTENT_PROVIDER
    if key in COMMAND_EXEC_SINKS:
        return SinkKind.COMMAND_EXEC
    if key in CROSS_COMPONENT_SINKS:
        return SinkKind.CROSS_COMPONENT
    if key in WEBVIEW_SINKS:
        return SinkKind.WEBVIEW
    if key in CLIPBOARD_SINKS:
        return SinkKind.CLIPBOARD
    if key in RESULT_CALLBACK_SINKS:
        return SinkKind.RESULT_CALLBACK
    return None


def _ownership_of(
    kind: SinkKind,
    key: tuple[str, str],
    *,
    signals: set[str],
    carries_data: bool,
    authority: str,
    own_authorities: frozenset[str] | set[str],
    package: str,
    path_from_param: bool = False,
) -> Ownership:
    """数据归属判定（D-050 / D-051 / D-057）。"""
    del key
    if kind is SinkKind.COMMAND_EXEC:
        return Ownership.HIGH
    if kind is SinkKind.EXTERNAL_STORAGE:
        return Ownership.SHARED
    if kind is SinkKind.FILE:
        return _file_ownership(signals, path_from_param=path_from_param)
    if kind is SinkKind.CONTENT_PROVIDER:
        return _provider_ownership(authority, own_authorities, package)
    if kind is SinkKind.RESULT_CALLBACK:
        # high 会直接推高 impact，没确认携带数据时宁可 unknown（D-051）。
        return Ownership.HIGH if carries_data else Ownership.UNKNOWN
    if kind in (SinkKind.CROSS_COMPONENT, SinkKind.WEBVIEW, SinkKind.CLIPBOARD):
        # §5.7 的 medium ≡ shared（D-050）；跨组件未确认携带数据 → unknown，不冒充 shared。
        if kind is SinkKind.CROSS_COMPONENT and not carries_data:
            return Ownership.UNKNOWN
        return Ownership.SHARED
    return Ownership.UNKNOWN


def _file_ownership(signals: set[str], *, path_from_param: bool = False) -> Ownership:
    """文件路径的归属（D-051 / D-057）。

    1. 私有目录信号（`getCacheDir` 等）→ own
    2. 外部存储信号 → shared
    3. 路径**直接来自攻击者可控形参**（JS 桥方法的实参）→ cross-app：路径完全可控，
       可指向应用私有目录之外
    4. 都没有 → unknown（不默认 own）
    """
    if "own" in signals:
        return Ownership.OWN
    if "external" in signals:
        return Ownership.SHARED
    if path_from_param:
        return Ownership.CROSS_APP
    return Ownership.UNKNOWN


#: 形参寄存器（`p1`、`p2`……；`p0` 是 `this`，不算攻击者输入）。
_PARAM_REGISTER = re.compile(r"p[1-9]\d*")


def _path_is_parameter(site: regflow.InvokeSite) -> bool:
    """`File` 系构造的路径实参是否直接是方法形参（未与任何目录拼接）。"""
    return any(_PARAM_REGISTER.fullmatch(arg) for arg in site.value_args)


def _provider_ownership(
    authority: str, own_authorities: frozenset[str] | set[str], package: str
) -> Ownership:
    """内容提供者：authority 指向自身 → own；解析不出来 → 保守 cross-app（D-051）。"""
    if not authority:
        return Ownership.CROSS_APP
    if authority in own_authorities:
        return Ownership.OWN
    if package and (authority == package or authority.startswith(f"{package}.")):
        return Ownership.OWN
    return Ownership.CROSS_APP


def _ownership_signals(method: MethodInfo) -> set[str]:
    """方法内出现过的目录归属信号。"""
    signals: set[str] = set()
    for instruction in method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue
        key = (site.class_descriptor, site.method)
        if key in OWN_DIR_SIGNALS:
            signals.add("own")
        elif key in EXTERNAL_STORAGE_SINKS:
            signals.add("external")
    return signals


def _carries_intent_data(method: MethodInfo) -> bool:
    """方法内是否有证据表明 Intent 携带数据（`putExtra*` / `setData`）。"""
    for instruction in method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is None or site.class_descriptor != "Landroid/content/Intent;":
            continue
        if site.method in INTENT_DATA_METHODS or site.method.startswith("put"):
            return True
    return False


def _content_authority(method: MethodInfo) -> str:
    """从方法内的 `content://` 常量里取 authority；取不到返回空串。"""
    for instruction in method.instructions:
        const = regflow.parse_const_string(instruction)
        if const is None:
            continue
        value = const[1]
        if not value.startswith("content://"):
            continue
        rest = value.removeprefix("content://")
        return rest.split("/", 1)[0].split("?", 1)[0]
    return ""


def _find_method(class_info: ClassInfo | None, name: str) -> MethodInfo | None:
    """按方法名找实现（签名未必完全对齐，取第一个同名）。"""
    if class_info is None:
        return None
    for method in class_info.methods:
        if method.name == name:
            return method
    return None
