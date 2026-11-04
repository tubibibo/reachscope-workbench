"""Conservative SSH/Nginx export review, with bounded context-aware parsing.

Exports are operator-supplied text, not authenticated runtime facts. Includes are
resolved solely against actual nginx -T dump sections; no host files are opened.
Unresolved scopes never support a pass or a successful remediation comparison.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from .guidance import baseline_guidance

MAX_LINES = 10_000
MAX_TOKENS = 20_000
MAX_CONTEXTS = 200
MAX_FACTS = 100
_SSH_FIELDS = {"permitrootlogin", "passwordauthentication", "permitemptypasswords", "maxauthtries"}
_NGINX_FIELDS = {"autoindex", "server_tokens", "ssl_protocols"}
_HEADER = re.compile(r"^# configuration file ([^\r\n]{1,1000}):\s*$")
_LIMITATIONS = [
    "仅复核操作员提供的 SSH/Nginx 静态导出，不连接主机、不执行命令、不证明当前服务已加载该配置。",
    "SSH 导出仅覆盖所提供连接上下文；Match、Include 与缺失字段保持未知，口令关闭不覆盖全部 PAM/键盘交互认证。",
    "Nginx 仅实现有限 HTTP 配置语法与导出内 Include 解析；变量、未提供的包含文件、歧义和截断会保留覆盖缺口。",
    "通过仅表示所述静态条件，不能证明端口连通、实际 TLS 握手、目录可浏览、账户授权或整体安全。",
    "结果仅保留允许的配置值、位置及摘要；原上传配置仍按本地文件策略保存在本机，可能包含敏感资料。",
]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _check(host: str, component: str, suffix: str, title: str, status: str, facts: list[dict[str, Any]],
           *, complete: bool, scopes: list[str], capture_kind: str,
           scope_complete: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    identifier = f"host.{component}.{suffix}"
    truncated = len(facts) > MAX_FACTS
    if truncated and status == "pass":
        status = "unknown"
    eid = "host-config-" + _digest([identifier, host])[:24]
    values = {"facts": facts[:MAX_FACTS], "facts_truncated": truncated,
              "capture_kind": capture_kind, "runtime_state_verified": False}
    description = {"pass": "已提供完整范围内的本项配置满足所述检查条件，真实部署与业务仍需人工验证。",
                   "review": "观察到需要结合业务复核的配置声明；本结果不是漏洞可利用性或入侵证明。",
                   "unknown": "配置资料缺失、无法唯一解析或范围不完整，不能据此判断安全或整改完成。",
                   "not_applicable": "提供的有限配置范围没有本项适用上下文；不代表主机没有其他服务或风险。"}[status]
    guide = baseline_guidance(identifier)
    row = {"id": identifier, "resource_id": host + "::" + component,
           "title": title, "status": status, "severity": "medium" if status == "review" else "info",
           "description": description, "recommendation": guide["blue_steps"][0], "evidence_ids": [eid],
           "complete": complete and not truncated and status in {"pass", "review", "not_applicable"},
           "facts_truncated": truncated, "evidence": {"pointer": f"/{component}", "values": values},
           "comparison_identity": {"component": component, "scope_keys": sorted(scopes), "complete": scope_complete},
           "guidance": guide}
    evidence = {"id": eid, "kind": "host_static_configuration", "title": title,
                "source": f"host-snapshot#/{component}", "data": values, "sha256": _digest(values)}
    return row, evidence


def _ssh(text: str | None, host: str, connection_context: str | None,
         capture_kind: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    values: dict[str, list[tuple[str, int]]] = {key: [] for key in _SSH_FIELDS}
    gaps: set[str] = set()
    present = isinstance(text, str) and bool(text.strip())
    lines = text.splitlines() if present and text is not None else []
    if not present:
        gaps.add("missing_export")
    if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text or ""):
        gaps.add("control_characters_in_export")
    if len(lines) > MAX_LINES:
        gaps.add("line_limit")
    for index, raw in enumerate(lines[:MAX_LINES], 1):
        try:
            tokens = shlex.split(raw, comments=True, posix=True)
        except ValueError:
            gaps.add("invalid_line")
            continue
        if not tokens:
            continue
        name = tokens[0].lower()
        if name in {"match", "include"}:
            gaps.add("unresolved_match_or_include")
        if name in _SSH_FIELDS:
            if len(tokens) != 2 or len(tokens[1]) > 80:
                gaps.add("invalid_reviewed_field")
            else:
                values[name].append((tokens[1], index))
    definitions = (("permitrootlogin", "root_login", "SSH 直接 root 登录边界"),
                   ("passwordauthentication", "password_auth", "SSH 口令认证声明"),
                   ("permitemptypasswords", "empty_passwords", "SSH 空口令认证声明"),
                   ("maxauthtries", "max_auth_tries", "SSH 每连接认证尝试次数"))
    checks, evidence = [], []
    context_known = isinstance(connection_context, str) and bool(connection_context.strip())
    scope = "ssh:" + _digest(connection_context) if context_known else "ssh:unspecified"
    for field_name, suffix, title in definitions:
        captured = values[field_name]
        known = len(captured) == 1
        value = captured[0][0] if known else None
        allowed: set[str] = ({"yes", "no", "prohibit-password", "without-password", "forced-commands-only"}
                             if field_name == "permitrootlogin" else {"yes", "no"})
        if field_name == "maxauthtries":
            parsed = int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 5 else None
            known = parsed is not None and 1 <= parsed <= 65535
            state = "pass" if known and parsed is not None and parsed <= 4 else "review" if known else "unknown"
            shown: Any = parsed if known else "[unresolved]"
        else:
            known = known and value in allowed
            # Direct root access with restricted key/command contexts still
            # warrants review; only an explicit no satisfies this strict rule.
            state = "pass" if known and value == "no" else "review" if known else "unknown"
            shown = value if known else "[unresolved]"
        if gaps:
            state = "unknown"
        facts = [{"field": field_name, "line": captured[0][1] if captured else None,
                  "value": shown, "occurrences": len(captured), "gap_codes": sorted(gaps),
                  "connection_context_provided": context_known,
                  "export_sha256": hashlib.sha256((text or "").encode("utf-8")).hexdigest()}]
        check, proof = _check(host, "ssh", suffix, title, state, facts, complete=known and not gaps,
                             scopes=[scope], scope_complete=context_known, capture_kind=capture_kind)
        checks.append(check)
        evidence.append(proof)
    return checks, evidence, {"provided": present, "lines": len(lines), "reviewed_fields": len(definitions), "gap_codes": sorted(gaps),
                               "connection_context_provided": context_known, "connection_context_verified": False}


@dataclass(frozen=True)
class _Token:
    value: str
    line: int


@dataclass
class _Node:
    name: str
    args: list[str]
    line: int
    children: list[_Node] | None = None


@dataclass
class _Context:
    key: str
    kind: str
    line: int
    values: dict[str, tuple[list[str], int]] = field(default_factory=dict)
    tls: bool = False
    ambiguous: bool = False
    listeners: list[tuple[str, bool]] = field(default_factory=list)


class _ParseGap(ValueError):
    pass


def _tokens(text: str, offset: int = 0) -> list[_Token]:
    tokens: list[_Token] = []
    value: list[str] = []
    line, start = offset + 1, offset + 1
    quote: str | None = None
    escaped, comment, started, closed_quote = False, False, False, False

    def flush() -> None:
        nonlocal started, closed_quote
        if started:
            tokens.append(_Token("".join(value), start))
            value.clear()
            started, closed_quote = False, False

    for char in text:
        if char == "\n":
            line += 1
        if comment:
            if char == "\n":
                comment = False
            continue
        if closed_quote and not char.isspace() and char not in "{};#":
            raise _ParseGap("unsupported_quoted_token_suffix")
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            if not started:
                start = line
                started = True
            escaped = True
        elif quote:
            if char == quote:
                quote = None
                closed_quote = True
            else:
                value.append(char)
        elif char in {'"', "'"}:
            if started:
                raise _ParseGap("unsupported_embedded_quote")
            start, started = line, True
            quote = char
        elif char == "#":
            flush()
            comment = True
        elif char in "{};":
            flush()
            tokens.append(_Token(char, line))
        elif char.isspace():
            flush()
        else:
            if not started:
                start, started = line, True
            value.append(char)
        if len(value) > 4096 or len(tokens) > MAX_TOKENS:
            raise _ParseGap("token_limit")
    if quote or escaped:
        raise _ParseGap("incomplete_quote")
    flush()
    if len(tokens) > MAX_TOKENS:
        raise _ParseGap("token_limit")
    return tokens


def _tree(tokens: list[_Token]) -> list[_Node]:
    position = 0

    def parse(depth: int, nested: bool) -> list[_Node]:
        nonlocal position
        if depth > 30:
            raise _ParseGap("depth_limit")
        output: list[_Node] = []
        while position < len(tokens):
            if tokens[position].value == "}":
                if not nested:
                    raise _ParseGap("unexpected_close")
                position += 1
                return output
            words = []
            line = tokens[position].line
            while position < len(tokens) and tokens[position].value not in {"{", "}", ";"}:
                words.append(tokens[position].value)
                position += 1
            if not words or position >= len(tokens) or tokens[position].value == "}":
                raise _ParseGap("incomplete_directive")
            ending = tokens[position].value
            position += 1
            output.append(_Node(words[0], words[1:], line, parse(depth + 1, True) if ending == "{" else None))
        if nested:
            raise _ParseGap("unclosed_block")
        return output

    return parse(0, False)


def _nginx_tree(text: str) -> tuple[list[_Node], set[str]]:
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise _ParseGap("line_limit")
    sections: dict[str, tuple[list[str], int]] = {}
    current = "[provided-main]"
    buffer: list[str] = []
    offset = 0
    for index, line in enumerate(lines):
        match = _HEADER.fullmatch(line)
        if match:
            if buffer and any(part.strip() for part in buffer):
                if current in sections:
                    raise _ParseGap("duplicate_dump_section")
                sections[current] = (buffer, offset)
            current, buffer, offset = posixpath.normpath(match[1]), [], index + 1
        else:
            buffer.append(line)
    if buffer and any(part.strip() for part in buffer):
        if current in sections:
            raise _ParseGap("duplicate_dump_section")
        sections[current] = (buffer, offset)
    if not sections or len(sections) > 50:
        raise _ParseGap("section_limit_or_empty")
    parsed = {name: _tree(_tokens("\n".join(parts), start)) for name, (parts, start) in sections.items()}
    gaps: set[str] = set()
    expanded = 0

    def expand(nodes: list[_Node], stack: tuple[str, ...], depth: int) -> list[_Node]:
        nonlocal expanded
        if depth > 30:
            raise _ParseGap("include_depth_limit")
        output = []
        for node in nodes:
            expanded += 1
            if expanded > MAX_TOKENS:
                raise _ParseGap("expanded_directive_limit")
            if node.name == "include":
                pattern = node.args[0] if len(node.args) == 1 else ""
                if not pattern.startswith("/") or "$" in pattern:
                    gaps.add("unresolved_include")
                    continue
                parts = posixpath.normpath(pattern).split("/")
                matches = sorted(name for name in parsed if len(name.split("/")) == len(parts)
                                 and all(fnmatch.fnmatchcase(part, match) for part, match in zip(name.split("/"), parts, strict=True)))
                if not matches:
                    gaps.add("unresolved_include")
                for name in matches:
                    if name in stack:
                        gaps.add("include_cycle")
                    else:
                        output.extend(expand(parsed[name], (*stack, name), depth + 1))
            else:
                output.append(_Node(node.name, node.args, node.line,
                                    expand(node.children, stack, depth + 1) if node.children is not None else None))
        return output

    first = next(iter(parsed))
    return expand(parsed[first], (first,), 0), gaps


def _nginx_contexts(nodes: list[_Node]) -> tuple[list[_Context], set[str]]:
    roots = [node for node in nodes if node.name == "http" and node.children is not None]
    gaps: set[str] = set()
    if len(roots) != 1:
        return [], {"http_scope_missing_or_ambiguous"}
    if roots[0].args:
        return [], {"unsupported_http_block_arguments"}
    output: list[_Context] = []
    seen: set[str] = set()

    def walk(node: _Node, inherited: dict[str, tuple[list[str], int]], parent: str, tls: bool) -> None:
        if len(output) >= MAX_CONTEXTS:
            raise _ParseGap("context_limit")
        if node.name == "server" and node.args:
            gaps.add("unsupported_server_block_arguments")
        if node.name == "location" and (not node.args or not all(node.args)
                                        or len(node.args) > 2 or len(node.args) == 2 and node.args[0] not in {"=", "~", "~*", "^~"}):
            gaps.add("unsupported_location_arguments")
        values = dict(inherited)
        own: dict[str, list[_Node]] = {}
        for child in node.children or []:
            if child.name in _NGINX_FIELDS and child.children is None:
                own.setdefault(child.name, []).append(child)
        for key, entries in own.items():
            if len(entries) != 1:
                gaps.add("duplicate_reviewed_directive")
                values[key] = (["[ambiguous]"], entries[0].line)
            else:
                values[key] = (entries[0].args, entries[0].line)
        identity: list[Any] = [node.name, node.args]
        if node.name == "server":
            identity.extend([[child.name, child.args] for child in node.children or [] if child.name in {"listen", "server_name"}])
            tls = any(child.name == "listen" and "ssl" in child.args for child in node.children or [])
            if any(child.name == "ssl" for child in node.children or []):
                gaps.add("legacy_ssl_directive")
            if any(child.name == "listen" and (not child.args or child.children is not None) for child in node.children or []):
                gaps.add("invalid_listen_declaration")
        selector_args = [*node.args, *(value for child in node.children or []
                                      if child.name in {"listen", "server_name"} for value in child.args)]
        if any("$" in value for value in selector_args):
            gaps.add("dynamic_context_selector")
        key = _digest([parent, identity])[:32]
        ambiguous = key in seen
        if ambiguous:
            gaps.add("ambiguous_context_identity")
        seen.add(key)
        listeners = [(child.args[0], "ssl" in child.args) for child in node.children or []
                     if child.name == "listen" and child.args] if node.name == "server" else []
        context = _Context(key, node.name, node.line, values, tls, ambiguous, listeners)
        if node.name != "http":
            output.append(context)
        for child in node.children or []:
            if child.children is None:
                if child.name in _NGINX_FIELDS and node.name not in {"http", "server", "location"}:
                    gaps.add("unsupported_directive_context")
                continue
            if child.name == "server" and node.name == "http" or child.name == "location" and node.name in {"server", "location"}:
                walk(child, values, key, tls)
            elif child.name in {"if", "limit_except"}:
                gaps.add("conditional_scope_not_evaluated")
            elif child.name not in {"types", "map", "upstream", "geo", "split_clients", "charset_map"}:
                gaps.add("unsupported_http_block")
    walk(roots[0], {}, "http", False)
    sockets: dict[str, set[bool]] = {}
    ports: dict[str, set[bool]] = {}
    for context in output:
        for address, ssl in context.listeners:
            # Normalize only obvious IPv4 wildcard aliases. DNS, actual bound
            # sockets and version-dependent protocol selection are not queried.
            normalized = "*:" + address if address.isdecimal() else address
            if normalized.startswith("0.0.0.0:"):
                normalized = "*:" + normalized.removeprefix("0.0.0.0:")
            sockets.setdefault(normalized, set()).add(ssl)
            port = re.search(r":([0-9]{1,5})\Z", normalized)
            if port:
                ports.setdefault(port[1], set()).add(ssl)
    if any(len(flags) > 1 for flags in [*sockets.values(), *ports.values()]):
        gaps.add("shared_tls_listener_context_not_evaluated")
    if not output:
        gaps.add("server_scope_missing")
    return output, gaps


def _nginx(text: str | None, host: str, capture_kind: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    contexts: list[_Context] = []
    gaps: set[str] = set()
    present = isinstance(text, str) and bool(text.strip())
    if present and text is not None:
        try:
            if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text):
                raise _ParseGap("control_characters_in_export")
            nodes, parse_gaps = _nginx_tree(text)
            contexts, context_gaps = _nginx_contexts(nodes)
            gaps.update(parse_gaps | context_gaps)
        except _ParseGap as exc:
            gaps.add(str(exc))
    else:
        gaps.add("missing_export")
    checks, evidence = [], []
    scopes = sorted(context.key for context in contexts)
    for field_name, title in (("autoindex", "Nginx 目录浏览声明"), ("server_tokens", "Nginx 版本令牌声明"), ("ssl_protocols", "Nginx TLS 协议声明")):
        applicable = [context for context in contexts if field_name != "ssl_protocols" or context.kind == "server" and context.tls]
        facts: list[dict[str, Any]] = []
        states = []
        for context in applicable:
            raw, line = context.values.get(field_name, ([], context.line))
            known = (len(raw) == 1 and raw[0] in {"on", "off", "build"}) if field_name == "server_tokens" else (
                bool(raw) and all(value in {"SSLv2", "SSLv3", "TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"} for value in raw)
                if field_name == "ssl_protocols" else len(raw) == 1 and raw[0] in {"on", "off"})
            safe = set(raw) <= {"TLSv1.2", "TLSv1.3"} if field_name == "ssl_protocols" else raw == ["off"]
            states.append("pass" if known and safe else "review" if known else "unknown")
            facts.append({"context_id": context.key, "context_kind": context.kind, "line": line,
                          "directive": field_name, "values": raw if known else ["[unresolved]"], "tls_listener_declared": context.tls})
        state = "review" if "review" in states else "unknown" if "unknown" in states or gaps or not contexts else "pass" if states else "not_applicable"
        # A visible weak declaration remains useful even if other scopes are
        # unresolved, but it can never be a complete remediation baseline.
        complete = not gaps and "unknown" not in states
        if not facts:
            facts = [{"directive": field_name, "gap_codes": sorted(gaps), "applicable_contexts": 0}]
        facts.append({"export_sha256": hashlib.sha256((text or "").encode("utf-8")).hexdigest(), "gap_codes": sorted(gaps)})
        if len(facts) > MAX_FACTS:
            # Keep the actual reason for review inside the retained evidence
            # budget, even when its context occurs late in a large export.
            ranked = sorted(zip(states, facts[:-1], strict=True), key=lambda item: {"review": 0, "unknown": 1, "pass": 2}[item[0]])
            facts = [facts[-1], *(fact for _status, fact in ranked)]
        suffix = "tls_protocols" if field_name == "ssl_protocols" else field_name
        check, proof = _check(host, "nginx", suffix, title, state, facts, complete=complete, scopes=scopes,
                             scope_complete=not gaps, capture_kind=capture_kind)
        checks.append(check)
        evidence.append(proof)
    return checks, evidence, {"provided": present, "contexts_returned": len(contexts), "context_limit": MAX_CONTEXTS,
                               "gap_codes": sorted(gaps), "includes_resolved_only_from_dump": True}


def assess_baseline(data: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    """Execute only selected configuration groups over already validated input."""
    checks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    source_kind = "synthetic_demo" if data.get("source_kind") == "synthetic_demo" else "operator_supplied_export"
    coverage: dict[str, Any] = {"source_kind": source_kind,
                               "collected_at": data.get("collected_at"), "collection_state": data.get("collection_state", "unknown"),
                               "runtime_state_verified": False}
    collection = data.get("collection_metadata")
    if isinstance(collection, dict):
        coverage["collection_metadata"] = collection
    host = str(data["host_id"])
    for component, key in (("ssh", "effective_config"), ("nginx", "config_dump")):
        if component not in selected:
            continue
        value = data.get(component)
        text = value.get(key) if isinstance(value, dict) else None
        exported = text if isinstance(text, str) else None
        if component == "ssh":
            context = value.get("connection_context") if isinstance(value, dict) else None
            rows, proofs, metadata = _ssh(exported, host, context if isinstance(context, str) else None, source_kind)
        else:
            rows, proofs, metadata = _nginx(exported, host, source_kind)
        if isinstance(collection, dict):
            capture = collection["components"][component]
            metadata["capture"] = capture
            for row, proof in zip(rows, proofs, strict=True):
                identity = row["comparison_identity"]
                identity["scope_keys"] = [f"projected:{collection['projection']}:{key}" for key in identity["scope_keys"]]
                if capture["complete"] is not True:
                    row["status"], row["complete"], identity["complete"] = "unknown", False, False
                # This producer-supplied provenance is included before hashing;
                # it is not an assertion of a trusted collector or live state.
                proof["data"]["collection"] = {"projection": collection["projection"], "capture": capture,
                                               "metadata_verified": False}
                proof["sha256"] = _digest(proof["data"])
        checks.extend(rows)
        evidence.extend(proofs)
        coverage[component] = metadata
    return {"checks": checks, "evidence": evidence, "coverage": coverage, "limitations": list(_LIMITATIONS)}
