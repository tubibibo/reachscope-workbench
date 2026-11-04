"""IR 数据模型（PLAN §4）。

全部为 `@dataclass(frozen=True)`；字段名即 JSON 字段名（唯一例外见 D-013）。
本模块只定义**数据结构**，不含任何判定逻辑——判定在 M3 的 `analyze/` 实现。

字段默认值仅用于方便构造；分析阶段必须显式写入状态，
不允许用空列表 / None 表达“无法判定”（AGENT_BRIEF 硬性禁止）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from .._version import SCHEMA_VERSION
from .serialize import IRSerializable, serialize, stable_id
from .validation import validate_identifiers

#: `SourceLoc.snippet` 的最大长度（PLAN §4.10）。
SNIPPET_MAX_LENGTH = 200

__all__ = [
    "Bridge",
    "BridgeMethod",
    "Chain",
    "Component",
    "ComponentType",
    "CounterEvidence",
    "CounterExample",
    "Deeplink",
    "EntryKind",
    "ExposedTo",
    "Finding",
    "IntentFilter",
    "Judgment",
    "JudgmentResult",
    "Level",
    "Meta",
    "OriginCheck",
    "OriginLocation",
    "OriginStrength",
    "Ownership",
    "Protection",
    "Rank",
    "Report",
    "Sink",
    "SinkKind",
    "SourceLoc",
    "Step",
    "UrlSource",
    "UrlSourceKind",
    "WebView",
    "stable_id",
]


class Level(StrEnum):
    """等级：只用于 `exploitability` / `impact` / `confidence`（PLAN §6.5）。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    def score(self) -> int:
        """排序用的数值：high=3, medium=2, low=1, unknown=0（PLAN §6.5）。"""
        return {"high": 3, "medium": 2, "low": 1, "unknown": 0}[self.value]


class Ownership(StrEnum):
    """数据归属档位（PLAN §5.7 / §6.3 J3），与 `Level` 是两套独立取值。"""

    OWN = "own"
    SHARED = "shared"
    CROSS_APP = "cross-app"
    HIGH = "high"
    UNKNOWN = "unknown"

    def rank(self) -> int:
        """归属的严重程度：high=4, cross-app=3, shared=2, own=1, unknown=0。"""
        return {"high": 4, "cross-app": 3, "shared": 2, "own": 1, "unknown": 0}[self.value]


class JudgmentResult(StrEnum):
    """判据结论（PLAN §6.3，与 T3.3 验收用词一致）。"""

    PASS = "PASS"
    PASS_WITH_NOTE = "PASS_WITH_NOTE"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ComponentType(StrEnum):
    """manifest 组件类型（PLAN §4.4）。"""

    ACTIVITY = "activity"
    ACTIVITY_ALIAS = "activity-alias"
    SERVICE = "service"
    RECEIVER = "receiver"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


class UrlSourceKind(StrEnum):
    """WebView URL 来源类别（PLAN §4.6）。"""

    CONST = "const"
    INTENT_DATA = "intent_data"
    INTENT_EXTRA = "intent_extra"
    DEEPLINK_PARAM = "deeplink_param"
    UNKNOWN = "unknown"


class OriginStrength(StrEnum):
    """来源校验强度（PLAN §5.6）。"""

    NONE = "none"
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class OriginLocation(StrEnum):
    """来源校验所在位置（PLAN §5.6）。"""

    PRE_LOAD = "pre_load"
    BRIDGE_METHOD = "bridge_method"
    SHOULD_OVERRIDE = "should_override"
    PAGE_CALLBACK = "page_callback"
    NONE = "none"

    @property
    def effective(self) -> bool:
        """该位置是否能覆盖首次 `loadUrl`（只有前两档算生效，见 PLAN §5.6）。"""
        return self in (OriginLocation.PRE_LOAD, OriginLocation.BRIDGE_METHOD)


class ExposedTo(StrEnum):
    """桥的暴露范围（PLAN §4.7）。"""

    ALL_PAGES = "all_pages"
    ORIGIN_RESTRICTED = "origin_restricted"


class SinkKind(StrEnum):
    """汇点类别（PLAN §5.7 表格的八类）。"""

    FILE = "file"
    EXTERNAL_STORAGE = "external_storage"
    CONTENT_PROVIDER = "content_provider"
    COMMAND_EXEC = "command_exec"
    CROSS_COMPONENT = "cross_component"
    WEBVIEW = "webview"
    CLIPBOARD = "clipboard"
    RESULT_CALLBACK = "result_callback"
    UNKNOWN = "unknown"


class EntryKind(StrEnum):
    """入口类别（PLAN §6.6 反例的 `entry_kind`）。"""

    DEEPLINK = "deeplink"
    COMPONENT = "component"
    WEBVIEW = "webview"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceLoc(IRSerializable):
    """代码证据位置（PLAN §4.10）。"""

    file: str = ""
    line: int = 0
    snippet: str = ""

    def __post_init__(self) -> None:
        """把 snippet 截断到 200 字符（frozen dataclass 只能这样改写）。"""
        if len(self.snippet) > SNIPPET_MAX_LENGTH:
            object.__setattr__(self, "snippet", self.snippet[:SNIPPET_MAX_LENGTH])


@dataclass(frozen=True)
class Meta(IRSerializable):
    """输入与版本信息（PLAN §4.2，另含 §9.2 要求的 warnings）。"""

    apk_path: str = ""
    apk_sha256: str = ""
    package: str = ""
    version_name: str = ""
    version_code: str = ""
    target_sdk: int | None = None
    min_sdk: int | None = None
    analyzed_at: str = ""
    tool_version: str = ""
    apktool_version: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Protection(IRSerializable):
    """加固 / 混淆状态（PLAN §4.3）。"""

    detected: bool | None = False
    tool: str | None = None
    labels: list[str] = field(default_factory=list)
    analyzable: bool = True
    #: 该检测环节自身的“跳过/降级/未解析”说明，最终合并进 `Meta.warnings`（§9.2）。
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntentFilter(IRSerializable):
    """intent-filter（PLAN §4.4）。"""

    actions: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    schemes: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    path_patterns: list[str] = field(default_factory=list)
    auto_verify: bool = False


@dataclass(frozen=True)
class Component(IRSerializable):
    """manifest 组件（PLAN §4.4）。"""

    name: str = ""
    type: ComponentType = ComponentType.UNKNOWN
    exported: bool = False
    exported_inferred: bool = False
    permission: str | None = None
    permission_protection: str | None = None
    intent_filters: list[IntentFilter] = field(default_factory=list)
    impl_present: bool = True
    impl_reason: str | None = None
    target_activity: str | None = None
    source: SourceLoc | None = None

    @property
    def id(self) -> str:
        """组件稳定 ID（PLAN §9.3）。"""
        return stable_id("component", self.name)


@dataclass(frozen=True)
class Deeplink(IRSerializable):
    """深链入口（PLAN §4.5）。"""

    id: str = ""
    scheme: str = ""
    host: str = ""
    path: str = ""
    auto_verify: bool = False
    component: str = ""
    params: list[str] = field(default_factory=list)
    source: SourceLoc | None = None


@dataclass(frozen=True)
class UrlSource(IRSerializable):
    """WebView 的 URL 来源（PLAN §4.6）。"""

    kind: UrlSourceKind = UrlSourceKind.UNKNOWN
    value: str = ""
    source: SourceLoc | None = None


@dataclass(frozen=True)
class WebView(IRSerializable):
    """WebView 使用点（PLAN §4.6）。

    三个布尔开关用 `bool | None`：None 表示“未观察到设置调用”，
    与 T2.3 的“找不到布尔常量时标 unknown，不猜测”一致（见 D-016）。
    """

    id: str = ""
    owner_class: str = ""
    owner_method: str = ""
    url_sources: list[UrlSource] = field(default_factory=list)
    js_enabled: bool | None = None
    file_access: bool | None = None
    universal_file_access: bool | None = None
    source: SourceLoc | None = None


@dataclass(frozen=True)
class OriginCheck(IRSerializable):
    """来源校验判定（PLAN §4.7 / §5.6）。"""

    present: bool = False
    strength: OriginStrength = OriginStrength.NONE
    kind: str | None = None
    location: OriginLocation = OriginLocation.NONE
    effective: bool = False
    evidence: SourceLoc | None = None
    bypass_reason: str | None = None


@dataclass(frozen=True)
class Sink(IRSerializable):
    """数据汇点（TASKS T2.6：`Sink(kind, ownership, source)`）。"""

    kind: SinkKind = SinkKind.UNKNOWN
    ownership: Ownership = Ownership.UNKNOWN
    source: SourceLoc | None = None


@dataclass(frozen=True)
class BridgeMethod(IRSerializable):
    """带 `@JavascriptInterface` 的桥方法（PLAN §4.7）。"""

    name: str = ""
    params: list[str] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    guarded: bool = False
    source: SourceLoc | None = None


@dataclass(frozen=True)
class Bridge(IRSerializable):
    """JS 桥（PLAN §4.7）。"""

    id: str = ""
    impl_class: str = ""
    registered_in: SourceLoc | None = None
    exposed_to: ExposedTo = ExposedTo.ALL_PAGES
    origin_check: OriginCheck = field(default_factory=OriginCheck)
    revoked: bool = False
    revoke_at: SourceLoc | None = None
    methods: list[BridgeMethod] = field(default_factory=list)
    source: SourceLoc | None = None


@dataclass(frozen=True)
class Step(IRSerializable):
    """链上的一步（PLAN §4.8）。`from` 是保留字，字段名为 `from_`（D-013）。"""

    order: int = 0
    description: str = ""
    from_: str = field(default="", metadata={"alias": "from"})
    to: str = ""
    sink: str = ""
    source: SourceLoc | None = None


@dataclass(frozen=True)
class Judgment(IRSerializable):
    """一条判据的判定结果（PLAN §4.8 / §6.3，字段定义见 D-008）。"""

    name: str = ""
    result: JudgmentResult = JudgmentResult.UNKNOWN
    confidence: Level = Level.UNKNOWN
    reason: str = ""
    source: SourceLoc | None = None
    score_delta: int = 0


@dataclass(frozen=True)
class Rank(IRSerializable):
    """三元组评分（PLAN §6.5），不发明单一分数。"""

    exploitability: Level = Level.UNKNOWN
    impact: Level = Level.UNKNOWN
    confidence: Level = Level.UNKNOWN

    def sort_key(self) -> tuple[int, int, int]:
        """字典序降序排序用的键（high=3 ... unknown=0）。"""
        return (self.exploitability.score(), self.impact.score(), self.confidence.score())


@dataclass(frozen=True)
class Chain(IRSerializable):
    """从入口到汇点的攻击链（PLAN §4.8）。"""

    id: str = ""
    rank: Rank = field(default_factory=Rank)
    entries: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    judgments: list[Judgment] = field(default_factory=list)
    evidence_complete: bool = False


@dataclass(frozen=True)
class CounterEvidence(IRSerializable):
    """一条反向证据（PLAN §4.9 `Finding.counter_evidence`）。"""

    judgment: str = ""
    reason: str = ""
    source: SourceLoc | None = None


@dataclass(frozen=True)
class Finding(IRSerializable):
    """可利用性 ≥ medium 的链（PLAN §4.9）。"""

    chain_id: str = ""
    title: str = ""
    exploitability: Level = Level.UNKNOWN
    impact: Level = Level.UNKNOWN
    confidence: Level = Level.UNKNOWN
    summary: str = ""
    counter_evidence: list[CounterEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class CounterExample(IRSerializable):
    """反例：入口存在但不可利用（PLAN §4.9 / §6.6）。"""

    entry_id: str = ""
    entry_kind: EntryKind = EntryKind.UNKNOWN
    failed_judgment: str = ""
    reason: str = ""
    source: SourceLoc | None = None


@dataclass(frozen=True)
class Report(IRSerializable):
    """报告顶层对象（PLAN §4.1）。"""

    meta: Meta = field(default_factory=Meta)
    protection: Protection = field(default_factory=Protection)
    components: list[Component] = field(default_factory=list)
    deeplinks: list[Deeplink] = field(default_factory=list)
    webviews: list[WebView] = field(default_factory=list)
    bridges: list[Bridge] = field(default_factory=list)
    chains: list[Chain] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    counter_examples: list[CounterExample] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Also runs on from_dict() and normalize_report()'s dataclass copy.
        validate_identifiers(self.components, self.chains)

    def summary(self) -> dict[str, int]:
        """各列表计数（PLAN §8.1 的 summary 块）。"""
        return {
            "components": len(self.components),
            "deeplinks": len(self.deeplinks),
            "webviews": len(self.webviews),
            "bridges": len(self.bridges),
            "chains": len(self.chains),
            "findings": len(self.findings),
            "counter_examples": len(self.counter_examples),
        }

    def to_dict(self) -> dict[str, Any]:
        """`Report` 序列化时附带 `schema_version` 与 `summary`（PLAN §8.1）。"""
        # Frozen dataclasses still contain mutable lists supplied by callers.
        validate_identifiers(self.components, self.chains)
        data = cast("dict[str, Any]", serialize(self))
        data["schema_version"] = SCHEMA_VERSION
        data["summary"] = self.summary()
        return data
