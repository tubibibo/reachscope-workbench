"""WebView 汇点识别（PLAN §5.4 / TASKS T2.3）。

`§5.4` 的 **13 个调用点**（D-040）全部登记在 `CALLSITES`；其中三个回调
（`shouldOverrideUrlLoading` / `onPageStarted` / `onPageFinished`）是**声明**而非调用，
由 `is_callback_method()` 判定，T2.5 用它圈定来源校验的扫描范围。

布尔开关（`js_enabled` 等）只回溯 `const/4`：找不到常量就是 `None`（未知），不猜（D-016）。
回溯规则见 D-045：取 setter 的末位寄存器、只在**同一方法内**回溯、多次设置取最后一次。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from ..graph import regflow
from ..ingest.smali import ClassInfo, Instruction, MethodInfo, SmaliIndex
from ..ir.model import SourceLoc, UrlSource, UrlSourceKind, WebView
from ..ir.serialize import stable_id
from .components import class_name_of

logger = logging.getLogger("reachscope.extract.webview")

WEBVIEW_DESCRIPTOR = "Landroid/webkit/WebView;"
WEB_SETTINGS_DESCRIPTOR = "Landroid/webkit/WebSettings;"
WEBVIEW_CLIENT_DESCRIPTOR = "Landroid/webkit/WebViewClient;"
WEBCHROME_CLIENT_DESCRIPTOR = "Landroid/webkit/WebChromeClient;"

#: 回调所在的框架体系（T2.5 收紧扫描范围用，避免命中外挂的同名业务方法）。
CLIENT_BASE_DESCRIPTORS = (WEBVIEW_CLIENT_DESCRIPTOR, WEBCHROME_CLIENT_DESCRIPTOR)


class CallsiteKind(StrEnum):
    """§5.4 调用点的分类。"""

    LOAD = "load"
    BRIDGE_REGISTER = "bridge_register"
    BRIDGE_REVOKE = "bridge_revoke"
    SETTING_JS = "setting_js"
    SETTING_FILE = "setting_file"
    SETTING_UNIVERSAL_FILE = "setting_universal_file"
    CALLBACK = "callback"


#: §5.4 的 13 个调用点：`(类描述符, 方法名, 签名, 类别)`。
#: 签名留空表示**不限重载**（`loadData` / 回调等的重载不固定）。
CALLSITES: tuple[tuple[str, str, str, CallsiteKind], ...] = (
    (WEBVIEW_DESCRIPTOR, "loadUrl", "(Ljava/lang/String;)V", CallsiteKind.LOAD),
    (WEBVIEW_DESCRIPTOR, "loadUrl", "(Ljava/lang/String;Ljava/util/Map;)V", CallsiteKind.LOAD),
    (WEBVIEW_DESCRIPTOR, "loadData", "", CallsiteKind.LOAD),
    (WEBVIEW_DESCRIPTOR, "loadDataWithBaseURL", "", CallsiteKind.LOAD),
    (WEBVIEW_DESCRIPTOR, "addJavascriptInterface", "", CallsiteKind.BRIDGE_REGISTER),
    (WEBVIEW_DESCRIPTOR, "removeJavascriptInterface", "", CallsiteKind.BRIDGE_REVOKE),
    (WEB_SETTINGS_DESCRIPTOR, "setJavaScriptEnabled", "", CallsiteKind.SETTING_JS),
    (WEB_SETTINGS_DESCRIPTOR, "setAllowFileAccess", "", CallsiteKind.SETTING_FILE),
    (
        WEB_SETTINGS_DESCRIPTOR,
        "setAllowUniversalAccessFromFileURLs",
        "",
        CallsiteKind.SETTING_UNIVERSAL_FILE,
    ),
    (
        WEB_SETTINGS_DESCRIPTOR,
        "setAllowFileAccessFromFileURLs",
        "",
        CallsiteKind.SETTING_UNIVERSAL_FILE,
    ),
    (WEBVIEW_CLIENT_DESCRIPTOR, "shouldOverrideUrlLoading", "", CallsiteKind.CALLBACK),
    (WEBVIEW_CLIENT_DESCRIPTOR, "onPageStarted", "", CallsiteKind.CALLBACK),
    (WEBVIEW_CLIENT_DESCRIPTOR, "onPageFinished", "", CallsiteKind.CALLBACK),
)

#: URL 来源：被调用的方法名 → `UrlSourceKind`（D-041 固定映射）。
SOURCE_METHODS = {
    "getData": UrlSourceKind.INTENT_DATA,
    "getStringExtra": UrlSourceKind.INTENT_EXTRA,
    "getQueryParameter": UrlSourceKind.DEEPLINK_PARAM,
}

#: 派生调用：结果仍来自 receiver，继续沿链回溯（`Uri.toString()` 这类）。
DERIVATION_METHODS = frozenset({"toString", "getPath", "getLastPathSegment", "getQuery"})

#: 三个回调名（T2.5 的扫描入口）。
CALLBACK_NAMES = frozenset(
    name for descriptor, name, _, kind in CALLSITES if kind is CallsiteKind.CALLBACK
)


@dataclass(frozen=True)
class CallsiteMatch:
    """一个被识别的调用点。"""

    kind: CallsiteKind
    site: regflow.InvokeSite


@dataclass
class _OwnerRecord:
    """同一个 `(类, 方法)` 内的 WebView 使用点累积。"""

    owner_class: str
    owner_method: str
    url_sources: list[UrlSource] = field(default_factory=list)
    settings: dict[CallsiteKind, bool | None] = field(default_factory=dict)
    source: SourceLoc | None = None
    has_load: bool = False
    emitted: bool = False

    def build(self) -> WebView:
        """生成 `WebView`（只有出现 loadUrl 或注册桥的方法才算一个 WebView 使用点）。"""
        file_line = f"{self.source.file}:{self.source.line}" if self.source else ""
        return WebView(
            id=stable_id("webview", f"{self.owner_class}|{self.owner_method}|{file_line}"),
            owner_class=self.owner_class,
            owner_method=self.owner_method,
            url_sources=list(self.url_sources),
            js_enabled=self.settings.get(CallsiteKind.SETTING_JS),
            file_access=self.settings.get(CallsiteKind.SETTING_FILE),
            universal_file_access=self.settings.get(CallsiteKind.SETTING_UNIVERSAL_FILE),
            source=self.source,
        )


def extract_webviews(index: SmaliIndex) -> list[WebView]:
    """扫描全 APK，产出 `WebView` 列表（按 `owner_class, owner_method` 排序）。"""
    records: dict[tuple[str, str], _OwnerRecord] = {}
    for descriptor in sorted(index.class_by_descriptor):
        class_info = index.class_by_descriptor[descriptor]
        owner_class = class_name_of(descriptor)
        for method in class_info.methods:
            _collect(records, owner_class, method)

    webviews: list[WebView] = []
    for key in sorted(records):
        record = records[key]
        if record.emitted:
            webviews.append(record.build())
    return webviews


def match_callsite(instruction: Instruction) -> CallsiteMatch | None:
    """指令是否命中 §5.4 的 13 个调用点之一。"""
    site = regflow.parse_invoke(instruction)
    if site is None:
        return None
    for descriptor, name, signature, kind in CALLSITES:
        if site.class_descriptor != descriptor or site.method != name:
            continue
        if signature and site.signature != signature:
            continue
        return CallsiteMatch(kind=kind, site=site)
    return None


def is_callback_method(class_info: ClassInfo, method: MethodInfo, index: SmaliIndex) -> bool:
    """该方法是否是 WebViewClient/WebChromeClient 体系里的三个回调之一（T2.5）。"""
    if method.name not in CALLBACK_NAMES:
        return False
    return has_client_ancestor(class_info, index)


def has_client_ancestor(class_info: ClassInfo, index: SmaliIndex) -> bool:
    """类的 super 链（或自身）是否含 WebViewClient / WebChromeClient。

    框架类（`Landroid/webkit/WebViewClient;`）不在 APK 的 smali 里，
    所以既要比对自身描述符，也要比对**直接父类名**，不能只沿索引里的类往上走。
    """
    current: ClassInfo | None = class_info
    seen: set[str] = set()
    while current is not None and current.descriptor not in seen:
        seen.add(current.descriptor)
        if current.descriptor in CLIENT_BASE_DESCRIPTORS:
            return True
        if current.super_name in CLIENT_BASE_DESCRIPTORS:
            return True
        current = index.get_class(current.super_name) if current.super_name else None
    return False


def classify_url_source(method: MethodInfo, site: regflow.InvokeSite) -> UrlSource:
    """判定 `loadUrl` / `loadData` 的 URL 参数来自哪里（D-041）。

    - `const-string` → `const`（带值）
    - 沿 `move-result*` 链回溯到 `Intent.getData` / `getStringExtra` / `getQueryParameter`
    - 链上有 `toString` 这类派生调用时继续往前走（`getData → toString → loadUrl` 是真实现象）
    - 判不出来 → `unknown`（不猜）
    """
    location = _location(method, site.index)
    register = site.value_args[0] if site.value_args else None
    if register is None:
        return UrlSource(kind=UrlSourceKind.UNKNOWN, source=location)

    const = regflow.backtrack_const_string(method, site.index, register)
    if const is not None:
        return UrlSource(kind=UrlSourceKind.CONST, value=const[1], source=location)

    current_register = register
    current_index = site.index
    for _ in range(regflow.MAX_BACKTRACK_STEPS):
        definition = regflow.backtrack_definition(method, current_index, current_register)
        if definition is None or not definition.opcode.startswith("move-result"):
            break
        invoke = regflow.invoke_before(method, definition.index)
        if invoke is None:
            break
        kind = SOURCE_METHODS.get(invoke.method)
        if kind is not None:
            return UrlSource(kind=kind, source=location)
        if invoke.method in DERIVATION_METHODS and invoke.receiver is not None:
            current_register = invoke.receiver
            current_index = invoke.index
            continue
        break
    return UrlSource(kind=UrlSourceKind.UNKNOWN, source=location)


def _collect(
    records: dict[tuple[str, str], _OwnerRecord], owner_class: str, method: MethodInfo
) -> None:
    """把一个方法里的调用点累积到该 `(类, 方法)` 的记录上。"""
    record: _OwnerRecord | None = None
    for instruction in method.instructions:
        match = match_callsite(instruction)
        if match is None:
            continue
        if record is None:
            key = (owner_class, method.name_with_signature)
            record = records.setdefault(key, _OwnerRecord(owner_class, method.name_with_signature))
        location = _location(method, instruction.index)
        if match.kind is CallsiteKind.LOAD:
            record.url_sources.append(classify_url_source(method, match.site))
            record.emitted = True
            if not record.has_load:
                record.source = location  # 证据位置优先取加载调用（比注册点更能说明用途）
                record.has_load = True
        elif match.kind is CallsiteKind.BRIDGE_REGISTER:
            record.emitted = True
            if record.source is None:
                record.source = location
        elif match.kind in _SETTING_FIELDS:
            register = match.site.value_args[-1] if match.site.value_args else None
            value = (
                regflow.backtrack_const_number(method, match.site.index, register)
                if register
                else None
            )
            # 同方法内多次设置取最后一次（D-045）。
            record.settings[match.kind] = None if value is None else bool(value)


#: 设置类调用点 → 对应的布尔值（同方法内多次设置取最后一次，D-042）。
_SETTING_FIELDS = {
    CallsiteKind.SETTING_JS,
    CallsiteKind.SETTING_FILE,
    CallsiteKind.SETTING_UNIVERSAL_FILE,
}


def _location(method: MethodInfo, index: int) -> SourceLoc:
    """指令位置的证据（file 是相对路径，见 D-036）。"""
    instruction = method.instructions[index] if 0 <= index < len(method.instructions) else None
    return SourceLoc(
        file=method.source.file,
        line=instruction.file_line if instruction else 0,
        snippet=f"{instruction.opcode} {instruction.operands_raw}".strip()
        if instruction
        else "",
    )
