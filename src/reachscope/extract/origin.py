"""来源校验分类（PLAN §5.6 / TASKS T2.5）。

扫描范围（用户收紧，D-047）：
- `shouldOverrideUrlLoading` / `onPageStarted` / `onPageFinished` **只认 super 链含
  WebViewClient / WebChromeClient 的类**（避免命中外挂的同名业务方法把反例判反）
- 带 `@JavascriptInterface` 的桥方法
- 出现 `loadUrl` / `loadData` 的方法（判 `pre_load` 用）

方法内用一次前向“标签传播”（不是跨方法数据流）判定被校验的字符串来自哪里，
再看它参与了哪个 `String` 方法，映射成 strong / medium / weak / none（D-048）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from enum import StrEnum

from ..graph import regflow
from ..ingest.smali import ClassInfo, Instruction, MethodInfo, SmaliIndex
from ..ir.model import Bridge, OriginCheck, OriginLocation, OriginStrength, SourceLoc
from .bridge import JAVASCRIPT_INTERFACE
from .components import class_name_of
from .webview import CALLBACK_NAMES, CallsiteKind, is_callback_method, match_callsite

logger = logging.getLogger("reachscope.extract.origin")


class Tag(StrEnum):
    """方法内字符串来源的粗略标签（前向传播，不跨方法）。"""

    CONST = "const"
    RAW_URL = "raw_url"
    HOST = "host"
    PATH = "path"
    QUERY = "query"
    URI = "uri"
    CONCAT = "concat"
    UNKNOWN = "unknown"


#: `Uri` 的取值方法 → 标签。
URI_ACCESSORS = {
    "getHost": Tag.HOST,
    "getAuthority": Tag.HOST,
    "getPath": Tag.PATH,
    "getLastPathSegment": Tag.PATH,
    "getQuery": Tag.QUERY,
    "getQueryParameter": Tag.QUERY,
}

#: 精确比较 → strong（host）/ medium（原始 URL）。
EQUALS_METHODS = frozenset({"equals", "equalsIgnoreCase", "contentEquals"})

#: 前后缀比较 → medium（作用于 host）。
AFFIX_METHODS = frozenset({"startsWith", "endsWith", "regionMatches"})

#: 子串匹配 → weak。
SUBSTRING_METHODS = frozenset({"contains", "indexOf", "lastIndexOf", "find", "matches"})

BYPASS_CONCAT = "substring match on concatenated host+path"
BYPASS_FULL_URL = "substring match on full URL"
BYPASS_AFFIX_URL = "prefix/suffix match on full URL"

#: 位置优先级：桥方法内 > 加载前 > shouldOverride > 页面回调（D-049）。
LOCATION_RANK = {
    OriginLocation.BRIDGE_METHOD: 4,
    OriginLocation.PRE_LOAD: 3,
    OriginLocation.SHOULD_OVERRIDE: 2,
    OriginLocation.PAGE_CALLBACK: 1,
    OriginLocation.NONE: 0,
}


@dataclass(frozen=True)
class _Match:
    """方法内命中的一次校验。"""

    strength: OriginStrength
    kind: str
    index: int
    bypass_reason: str | None


@dataclass(frozen=True)
class OriginFinding:
    """一个方法内的校验结果（连带方法/类，供挂到桥上时用）。"""

    check: OriginCheck
    method: MethodInfo
    class_info: ClassInfo


def collect_origin_checks(index: SmaliIndex) -> list[OriginFinding]:
    """扫描全 APK，产出所有识别到的来源校验（按证据位置排序）。"""
    findings: list[OriginFinding] = []
    for descriptor in sorted(index.class_by_descriptor):
        class_info = index.class_by_descriptor[descriptor]
        for method in class_info.methods:
            if not _in_scope(index, class_info, method):
                continue
            finding = _scan_method(class_info, method)
            if finding is not None:
                findings.append(finding)
    findings.sort(key=_sort_key)
    return findings


def attach_origin_checks(bridges: list[Bridge], findings: list[OriginFinding]) -> list[Bridge]:
    """把最强的校验挂到每个桥上，并给含校验的桥方法置 `guarded=True`（D-044）。"""
    guarded_sources = {
        finding.method.source
        for finding in findings
        if finding.check.location is OriginLocation.BRIDGE_METHOD
    }
    updated: list[Bridge] = []
    for bridge in bridges:
        methods = [
            replace(method, guarded=method.source in guarded_sources) for method in bridge.methods
        ]
        updated.append(replace(bridge, origin_check=_best_for_bridge(bridge, findings), methods=methods))
    return updated


def _in_scope(index: SmaliIndex, class_info: ClassInfo, method: MethodInfo) -> bool:
    """该方法是否是 §5.6 的扫描对象（D-047）。"""
    if is_callback_method(class_info, method, index):
        return True
    if method.has_annotation(JAVASCRIPT_INTERFACE):
        return True
    return _first_load_index(method) is not None


def _scan_method(class_info: ClassInfo, method: MethodInfo) -> OriginFinding | None:
    """在一个方法内找最强的校验并判定 location / effective。"""
    match = _scan_checks(method)
    if match is None:
        return None

    load_index = _first_load_index(method)
    location = _location_of(method, match.index, load_index)
    effective, bypass = _effective_of(method, location, match, load_index)
    return OriginFinding(
        check=OriginCheck(
            present=True,
            strength=match.strength,
            kind=match.kind,
            location=location,
            effective=effective,
            evidence=_location(method, match.index),
            bypass_reason=bypass,
        ),
        method=method,
        class_info=class_info,
    )


def _location_of(method: MethodInfo, check_index: int, load_index: int | None) -> OriginLocation:
    """校验所在位置：`pre_load` 优先于桥方法，再是回调（D-049）。"""
    if load_index is not None and check_index < load_index:
        return OriginLocation.PRE_LOAD
    if method.has_annotation(JAVASCRIPT_INTERFACE):
        return OriginLocation.BRIDGE_METHOD
    if method.name == "shouldOverrideUrlLoading":
        return OriginLocation.SHOULD_OVERRIDE
    if method.name in CALLBACK_NAMES:
        return OriginLocation.PAGE_CALLBACK
    return OriginLocation.NONE


def _effective_of(
    method: MethodInfo, location: OriginLocation, match: _Match, load_index: int | None
) -> tuple[bool, str | None]:
    """生效性：失败分支必须跳过 loadUrl；无法确认 → False + 证据写明（D-048）。"""
    if location is OriginLocation.PRE_LOAD:
        if load_index is not None and _branch_guards(method, load_index):
            return True, match.bypass_reason
        return False, match.bypass_reason or "check order unconfirmed: no branch guards loadUrl"
    if location is OriginLocation.BRIDGE_METHOD:
        return True, match.bypass_reason
    if location is OriginLocation.SHOULD_OVERRIDE:
        return (
            False,
            match.bypass_reason
            or "check only in shouldOverrideUrlLoading; first loadUrl unaffected",
        )
    if location is OriginLocation.PAGE_CALLBACK:
        return False, match.bypass_reason or "check only in page callback; first loadUrl unaffected"
    return False, match.bypass_reason or "check location unknown; effectiveness unconfirmed"


def _scan_checks(method: MethodInfo) -> _Match | None:
    """前向扫描一遍：边传播标签边判定，取最强的一次校验。

    **必须边传播边判定**：smali 里寄存器会被复用（同一个 v1 先装 getHost 结果、
    后面又装别的字符串），只看最终标签表会丢掉真实的校验点。
    """
    tags: dict[str, Tag] = {}
    builder_tags: dict[str, set[Tag]] = {}
    url_register = _url_param_register(method)
    if url_register:
        tags[url_register] = Tag.RAW_URL

    best: _Match | None = None
    for instruction in method.instructions:
        const = regflow.parse_const_string(instruction)
        if const is not None:
            tags[const[0]] = Tag.CONST
            continue
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue

        match = _classify(site, tags)
        if match is not None and (best is None or _rank(match.strength) > _rank(best.strength)):
            best = match

        result = regflow.result_of_call(method, site.index)
        if site.class_descriptor == "Ljava/lang/StringBuilder;":
            if site.method == "append" and site.receiver:
                builder_tags.setdefault(site.receiver, set()).update(
                    tags.get(register, Tag.UNKNOWN) for register in site.value_args
                )
            elif site.method == "toString" and result:
                tags[result] = _combine(builder_tags.get(site.receiver or "", set()))
            continue
        tag = _tag_of_call(site, tags)
        if result and tag is not Tag.UNKNOWN:
            tags[result] = tag
    return best


def _classify(site: regflow.InvokeSite, tags: dict[str, Tag]) -> _Match | None:
    """按被调用的 `String` 方法与实参标签分档（D-048）。"""
    owner = class_name_of(site.class_descriptor).split(".")[-1]
    if owner != "String":
        return None
    subjects = [tags.get(register, Tag.UNKNOWN) for register in site.args]
    kind = f"{owner}.{site.method}"

    if site.method in EQUALS_METHODS:
        if Tag.HOST in subjects:
            return _Match(OriginStrength.STRONG, kind, site.index, None)
        if Tag.RAW_URL in subjects or Tag.URI in subjects:
            return _Match(OriginStrength.MEDIUM, kind, site.index, None)
        return None
    if site.method in AFFIX_METHODS:
        if Tag.HOST in subjects:
            return _Match(OriginStrength.MEDIUM, kind, site.index, None)
        if Tag.RAW_URL in subjects or Tag.URI in subjects:
            return _Match(OriginStrength.WEAK, kind, site.index, BYPASS_AFFIX_URL)
        return None
    if site.method in SUBSTRING_METHODS:
        if Tag.CONCAT in subjects or Tag.HOST in subjects:
            return _Match(OriginStrength.WEAK, kind, site.index, BYPASS_CONCAT)
        return _Match(OriginStrength.WEAK, kind, site.index, BYPASS_FULL_URL)
    return None


def _propagate(method: MethodInfo, url_register: str | None) -> dict[str, Tag]:
    """前向传播寄存器标签（含 StringBuilder 拼接识别，D-048）。"""
    tags: dict[str, Tag] = {}
    builder_tags: dict[str, set[Tag]] = {}
    if url_register:
        tags[url_register] = Tag.RAW_URL

    for instruction in method.instructions:
        const = regflow.parse_const_string(instruction)
        if const is not None:
            tags[const[0]] = Tag.CONST
            continue
        site = regflow.parse_invoke(instruction)
        if site is None:
            continue
        result = regflow.result_of_call(method, site.index)
        if site.class_descriptor == "Ljava/lang/StringBuilder;":
            if site.method == "append" and site.receiver:
                builder_tags.setdefault(site.receiver, set()).update(
                    tags.get(register, Tag.UNKNOWN) for register in site.value_args
                )
            elif site.method == "toString" and result:
                tags[result] = _combine(builder_tags.get(site.receiver or "", set()))
            continue
        tag = _tag_of_call(site, tags)
        if result and tag is not Tag.UNKNOWN:
            tags[result] = tag
    return tags


def _tag_of_call(site: regflow.InvokeSite, tags: dict[str, Tag]) -> Tag:
    """被调用方法的结果标签。"""
    accessor = URI_ACCESSORS.get(site.method)
    if accessor is not None:
        return accessor
    if site.method == "toString" and site.receiver:
        return tags.get(site.receiver, Tag.UNKNOWN)
    if site.method in ("parse", "concat", "valueOf", "substring", "trim", "toLowerCase"):
        for register in site.value_args:
            tag = tags.get(register)
            if tag in (Tag.HOST, Tag.RAW_URL, Tag.CONCAT, Tag.URI):
                return tag
        return Tag.URI if site.method == "parse" else Tag.UNKNOWN
    return Tag.UNKNOWN


def _combine(tags: set[Tag]) -> Tag:
    """`StringBuilder` 的 append 标签合并：host + path/常量 → 拼接。"""
    if Tag.HOST in tags and (Tag.PATH in tags or Tag.CONST in tags or Tag.QUERY in tags):
        return Tag.CONCAT
    if Tag.HOST in tags:
        return Tag.HOST
    if Tag.CONCAT in tags:
        return Tag.CONCAT
    if Tag.RAW_URL in tags or Tag.URI in tags:
        return Tag.RAW_URL
    if Tag.PATH in tags:
        return Tag.PATH
    return Tag.UNKNOWN


def _url_param_register(method: MethodInfo) -> str | None:
    """回调里承载 URL 的 String 参数（取最后一个 String 参数，如 `p2`）。"""
    types = regflow.param_types(method.signature)
    indices = [index for index, type_ in enumerate(types) if type_ == "Ljava/lang/String;"]
    if not indices:
        return None
    # 非静态方法 p0 是 this，所以第 i 个参数落在 p(i+1)；静态方法落在 p(i)。
    offset = 0 if "static" in method.access else 1
    return f"p{indices[-1] + offset}"


def _first_load_index(method: MethodInfo) -> int | None:
    """方法内第一个 `loadUrl` / `loadData` 调用的下标。"""
    for instruction in method.instructions:
        match = match_callsite(instruction)
        if match is not None and match.kind is CallsiteKind.LOAD:
            return instruction.index
    return None


def _branch_guards(method: MethodInfo, load_index: int) -> bool:
    """loadUrl 是否位于分支体内（失败分支能跳过它），从而确认校验生效。"""
    branch: Instruction | None = None
    for instruction in reversed(method.instructions[:load_index]):
        if instruction.opcode.startswith("if-"):
            branch = instruction
            break
    if branch is None:
        return False
    target = branch.operands_raw.split(",")[-1].strip()
    if not target.startswith(":"):
        return False
    return any(
        instruction.opcode == target and instruction.index > load_index
        for instruction in method.instructions
    )


def _best_for_bridge(bridge: Bridge, findings: list[OriginFinding]) -> OriginCheck:
    """桥自己的方法里有校验优先，否则取全局最强（位置优先，其次强度）。"""
    own = [
        finding
        for finding in findings
        if class_name_of(finding.class_info.descriptor) == bridge.impl_class
    ]
    candidates = own or findings
    if not candidates:
        return OriginCheck()
    best = max(
        candidates,
        key=lambda f: (LOCATION_RANK[f.check.location], _rank(f.check.strength)),
    )
    return best.check


def _rank(strength: OriginStrength) -> int:
    return {"none": 0, "weak": 1, "medium": 2, "strong": 3}[strength.value]


def _location(method: MethodInfo, index: int) -> SourceLoc:
    instruction = method.instructions[index] if 0 <= index < len(method.instructions) else None
    return SourceLoc(
        file=method.source.file,
        line=instruction.file_line if instruction else 0,
        snippet=f"{instruction.opcode} {instruction.operands_raw}".strip() if instruction else "",
    )


def _sort_key(finding: OriginFinding) -> tuple[str, int]:
    source = finding.check.evidence or SourceLoc()
    return (source.file, source.line)
