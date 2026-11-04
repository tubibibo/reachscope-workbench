"""核心数据模型。

全部为纯 dataclass：不引入 pydantic，序列化集中在 writers 层，
保证模型层零框架依赖（Phase 2 被 MCP / Agent 复用时不带包袱）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 常见端口 → 协议/服务面。分类引擎会用到，故放在模型层统一。
PORT_PROTOCOL: dict[str, str] = {
    "80": "http",
    "443": "https",
    "8080": "http",
    "8443": "https",
    "8000": "http",
    "8888": "http",
    "3000": "http",
    "5000": "http",
    "9200": "elasticsearch",
    "6379": "redis",
    "3306": "mysql",
    "5432": "postgresql",
    "27017": "mongodb",
    "2375": "docker",
    "2379": "etcd",
    "11211": "memcached",
    "21": "ftp",
    "22": "ssh",
    "23": "telnet",
    "25": "smtp",
    "445": "smb",
    "1433": "mssql",
    "1521": "oracle",
    "3389": "rdp",
    "5900": "vnc",
}


def guess_protocol(port: str | int) -> str:
    """按端口推断协议。未知端口返回空串，由分类引擎兜底。"""
    return PORT_PROTOCOL.get(str(port).strip(), "")


@dataclass
class Asset:
    """一条资产记录。字段顺序对齐 FOFA fields 顺序（host,ip,port,title,server）。"""

    host: str
    ip: str = ""
    port: str = ""
    title: str = ""
    server: str = ""
    protocol: str = ""
    # 以下由分类/映射阶段回填
    category: str = ""
    tech: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.protocol:
            self.protocol = guess_protocol(self.port)

    @property
    def url(self) -> str:
        """尽力拼出一个可访问 URL；非 HTTP 端口返回 host:port。"""
        if self.protocol in ("http", "https"):
            return f"{self.protocol}://{self.host}"
        if self.host and self.port:
            return f"{self.host}:{self.port}"
        return self.host


@dataclass
class Classification:
    """分类引擎的输出：类别 + 组件 + 置信度 + 命中证据。

    保留 evidence 的目的是让分类结果可解释——
    「为什么把它判成 Spring Boot Actuator」必须能回答。
    """

    category: str
    tech: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)


@dataclass
class SurfaceRule:
    """攻击面映射规则（来自 attack_surface_rules.yaml）。"""

    category: str
    display_name: str = ""
    priority: int = 5  # 1 最高（P1），5 最低
    tactics: list[str] = field(default_factory=list)  # 打哪
    success_signal: str = ""  # 出什么算成
    false_positive: list[str] = field(default_factory=list)  # 什么算假点
    knowledge_ref: list[str] = field(default_factory=list)  # 参考主题标签


@dataclass
class AttackSurface:
    """一个攻击面 = 规则 + 归属它的资产。"""

    category: str
    display_name: str = ""
    priority: int = 5
    tactics: list[str] = field(default_factory=list)
    success_signal: str = ""
    false_positive: list[str] = field(default_factory=list)
    knowledge_ref: list[str] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)


@dataclass
class FetchResult:
    """数据源的统一返回。任何 AssetSource 实现都返回它。"""

    source: str
    query: str = ""
    assets: list[Asset] = field(default_factory=list)
    account_used: str = ""
    account_tried: list[str] = field(default_factory=list)
    error: str = ""
    fpoint_consumed: int = 0
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class RunStats:
    """一次运行的成本与可靠性统计。

    存在的理由：FOFA 配额是钱，不可见的成本无法被优化。
    """

    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    assets_count: int = 0
    fpoint_consumed: int = 0
    account_switches: int = 0  # 切号次数
    retries: int = 0  # 退避重试次数
    cache_hits: int = 0
    cache_misses: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def cache_total(self) -> int:
        return self.cache_hits + self.cache_misses

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_total
        return (self.cache_hits / total) if total else 0.0


@dataclass
class ReportData:
    """交给 Writer 渲染的完整数据。"""

    target: str
    generated_at: str = ""
    source: str = ""
    query: str = ""
    assets: list[Asset] = field(default_factory=list)
    surfaces: list[AttackSurface] = field(default_factory=list)
    category_counts: dict[str, int] = field(default_factory=dict)
    stats: RunStats = field(default_factory=RunStats)

    @property
    def high_value_surfaces(self) -> list[AttackSurface]:
        """P1/P2 攻击面 —— 报告顶部直出，先打这些。"""
        return [s for s in self.surfaces if s.priority <= 2]
