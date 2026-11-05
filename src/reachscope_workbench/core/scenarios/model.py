"""场景包的数据文法：只做结构与取值校验，不碰文件系统。

模型全部 ``extra="forbid"``：作者写错字段名会立刻被拒绝，
避免"以为生效了其实没生效"。
"""

from __future__ import annotations

import re
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

PACK_FORMAT: Final = 1
MAX_PACK_BYTES: Final = 2 * 1024 * 1024
MAX_ROUTES: Final = 32
MAX_COOKIES: Final = 4
MAX_EXPECTATIONS: Final = 16
MAX_HEADER_VALUE: Final = 512
MAX_COOKIE_PART: Final = 128
# id 文法的单一来源：加载器用 \Z 全文匹配，API 字段用 ^...$，两者由同一文本拼装。
ID_PATTERN_TEXT: Final = r"[a-z0-9][a-z0-9-]{1,40}"
ID_PATTERN: Final = re.compile(ID_PATTERN_TEXT + r"\Z")
ALLOWED_PROFILES: Final = frozenset({"baseline", "hardened"})
ALLOWED_BODY_SUFFIXES: Final = frozenset({".html", ".txt", ".css"})

# 作者可设响应头白名单（小写比对）。扩展白名单 = 一次代码变更（设计稿 §3.3）。
ALLOWED_HEADERS: Final = frozenset({
    "cache-control", "content-security-policy", "content-type", "cross-origin-opener-policy",
    "cross-origin-resource-policy", "location", "permissions-policy", "referrer-policy",
    "strict-transport-security", "x-content-type-options", "x-frame-options",
})
# 运行时保留头：由服务端计算或属于协议层，作者设置即拒绝（规则 15）。
RESERVED_HEADERS: Final = frozenset({"connection", "content-length"})
RESERVED_HEADER_PREFIX: Final = "x-reachscope-lab-"

# 受限 Cookie 文法（规则 19）：恰好一个 name=value 段 + 可选固定属性。
_COOKIE_PAIR: Final = re.compile(r"[A-Za-z0-9._-]{1,128}=[A-Za-z0-9._-]{1,128}\Z")
_COOKIE_FLAGS: Final = frozenset({"HttpOnly", "Path=/", "Secure"})
_SAMESITE_VALUES: Final = frozenset({"Lax", "None", "Strict"})
_MAX_AGE: Final = re.compile(r"[0-9]{1,5}\Z")

_MODEL_CONFIG: Final = ConfigDict(extra="forbid", frozen=True, strict=True)


def _validate_cookie_entry(entry: str) -> None:
    """单条受限 Cookie 文法；不合法即抛 ValueError（规则 19）。"""
    segments = [segment.strip() for segment in entry.split(";")]
    if not segments[0]:
        raise ValueError("Cookie 条目必须以 name=value 段开头")
    if _COOKIE_PAIR.fullmatch(segments[0]) is None:
        raise ValueError("Cookie 必须以一个 name=value 段开头，名字与值限 [A-Za-z0-9._-] 且各 ≤128 字节")
    for segment in segments[1:]:
        if not segment:
            raise ValueError("Cookie 含空属性段")
        if segment in _COOKIE_FLAGS:
            continue
        if segment.startswith("SameSite=") and segment.removeprefix("SameSite=") in _SAMESITE_VALUES:
            continue
        age = segment.removeprefix("Max-Age=") if segment.startswith("Max-Age=") else None
        if age is not None and _MAX_AGE.fullmatch(age) is not None and int(age) <= 86400:
            continue
        raise ValueError(f"Cookie 属性不受支持：{segment!r}")


class ScenarioRoute(BaseModel):
    """一条路由：响应体文件（相对包根）与状态码。"""

    model_config = _MODEL_CONFIG

    body: str
    status: int = 200

    @field_validator("body")
    @classmethod
    def _body_suffix(cls, value: str) -> str:
        if not value.endswith(tuple(sorted(ALLOWED_BODY_SUFFIXES))):
            raise ValueError("body 后缀必须是 .html/.txt/.css 之一")
        return value

    @field_validator("status")
    @classmethod
    def _status_range(cls, value: int) -> int:
        if not 200 <= value <= 599:
            raise ValueError("status 必须在 200..599")
        return value


class ScenarioProfile(BaseModel):
    """一个剖面的响应头、Cookie 与路由。"""

    model_config = _MODEL_CONFIG

    headers: dict[str, str] = {}
    cookies: list[str] = []
    routes: dict[str, ScenarioRoute]

    @field_validator("headers")
    @classmethod
    def _headers_within_allowlist(cls, value: dict[str, str]) -> dict[str, str]:
        seen: set[str] = set()
        for name, header_value in value.items():
            lowered = name.lower()
            if not name or name != name.strip():
                raise ValueError(f"响应头名字为空或含首尾空白：{name!r}")
            if lowered in seen:
                raise ValueError(f"响应头 {name!r} 与先前条目仅大小写不同，会作为重复头发送，浏览器取哪个不确定")
            seen.add(lowered)
            if lowered in RESERVED_HEADERS or lowered.startswith(RESERVED_HEADER_PREFIX):
                raise ValueError(f"响应头 {name!r} 是运行时保留头，作者不能设置")
            if lowered not in ALLOWED_HEADERS:
                raise ValueError(f"响应头 {name!r} 不在白名单内")
            if not header_value.isascii():
                raise ValueError(f"响应头 {name!r} 的值含非 ASCII 字符")
            if len(header_value.encode("utf-8")) > MAX_HEADER_VALUE:
                raise ValueError(f"响应头 {name!r} 的值超过 {MAX_HEADER_VALUE} 字节")
            if "\r" in header_value or "\n" in header_value:
                raise ValueError(f"响应头 {name!r} 的值含换行")
            # 浏览器 URL 解析里反斜杠等价于 /、ASCII 制表符会被整体剔除：
            # `/\evil` 与 `/<TAB>/evil` 都会变成 `//evil` → 协议相对 → 站外跳转。
            # 所以除"单个 / 开头"外，还必须排掉反斜杠与控制字符。
            if lowered == "location" and (
                not header_value.startswith("/")
                or header_value.startswith("//")
                or "\\" in header_value
                or any(not " " <= char <= "~" for char in header_value)
            ):
                raise ValueError("location 只允许以单个 / 开头的站内相对路径，禁止反斜杠与控制字符")
        return value

    @field_validator("cookies")
    @classmethod
    def _cookies_grammar(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_COOKIES:
            raise ValueError(f"Cookie 最多 {MAX_COOKIES} 条")
        for entry in value:
            _validate_cookie_entry(entry)
        return value

    @field_validator("routes")
    @classmethod
    def _routes_shape(cls, value: dict[str, ScenarioRoute]) -> dict[str, ScenarioRoute]:
        if not value:
            raise ValueError("routes 不能为空")
        if len(value) > MAX_ROUTES:
            raise ValueError(f"routes 最多 {MAX_ROUTES} 条")
        for key in value:
            if not key.startswith("/"):
                raise ValueError(f"路由键必须以 / 开头：{key!r}")
            # 与 Location 同一口径：浏览器把 \ 当分隔符、把 // 当协议相对，
            # 控制字符会被剔除或截断——这类键要么不可达，要么教坏作者。
            if key.startswith("//"):
                raise ValueError(f"路由键不许以 // 开头：{key!r}")
            if "?" in key or "#" in key or ".." in key or "\\" in key:
                raise ValueError(f"路由键含非法字符：{key!r}")
            if any(not " " <= char <= "~" for char in key):
                raise ValueError(f"路由键含控制字符：{key!r}")
        return value


class ScenarioExpectation(BaseModel):
    """一条复测期望；absent 用 null 表示（设计稿 §3.2）。"""

    model_config = _MODEL_CONFIG

    field: str
    baseline: str | int | None = None
    hardened: str | int | None = None

    @model_validator(mode="after")
    def _expectation_grammar(self) -> Self:
        if self.field == "status":
            for side in (self.baseline, self.hardened):
                if type(side) is not int:
                    raise ValueError("status 断言的两端都必须是 int")
            return self
        if not self.field.startswith("headers.") or self.field.removeprefix("headers.") not in ALLOWED_HEADERS:
            raise ValueError("field 只允许 status 或 headers.<白名单名（小写）>")
        for side in (self.baseline, self.hardened):
            if side is not None and not isinstance(side, str):
                raise ValueError("headers.<name> 断言的值只允许 str 或 null（absent）")
        return self


class ScenarioPack(BaseModel):
    """一个场景包的全部声明。"""

    model_config = _MODEL_CONFIG

    pack_format: int
    id: str
    title: dict[str, str]
    summary: dict[str, str]
    difficulty: Literal["intro", "intermediate", "advanced"]
    profiles: dict[str, ScenarioProfile]
    expectations: list[ScenarioExpectation] = []
    limits: list[str] = []

    @field_validator("pack_format")
    @classmethod
    def _pack_format_is_current(cls, value: int) -> int:
        if value != PACK_FORMAT:
            raise ValueError(f"pack_format 必须是 {PACK_FORMAT}")
        return value

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if ID_PATTERN.fullmatch(value) is None:
            raise ValueError("id 必须匹配 [a-z0-9][a-z0-9-]{1,40}")
        return value

    @field_validator("title", "summary")
    @classmethod
    def _bilingual_keys(cls, value: dict[str, str]) -> dict[str, str]:
        if "en" not in value:
            raise ValueError("必须包含 en 文案")
        if set(value) - {"en", "zh"}:
            raise ValueError("语言键只允许 en/zh")
        return value

    @field_validator("profiles")
    @classmethod
    def _profiles_complete(cls, value: dict[str, ScenarioProfile]) -> dict[str, ScenarioProfile]:
        if set(value) != ALLOWED_PROFILES:
            raise ValueError("profiles 必须恰好包含 baseline 与 hardened")
        return value

    @field_validator("expectations")
    @classmethod
    def _expectations_cap(cls, value: list[ScenarioExpectation]) -> list[ScenarioExpectation]:
        if len(value) > MAX_EXPECTATIONS:
            raise ValueError(f"expectations 最多 {MAX_EXPECTATIONS} 条")
        return value
