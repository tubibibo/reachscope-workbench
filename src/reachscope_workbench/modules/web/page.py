"""Bounded passive HTML inventory. References are data, never additional requests."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

RESOURCE_LIMIT = 80
FORM_LIMIT = 30
INPUT_LIMIT = 40
_KINDS = ("scripts", "stylesheets", "links", "images")


def _text(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def reference_url(base: str, value: str) -> str:
    """Retain only HTTP(S) references and remove userinfo and fragments."""
    if len(value) > 4096 or any(ord(char) < 32 for char in value) or "\\" in value:
        return ""
    try:
        parsed = urlsplit(urljoin(base, value.strip()))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or "%" in parsed.hostname:
            return ""
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None:
            if not 1 <= parsed.port <= 65535:
                return ""
            authority += f":{parsed.port}"
        return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))[:4096]
    except (ValueError, UnicodeError):
        return ""


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class _Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base = ""
        self.language = ""
        self.description = ""
        self.canonical = ""
        self.resources: dict[str, list[str]] = {kind: [] for kind in _KINDS}
        self.forms: list[dict[str, Any]] = []
        self.current_form: dict[str, Any] | None = None
        self.counts = dict.fromkeys((*_KINDS, "forms", "password_fields", "inline_scripts"), 0)
        self.truncated = False

    def _resource(self, kind: str, value: str) -> None:
        self.counts[kind] += 1
        if len(self.resources[kind]) < RESOURCE_LIMIT:
            self.resources[kind].append(value[:4097])
        else:
            self.truncated = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "html" and not self.language:
            self.language = _text(attributes.get("lang", ""), 80)
        elif tag == "base" and not self.base and attributes.get("href"):
            self.base = attributes["href"][:4097]
        elif tag == "meta" and attributes.get("name", "").lower() == "description" and not self.description:
            self.description = _text(attributes.get("content", ""), 1024)
        elif tag == "link":
            rel = attributes.get("rel", "").lower().split()
            if "canonical" in rel and not self.canonical:
                self.canonical = attributes.get("href", "")[:4097]
            if "stylesheet" in rel and attributes.get("href"):
                self._resource("stylesheets", attributes["href"])
        elif tag == "script":
            if attributes.get("src"):
                self._resource("scripts", attributes["src"])
            else:
                self.counts["inline_scripts"] += 1
        elif tag in {"a", "area"} and attributes.get("href"):
            self._resource("links", attributes["href"])
        elif tag == "img" and attributes.get("src"):
            self._resource("images", attributes["src"])
        elif tag == "form":
            self.counts["forms"] += 1
            method = attributes.get("method", "get").lower().strip()
            form: dict[str, Any] = {"action": attributes.get("action", "")[:4097],
                                    "method": method if method in {"get", "post", "dialog"} else "get",
                                    "password_fields": 0, "input_names": []}
            if len(self.forms) < FORM_LIMIT:
                self.forms.append(form)
                self.current_form = form
            else:
                self.current_form = None
                self.truncated = True
        elif tag in {"input", "textarea", "select", "button"}:
            password = tag == "input" and attributes.get("type", "").lower() == "password"
            self.counts["password_fields"] += int(password)
            if self.current_form is not None:
                self.current_form["password_fields"] += int(password)
                name = _text(attributes.get("name", ""), 100)
                if name and len(self.current_form["input_names"]) < INPUT_LIMIT:
                    self.current_form["input_names"].append(name)
                elif name:
                    self.truncated = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current_form = None


def page_inventory(
    body: bytes, url: str, content_type: str, *, encoding: str = "utf-8",
    content_encoding: str = "identity", truncated: bool = False,
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "analyzed": False, "reason": "响应不是 HTML", "language": "", "description": "", "canonical": "",
        "base_url": url, "forms": [], **{kind: [] for kind in _KINDS},
        "counts": dict.fromkeys((*_KINDS, "forms", "password_fields", "inline_scripts", "external_scripts", "mixed_content"), 0),
        "truncated": truncated,
    }
    if "html" not in content_type.lower():
        return empty
    if content_encoding.lower().strip() not in {"", "identity"}:
        return {**empty, "reason": "压缩响应按原始字节保留，未展开解析"}
    try:
        decoded = body.decode(encoding, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")
    if "\x00" in decoded[:8192]:
        return {**empty, "reason": "响应含二进制特征，未按 HTML 解析"}
    parser = _Inventory()
    try:
        parser.feed(decoded)
        parser.close()
    except (ValueError, RecursionError):
        return {**empty, "reason": "HTML 解析未完成", "truncated": True}
    base = reference_url(url, parser.base) if parser.base else url
    base = base or url
    page_origin = _origin(url)

    def resource(value: str, kind: str) -> dict[str, Any] | None:
        reference = reference_url(base, value)
        if not reference:
            return None
        return {"url": reference, "external": _origin(reference) != page_origin,
                "mixed_content": kind != "links" and page_origin[0] == "https" and reference.startswith("http://")}

    resources = {kind: [record for value in parser.resources[kind] if (record := resource(value, kind)) is not None]
                 for kind in _KINDS}
    for form in parser.forms:
        # Missing/empty form action is the document URL rather than <base>.
        action = reference_url(base, form["action"]) if form["action"] else reference_url(url, url)
        form["action"] = action
        form["external"] = bool(action and _origin(action) != page_origin)
        form["mixed_content"] = bool(action and page_origin[0] == "https" and action.startswith("http://"))
    counts = {**parser.counts, "external_scripts": sum(row["external"] for row in resources["scripts"]),
              "mixed_content": sum(row["mixed_content"] for kind in ("scripts", "stylesheets", "images") for row in resources[kind])}
    return {"analyzed": True, "reason": "仅解析已采集 HTML；未加载资源或提交表单", "language": parser.language,
            "description": parser.description, "canonical": reference_url(base, parser.canonical) if parser.canonical else "",
            "base_url": base, "forms": parser.forms, **resources, "counts": counts,
            "truncated": truncated or parser.truncated}
