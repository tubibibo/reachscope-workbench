"""Allowlisted configuration projection; raw exports never leave this module.

The projected Nginx text is for static review only and MUST NOT be deployed. It
retains selected directives and context structure using deterministic aliases.
Unsupported, dynamic or incomplete constructs fail closed as unknown input.
"""

from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re
import shlex
from dataclasses import dataclass

MAX_TOKENS = 20_000
MAX_NODES = 10_000
_SSH = {"permitrootlogin", "passwordauthentication", "permitemptypasswords", "maxauthtries"}
_REVIEW = {"autoindex", "server_tokens", "ssl_protocols"}
_HEADER = re.compile(r"# configuration file ([^\r\n]{1,1000}):\s*\Z")
_IGNORED_BLOCKS = {"types", "map", "upstream", "geo", "split_clients", "charset_map"}
_LISTEN_FLAGS = {"ssl", "default_server", "default", "http2", "proxy_protocol", "bind", "deferred", "reuseport", "ipv6only=on", "ipv6only=off"}


class ProjectionUnsupported(ValueError):
    """Fixed exception with no raw export, token, filename or system error."""

    def __init__(self) -> None:
        super().__init__("projection_unsupported")


def _text(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ProjectionUnsupported from exc
    if not value.strip() or len(raw) > 256 * 1024 or any(ord(char) < 32 and char not in "\r\n\t" or ord(char) == 127 for char in value):
        raise ProjectionUnsupported
    return value


def project_ssh(raw: bytes) -> str:
    values: dict[str, str] = {}
    for line in _text(raw).splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as exc:
            raise ProjectionUnsupported from exc
        if not tokens:
            continue
        name = tokens[0].lower()
        if name in {"match", "include"}:
            raise ProjectionUnsupported
        if name not in _SSH:
            continue
        if name in values or len(tokens) != 2:
            raise ProjectionUnsupported
        value = tokens[1]
        if name == "maxauthtries":
            if not value.isascii() or not value.isdecimal() or len(value) > 5 or not 1 <= int(value) <= 65535:
                raise ProjectionUnsupported
        elif name == "permitrootlogin":
            if value not in {"yes", "no", "prohibit-password", "without-password", "forced-commands-only"}:
                raise ProjectionUnsupported
        elif value not in {"yes", "no"}:
            raise ProjectionUnsupported
        values[name] = value
    if values.keys() != _SSH:
        raise ProjectionUnsupported
    return "".join(name + " " + values[name] + "\n" for name in sorted(values))


@dataclass(frozen=True)
class _Node:
    name: str
    args: tuple[str, ...]
    children: tuple[_Node, ...] | None = None


def _tokens(text: str) -> list[str]:
    output: list[str] = []
    token: list[str] = []
    started, escaped, comment, closed = False, False, False, False
    quote: str | None = None

    def flush() -> None:
        nonlocal started, closed
        if started:
            output.append("".join(token))
            token.clear()
        started, closed = False, False

    for char in text:
        if comment:
            if char == "\n":
                comment = False
            continue
        if closed and not char.isspace() and char not in "{};#":
            raise ProjectionUnsupported
        if escaped:
            token.append(char)
            escaped = False
        elif char == "\\":
            escaped, started = True, True
        elif quote:
            if char == quote:
                quote, closed = None, True
            else:
                token.append(char)
        elif char in {'"', "'"}:
            if started:
                raise ProjectionUnsupported
            quote, started = char, True
        elif char == "#":
            flush()
            comment = True
        elif char in "{};":
            flush()
            output.append(char)
        elif char.isspace():
            flush()
        else:
            started = True
            token.append(char)
        if len(token) > 4096 or len(output) > MAX_TOKENS:
            raise ProjectionUnsupported
    if quote or escaped:
        raise ProjectionUnsupported
    flush()
    if len(output) > MAX_TOKENS:
        raise ProjectionUnsupported
    return output


def _parse(text: str) -> tuple[_Node, ...]:
    tokens = _tokens(text)
    offset = 0

    def walk(depth: int, nested: bool) -> tuple[_Node, ...]:
        nonlocal offset
        if depth > 30:
            raise ProjectionUnsupported
        nodes: list[_Node] = []
        while offset < len(tokens):
            if tokens[offset] == "}":
                if not nested:
                    raise ProjectionUnsupported
                offset += 1
                return tuple(nodes)
            words = []
            while offset < len(tokens) and tokens[offset] not in {"{", "}", ";"}:
                words.append(tokens[offset])
                offset += 1
            if not words or offset == len(tokens) or tokens[offset] == "}":
                raise ProjectionUnsupported
            ending = tokens[offset]
            offset += 1
            nodes.append(_Node(words[0], tuple(words[1:]), walk(depth + 1, True) if ending == "{" else None))
        if nested:
            raise ProjectionUnsupported
        return tuple(nodes)
    return walk(0, False)


def _expanded(text: str) -> tuple[_Node, ...]:
    files: dict[str, str] = {}
    current, marked = "[main]", False
    lines: list[str] = []
    for line in text.splitlines():
        match = _HEADER.fullmatch(line)
        if match:
            if marked or any(part.strip() and not part.lstrip().startswith("#") for part in lines):
                if current in files:
                    raise ProjectionUnsupported
                files[current] = "\n".join(lines)
            current, lines, marked = posixpath.normpath(match[1]), [], True
        else:
            lines.append(line)
    if current in files:
        raise ProjectionUnsupported
    files[current] = "\n".join(lines)
    if len(files) > 50:
        raise ProjectionUnsupported
    trees = {path: _parse(value) for path, value in files.items()}
    count = 0

    def expand(nodes: tuple[_Node, ...], ancestors: tuple[str, ...], depth: int) -> tuple[_Node, ...]:
        nonlocal count
        if depth > 30:
            raise ProjectionUnsupported
        result: list[_Node] = []
        for node in nodes:
            count += 1
            if count > MAX_NODES:
                raise ProjectionUnsupported
            if node.name == "include":
                if node.children is not None or len(node.args) != 1 or not node.args[0].startswith("/") or "$" in node.args[0]:
                    raise ProjectionUnsupported
                pattern = posixpath.normpath(node.args[0]).split("/")
                matching = sorted(path for path in trees if len(path.split("/")) == len(pattern)
                                  and all(fnmatch.fnmatchcase(part, match) for part, match in zip(path.split("/"), pattern, strict=True)))
                if not matching:
                    raise ProjectionUnsupported
                for path in matching:
                    if path in ancestors:
                        raise ProjectionUnsupported
                    result.extend(expand(trees[path], (*ancestors, path), depth + 1))
            else:
                result.append(_Node(node.name, node.args, expand(node.children, ancestors, depth + 1) if node.children is not None else None))
        return tuple(result)
    first = next(iter(trees))
    return expand(trees[first], (first,), 0)


def _alias(kind: str, value: str) -> str:
    return kind + "-" + hashlib.sha256((kind + "\0" + value).encode()).hexdigest()[:24]


def _address(value: str) -> str:
    if "$" in value or not value or len(value) > 512:
        raise ProjectionUnsupported
    if value.isascii() and value.isdecimal() and 1 <= int(value) <= 65535:
        return value
    match = re.fullmatch(r"(.+):([0-9]{1,5})", value)
    if match is None or not 1 <= int(match[2]) <= 65535:
        raise ProjectionUnsupported
    address, port = match.groups()
    if address in {"*", "0.0.0.0"}:
        return str(int(port))
    return _alias("bind", address) + ".invalid:" + str(int(port))


def project_nginx(raw: bytes) -> str:
    roots = _expanded(_text(raw))
    http = [node for node in roots if node.name == "http" and node.children is not None]
    if len(http) != 1 or http[0].args:
        raise ProjectionUnsupported
    contexts = 0

    def has_review(nodes: tuple[_Node, ...]) -> bool:
        return any(node.name in _REVIEW or node.children is not None and has_review(node.children) for node in nodes)

    def render(node: _Node, parent: str) -> str:
        nonlocal contexts
        contexts += 1
        if contexts > 200:
            raise ProjectionUnsupported
        if node.name == "server" and (parent != "http" or node.args):
            raise ProjectionUnsupported
        if node.name == "location":
            if parent not in {"server", "location"} or not node.args or not all(node.args) or len(node.args) > 2:
                raise ProjectionUnsupported
            if len(node.args) == 2 and node.args[0] not in {"=", "~", "~*", "^~"} or any("$" in arg for arg in node.args):
                raise ProjectionUnsupported
            args = [*node.args[:-1], "/" + _alias("route", node.args[-1])]
        else:
            args = list(node.args)
        parts = [node.name + (" " + " ".join(args) if args else "") + " {"]
        for child in node.children or ():
            if child.children is not None:
                if child.name in {"server", "location"}:
                    parts.append(render(child, node.name))
                elif child.name in _IGNORED_BLOCKS and not has_review(child.children):
                    continue
                else:
                    raise ProjectionUnsupported
            elif child.name in _REVIEW:
                values = child.args
                if (child.name in {"autoindex", "server_tokens"} and (len(values) != 1 or values[0] not in ({"on", "off"} if child.name == "autoindex" else {"on", "off", "build"}))
                        or child.name == "ssl_protocols" and (node.name not in {"http", "server"} or not values
                            or any(value not in {"SSLv2", "SSLv3", "TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"} for value in values))):
                    raise ProjectionUnsupported
                parts.append(child.name + " " + " ".join(values) + ";")
            elif child.name == "listen":
                if node.name != "server" or not child.args or any(flag not in _LISTEN_FLAGS for flag in child.args[1:]):
                    raise ProjectionUnsupported
                parts.append("listen " + " ".join([_address(child.args[0]), *child.args[1:]]) + ";")
            elif child.name == "server_name":
                if node.name != "server" or not child.args or any("$" in arg for arg in child.args):
                    raise ProjectionUnsupported
                parts.append("server_name " + " ".join(_alias("name", arg) + ".invalid" if arg else '""' for arg in child.args) + ";")
            elif child.name in {"ssl", "include"}:
                raise ProjectionUnsupported
        parts.append("}")
        return "\n".join(parts)
    projected = render(http[0], "root") + "\n"
    # An exported HTTP skeleton without a server is not useful scope evidence.
    if not any(child.name == "server" and child.children is not None for child in http[0].children or ()):
        raise ProjectionUnsupported
    return projected
