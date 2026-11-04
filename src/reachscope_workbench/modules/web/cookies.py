"""Retain bounded Set-Cookie attribute metadata, never Cookie values/raw headers."""

from __future__ import annotations

import re
from typing import Any

COOKIE_LIMIT = 50
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")


def _segments(raw: str) -> list[str]:
    # Attribute separators inside a quoted Cookie value are not attributes.
    # Do not accidentally retain a piece of that value as Path or Domain.
    if len(raw) > 16384 or any(ord(char) < 32 for char in raw):
        return []
    parts, start, quoted, escaped = [], 0, False, False
    for position, char in enumerate(raw):
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            parts.append(raw[start:position])
            start = position + 1
    if quoted:
        return []
    return [*parts, raw[start:]]


def cookie_metadata(headers: list[str]) -> list[dict[str, Any]]:
    output = []
    for raw in headers[:COOKIE_LIMIT]:
        parts = _segments(raw)
        if not parts:
            continue
        name, separator, _ = parts[0].partition("=")
        name = name.strip()
        if not separator or not _TOKEN.fullmatch(name):
            continue
        attributes = {}
        for part in parts[1:]:
            key, _, value = part.strip().partition("=")
            attributes[key.lower()] = value.strip().strip('"')
        same_site = attributes.get("samesite", "").lower()
        output.append({
            "name": name, "secure": "secure" in attributes, "http_only": "httponly" in attributes,
            "same_site": same_site if same_site in {"lax", "strict", "none", ""} else "invalid",
            "domain": attributes.get("domain", "")[:255], "path": attributes.get("path", "")[:512],
            "partitioned": "partitioned" in attributes,
            "prefix": "__Host-" if name.startswith("__Host-") else "__Secure-" if name.startswith("__Secure-") else "",
            "persistent": "expires" in attributes or "max-age" in attributes,
        })
    return output
