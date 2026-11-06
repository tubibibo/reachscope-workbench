"""判据 J1 / J2 / J3 / J4 / J5（PLAN §6.3 / TASKS T3.3 / T3.4）。

每条判据都是**纯函数**：`Component` / `ManifestInfo` / `SmaliIndex` / `list[Sink]` /
`(Bridge, WebView)` / `MethodInfo` → `Judgment`（带 SourceLoc + confidence + score_delta）。
J6 / 评分在 T3.6 加入。

理由字符串（`reason`）按 §6.3 原文：

- J1 / FAIL：`not exported` / `signature-level permission`
- J1 / PASS_WITH_NOTE：`requires {prot} permission; third-party app can request it`
- J1 / UNKNOWN：`permission protection level unresolved`
- J1 / PASS（无 permission）：`no permission required`
- J2 / FAIL：`implementation class not found in APK` / `no concrete implementation`
- J3 / 当所有 sink 都是 own：`all sinks stay within own boundary`
- J4 / not applicable：`page not attacker-controllable`（4b=false）
- J4 / short circuit：`blocked by strong origin check covering first load`
"""

from __future__ import annotations

from dataclasses import dataclass

from ..extract.components import descriptor_of, has_concrete_implementation
from ..graph import regflow
from ..ingest.smali import Instruction, MethodInfo, SmaliIndex
from ..ir.model import (
    Bridge,
    Component,
    ComponentType,
    Judgment,
    JudgmentResult,
    Level,
    OriginStrength,
    Ownership,
    Sink,
    SourceLoc,
    UrlSourceKind,
    WebView,
)

#: `Ownership` → 风险等级（§6.3 J3）。
OWNERSHIP_TO_LEVEL: dict[Ownership, Level] = {
    Ownership.OWN: Level.LOW,
    Ownership.SHARED: Level.MEDIUM,
    Ownership.CROSS_APP: Level.HIGH,
    Ownership.HIGH: Level.HIGH,
    Ownership.UNKNOWN: Level.LOW,  # unknown 在没有 worse 的情况下按 low；不能冒充 high
}


def j1(component: Component) -> Judgment:
    """零特权可达性（§6.3 J1）。"""
    if not component.exported:
        if component.exported_inferred:
            return _judgment(
                "J1", JudgmentResult.UNKNOWN, Level.MEDIUM,
                "not exported (inferred; no explicit android:exported)", component.source,
            )
        return _judgment(
            "J1", JudgmentResult.FAIL, Level.HIGH, "not exported", component.source,
        )
    if not component.permission:
        return _judgment(
            "J1", JudgmentResult.PASS, Level.HIGH, "no permission required", component.source,
        )
    prot = component.permission_protection or "unknown"
    if "signature" in prot:
        return _judgment(
            "J1", JudgmentResult.FAIL, Level.HIGH, "signature-level permission", component.source,
        )
    if prot in ("normal", "dangerous"):
        return _judgment(
            "J1",
            JudgmentResult.PASS_WITH_NOTE,
            Level.MEDIUM,
            f"requires {prot} permission; third-party app can request it",
            component.source,
        )
    return _judgment(
        "J1",
        JudgmentResult.UNKNOWN,
        Level.LOW,
        "permission protection level unresolved",
        component.source,
    )


def j2(component: Component, index: SmaliIndex | None) -> Judgment:
    """实现真实性（§6.3 J2）。"""
    if not component.impl_present:
        return _judgment(
            "J2",
            JudgmentResult.FAIL,
            Level.HIGH,
            "implementation class not found in APK",
            component.source,
        )
    if index is not None and component.type is not ComponentType.ACTIVITY_ALIAS:
        descriptor = descriptor_of(component.name)
        class_info = index.get_class(descriptor)
        if class_info is not None and (class_info.is_abstract or class_info.is_interface) and not has_concrete_implementation(component.name, index):
            return _judgment(
                "J2",
                JudgmentResult.FAIL,
                Level.HIGH,
                "no concrete implementation",
                component.source,
            )
    return _judgment(
        "J2", JudgmentResult.PASS, Level.HIGH, "implementation present", component.source,
    )


def j3(sinks: list[Sink]) -> tuple[Judgment, Ownership]:
    """数据归属（§6.3 J3）。返回 `(判定, 最高档 Ownership)`。"""
    if not sinks:
        # 显式无 sink = 没把数据送出私有边界 → 当 low；不冒充“已高危”
        return (
            _judgment(
                "J3",
                JudgmentResult.UNKNOWN,
                Level.LOW,
                "no sinks to classify",
            ),
            Ownership.UNKNOWN,
        )
    highest = max(sinks, key=lambda sink: sink.ownership.rank()).ownership
    level = OWNERSHIP_TO_LEVEL[highest]
    if highest is Ownership.OWN:
        reason = "all sinks stay within own boundary"
    else:
        reason = f"max sink ownership: {highest.value}; impact={level.value}"
    return _judgment("J3", JudgmentResult.PASS, Level.HIGH, reason), highest


def _judgment(
    name: str,
    result: JudgmentResult,
    confidence: Level,
    reason: str,
    source: SourceLoc | None = None,
) -> Judgment:
    """构造一条 `Judgment`（J1/J2/J3 都不参与 §6.3 的 score_delta，恒 0）。"""
    return Judgment(
        name=name,
        result=result,
        confidence=confidence,
        reason=reason,
        source=source,
        score_delta=0,
    )


__all__ = [
    "ENTRY_METHOD_NAMES",
    "JAVASCRIPT_INTERFACE",
    "OWNERSHIP_TO_LEVEL",
    "J5Hit",
    "bridge_method_refs",
    "is_entry_method",
    "j1",
    "j2",
    "j3",
    "j4",
    "j5",
]


# --- J4：WebView 桥暴露面（§6.3） ------------------------------------------


#: 4b：可被攻击者控制的 URL 来源类别。
ATTACKER_CONTROLLED_URL_KINDS = (
    UrlSourceKind.INTENT_DATA,
    UrlSourceKind.INTENT_EXTRA,
    UrlSourceKind.DEEPLINK_PARAM,
)


def j4(bridge: Bridge, webview: WebView) -> tuple[list[Judgment], Level]:
    """J4 算式（§6.3）→ 返回 6 条 Judgment（每条带 SourceLoc 和 score_delta） + exploitability。

    - 没有桥 → 返回 1 条 "J4 not applicable"
    - 4b=false → 1 条 "page not attacker-controllable"，exploitability=low
    - 强校验 + effective → 1 条 "blocked by strong origin check"，exploitability=low
      （**短路在 base 累加之前**，不写 6 条；用户硬要求）
    - 其它 → 6 条（base +2 / origin / effective / revoked / file_access / high-sink），
      score → exploitability：≥5=high，≥3=medium，否则 low
    """
    if not bridge.id:
        return [_judgment("J4", JudgmentResult.UNKNOWN, Level.LOW, "no bridge in chain")], Level.LOW

    is_4b = any(source.kind in ATTACKER_CONTROLLED_URL_KINDS for source in webview.url_sources)
    if not is_4b:
        return (
            [_judgment(
                "J4",
                JudgmentResult.PASS,
                Level.HIGH,
                "page not attacker-controllable",
                webview.source,
            )],
            Level.LOW,
        )

    origin = bridge.origin_check
    if origin.strength is OriginStrength.STRONG and origin.effective:
        return (
            [_judgment(
                "J4",
                JudgmentResult.PASS,
                Level.HIGH,
                "blocked by strong origin check covering first load",
                origin.evidence or webview.source,
            )],
            Level.LOW,
        )

    # 6 条累加：base / origin / effective / revoked / file / high-sink
    has_file = bool(webview.file_access or webview.universal_file_access)
    # §6.3「任一桥方法含 high 级 sink」= 数据归属为 high 或 cross-app：
    # 命令执行是 high；任意路径文件读写 / 指向他人的 provider 是 cross-app，
    # 后果同样是高影响（case 01/04 的验收要求）。own/shared/unknown 不计。
    high_sink = any(
        method.sinks
        and any(s.ownership in (Ownership.HIGH, Ownership.CROSS_APP) for s in method.sinks)
        for method in bridge.methods
    )

    items: list[Judgment] = [
        _scored("J4", 2, "external page + bridge exposed to all pages (base +2)", webview.source),
        _scored(
            "J4",
            0 if origin.strength is OriginStrength.STRONG else 1,
            f"origin check strength = {origin.strength.value}"
            + ("" if origin.strength is OriginStrength.STRONG else " (+1)"),
            origin.evidence or webview.source,
        ),
        _scored(
            "J4",
            0 if origin.effective else 1,
            f"origin check effective = {origin.effective}"
            + ("" if origin.effective else " (+1)"),
            origin.evidence or webview.source,
        ),
        _scored(
            "J4",
            0 if bridge.revoked else 1,
            f"bridge revoked = {bridge.revoked}" + ("" if bridge.revoked else " (+1)"),
            bridge.source or webview.source,
        ),
        _scored(
            "J4",
            1 if has_file else 0,
            f"file_access = {webview.file_access}, universal = {webview.universal_file_access}"
            + (" (+1)" if has_file else ""),
            webview.source,
        ),
        _scored(
            "J4",
            1 if high_sink else 0,
            "bridge method exposes high-impact sink (+1)" if high_sink else "no high-impact sink",
            bridge.source or webview.source,
        ),
    ]
    score = sum(item.score_delta for item in items)
    if score >= 5:
        return items, Level.HIGH
    if score >= 3:
        return items, Level.MEDIUM
    return items, Level.LOW


def _scored(name: str, delta: int, reason: str, source: SourceLoc | None) -> Judgment:
    """J4 的累加项：`result` 统一 PASS（已计入打分），`score_delta` 是这一项的贡献。"""
    return Judgment(
        name=name,
        result=JudgmentResult.PASS,
        confidence=Level.HIGH,
        reason=reason,
        source=source,
        score_delta=delta,
    )


# --- J5：深链直灌（§6.3） ----------------------------------------------


#: @JavascriptInterface 的全限定名（T2.4 也用同一个常量）。
JAVASCRIPT_INTERFACE = "Landroid/webkit/JavascriptInterface;"

#: §6.3 J5 的入口方法名集合（M1：按组件类型取子集，删掉“全集”过近似）。
#:
#: - Activity：`onCreate` / `onNewIntent` / `onStart` / `onResume`
#: - Service：`onCreate` / `onStartCommand` / `onBind` / `onStart`（旧 API）/
#:   `onHandleIntent`（IntentService）
#: - Receiver：`onReceive`
#: - Provider：`query` / `call` / `openFile`
#:
#: 非组件类型或未知类型 → 退回全集（不因此漏掉入口）。
ENTRY_METHODS_BY_TYPE: dict[ComponentType, frozenset[str]] = {
    ComponentType.ACTIVITY: frozenset({"onCreate", "onNewIntent", "onStart", "onResume"}),
    ComponentType.ACTIVITY_ALIAS: frozenset(
        {"onCreate", "onNewIntent", "onStart", "onResume"}
    ),
    ComponentType.SERVICE: frozenset(
        {"onCreate", "onStartCommand", "onBind", "onStart", "onHandleIntent"}
    ),
    ComponentType.RECEIVER: frozenset({"onReceive"}),
    ComponentType.PROVIDER: frozenset({"query", "call", "openFile"}),
}

ENTRY_METHOD_NAMES: frozenset[str] = frozenset(
    name for names in ENTRY_METHODS_BY_TYPE.values() for name in names
)


def is_entry_method(name: str, component_type: ComponentType | None = None) -> bool:
    """入口方法名（§6.3 J5 起点）判定；给了组件类型就按该类型的子集判。"""
    if component_type is None:
        return name in ENTRY_METHOD_NAMES
    names = ENTRY_METHODS_BY_TYPE.get(component_type)
    if names is None:
        return name in ENTRY_METHOD_NAMES
    return name in names


#: J5 视作"注入 sink"的调用点：WebView 加载。
_LOAD_SINKS: frozenset[tuple[str, str]] = frozenset({
    ("Landroid/webkit/WebView;", "loadUrl"),
    ("Landroid/webkit/WebView;", "loadData"),
    ("Landroid/webkit/WebView;", "loadDataWithBaseURL"),
})

#: J5 视作"注入 sink"的调用点：写文件 / 共享首选项。
_FILE_SINKS: frozenset[tuple[str, str]] = frozenset({
    ("Ljava/io/File;", "<init>"),
    ("Ljava/io/FileOutputStream;", "<init>"),
    ("Landroid/content/Context;", "openFileOutput"),
    ("Landroid/content/Context;", "getSharedPreferences"),
})


@dataclass(frozen=True)
class J5Hit:
    """J5 一次"attacker-controlled 标签流入 sink"的命中（§6.3 / T3.4）。

    字段：
    - `source`：调用点的 `SourceLoc`（相对路径 + 行号 + 指令 snippet）
    - `sink_kind`：`"webview" | "bridge" | "file"`，区分是 loadUrl / 桥方法 / 文件路径
    - `site`：原始 `InvokeSite`，T3.5 / T3.6 用来匹配桥方法或还原调用签名
    - `tags`：命中实参上的攻击者标签（M1：跨组件 join 用它匹配 key/载体）
    """

    source: SourceLoc
    sink_kind: str
    site: regflow.InvokeSite
    tags: tuple[regflow.Tag, ...] = ()

    @property
    def extra_keys(self) -> frozenset[str]:
        """命中的 `Intent.get*Extra(key)` 已知 key（空串表示 key 不可判定）。"""
        return frozenset(
            tag.value
            for tag in self.tags
            if tag.kind is regflow.TagKind.INTENT_EXTRA and tag.value
        )

    @property
    def has_unknown_extra_key(self) -> bool:
        return any(
            tag.kind is regflow.TagKind.INTENT_EXTRA and not tag.value
            for tag in self.tags
        )

    @property
    def reads_data(self) -> bool:
        """是否读取了 `Intent.getData*()`（URI 载体）。"""
        return any(tag.kind is regflow.TagKind.INTENT_DATA for tag in self.tags)

    @property
    def reads_deeplink_param(self) -> bool:
        """是否读取了 `Uri.getQueryParameter`（可能来自 data，也可能来自 extra）。"""
        return any(tag.kind is regflow.TagKind.DEEPLINK_PARAM for tag in self.tags)

    @property
    def deeplink_origins(self) -> frozenset[str]:
        """`getQueryParameter` 的 Uri 来源（`data` / `extra`），由 tag.owner 携带。"""
        return frozenset(
            tag.owner
            for tag in self.tags
            if tag.kind is regflow.TagKind.DEEPLINK_PARAM and tag.owner
        )


def bridge_method_refs(index: SmaliIndex) -> set[tuple[str, str, str]]:
    """`(class_descriptor, method_name, signature)` 集合：所有 @JavascriptInterface 方法。

    🔴 这是一次**全索引扫描**（O(类 × 方法)）。调用方必须只算一次再传给 `j5`：
    在 DuckDuckGo 这类大包上，每个入口方法各扫一遍全索引会把分析时间打进小时级。
    """
    refs: set[tuple[str, str, str]] = set()
    for class_info in index.class_by_descriptor.values():
        for method in class_info.methods:
            if method.has_annotation(JAVASCRIPT_INTERFACE):
                refs.add((class_info.descriptor, method.name, method.signature))
    return refs


def j5(
    entry_method: MethodInfo,
    index: SmaliIndex,
    *,
    package: str = "",
    bridge_refs: set[tuple[str, str, str]] | None = None,
    require_entry_method: bool = True,
    initial: dict[str, regflow.Tag] | None = None,
    component_type: ComponentType | None = None,
) -> list[J5Hit]:
    """J5：入口方法内 attacker-controlled 标签**所有**直灌 sink 的调用点（§6.3 / T3.4 / T3.6）。

    返回**全部命中**而不是第一个——T3.6 期望一条链里能同时出现
    `loadUrl`（暴露 WebView）和 `bridge → file sink`（被 @JavascriptInterface
    方法的内部 sink），所以多 hit 必须共存于一条 `Chain`。
    判不出 / 不在入口方法集合 → 空列表（不冒充"否"）。

    `require_entry_method=False`：调用方已经把"从入口方法出发、深度 ≤ 4"算好了
    （§6.4 第 3 步），这里分析的是**可达的 callee**。callee 的方法名自然不是
    `onCreate` 之类，入口闸门必须关掉，否则深度 4 的可达集永远产不出链（D-064）。

    `initial`：调用方沿调用路径算出的形参标签（M1 过程间污点）；`None` 走
    `regflow` 的保守默认。`component_type`：入口方法按组件类型取子集（M1）。
    """
    if require_entry_method and not is_entry_method(entry_method.name, component_type):
        return []
    flows = regflow.propagate(entry_method, smali=index, initial=initial)
    if bridge_refs is None:
        bridge_refs = bridge_method_refs(index)
    hits: list[J5Hit] = []
    for instruction in entry_method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue
        is_load = (site.class_descriptor, site.method) in _LOAD_SINKS
        is_bridge = (site.class_descriptor, site.method, site.signature) in bridge_refs
        is_file = (site.class_descriptor, site.method) in _FILE_SINKS
        if not (is_load or is_bridge or is_file):
            continue
        tainted = tuple(
            tag
            for register in site.value_args
            if register and (tag := flows.tag_of(register)).attacker_controlled
        )
        if tainted:
            sink_kind = "webview" if is_load else "bridge" if is_bridge else "file"
            hits.append(
                J5Hit(
                    source=_instruction_loc(entry_method, instruction),
                    sink_kind=sink_kind,
                    site=site,
                    tags=tainted,
                )
            )
    return hits


def _instruction_loc(method: MethodInfo, instruction: Instruction) -> SourceLoc:
    """调用位置的证据（§4.10 相对路径）。"""
    snippet = f"{instruction.opcode} {instruction.operands_raw}".strip()
    if len(snippet) > 200:
        snippet = snippet[:200]
    return SourceLoc(file=method.source.file, line=instruction.file_line, snippet=snippet)
