"""Bounded exact-URL HTTP observation; not a vulnerability or directory scanner."""

from __future__ import annotations

import asyncio
import hashlib
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from ... import __version__
from ...core.models import WorkbenchError
from .audit import audit_response
from .cookies import COOKIE_LIMIT, cookie_metadata
from .page import page_inventory
from .scope import normalize_url, redirect_in_scope, resolve_target

BODY_LIMIT = 512 * 1024
CHECKS = ("http", "headers", "page", "fingerprints")
_HEADERS = (
    "server", "content-type", "content-length", "location", "strict-transport-security",
    "content-security-policy", "x-content-type-options", "x-frame-options",
    "referrer-policy", "permissions-policy", "cache-control", "x-powered-by",
    "access-control-allow-origin", "access-control-allow-credentials",
    "content-security-policy-report-only",
    "x-reachscope-lab-session", "x-reachscope-lab-generation", "x-reachscope-lab-profile",
)


class _Title(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def html_title(data: bytes, encoding: str = "utf-8") -> str:
    parser = _Title()
    try:
        parser.feed(data.decode(encoding, errors="replace"))
    except (LookupError, ValueError):
        parser.feed(data.decode("utf-8", errors="replace"))
    return " ".join("".join(parser.parts).split())[:512]


def _preview(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding, errors="replace")
    except (LookupError, ValueError):
        # A peer can declare an unknown/non-text Python codec as charset. The
        # response still exists; fall back instead of turning it into a probe error.
        return data.decode("utf-8", errors="replace")


def _tls_info(response: httpx.Response) -> dict[str, Any] | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    ssl_object = stream.get_extra_info("ssl_object")
    if ssl_object is None:
        return None
    certificate = ssl_object.getpeercert()
    return {
        "version": ssl_object.version(),
        "cipher": ssl_object.cipher()[0] if ssl_object.cipher() else None,
        "not_after": certificate.get("notAfter"),
        "subject_alt_names": [name for kind, name in certificate.get("subjectAltName", ()) if kind == "DNS"][:20],
        "verification": "certificate-chain-and-hostname",
    }


async def _request(
    client: httpx.AsyncClient, url: str, addresses: list[str], timeout: float,
    checks: list[str] | None = None,
) -> dict[str, Any]:
    """Connect to a resolved IP while retaining original Host and TLS SNI.

    DNS is consulted exactly once per redirect hop. HTTPX/httpcore never performs
    a second hostname resolution for the connected target. No proxy env is used.
    """
    parsed = httpx.URL(url)
    selected = checks if checks is not None else list(CHECKS)
    last_error: Exception | None = None
    for address in addresses[:3]:
        pinned = parsed.copy_with(host=address)
        request = client.build_request("GET", pinned, headers={
            "Host": parsed.netloc.decode("ascii"),
            "User-Agent": f"ReachScope-Workbench/{__version__} (bounded-observation)",
            "Accept": "text/html,application/json;q=0.8,*/*;q=0.5",
            "Accept-Encoding": "identity",
        }, timeout=timeout)
        request.extensions["sni_hostname"] = parsed.host
        response: httpx.Response | None = None
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
            data = bytearray()
            truncated = False
            # Identity encoding keeps wire and body budgets aligned. Unexpected
            # compressed content is retained as a bounded opaque body, never expanded.
            async for chunk in response.aiter_raw(chunk_size=16384):
                remaining = BODY_LIMIT - len(data)
                if len(chunk) > remaining:
                    data.extend(chunk[:remaining])
                    truncated = True
                    break
                data.extend(chunk)
            body = bytes(data)
            encoding = response.encoding or "utf-8"
            content_encoding = response.headers.get("content-encoding", "identity").lower()
            is_html = "html" in response.headers.get("content-type", "").lower()
            record: dict[str, Any] = {
                "capture_schema": "web-response/2",
                "selected_checks": selected,
                "status_code": response.status_code,
                "http_version": response.http_version,
                "ip": address,
                "headers": {name: response.headers[name][:4096] for name in (_HEADERS if "headers" in selected else ("server", "content-type", "content-length", "location")) if name in response.headers},
                "headers_truncated": [name for name in (_HEADERS if "headers" in selected else ("server", "content-type", "content-length", "location")) if len(response.headers.get(name, "")) > 4096],
                "server": response.headers.get("server", "")[:512],
                "content_type": response.headers.get("content-type", "")[:512],
                "title": html_title(body, encoding) if ("page" in selected or "fingerprints" in selected) and is_html and content_encoding == "identity" else "",
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_bytes": len(body),
                "body_truncated": truncated,
                "hash_scope": "captured_prefix" if truncated else "captured_body",
                "body_preview": _preview(body[:2048], encoding) if is_html and content_encoding == "identity" else "",
                "content_encoding": content_encoding,
            }
            if "headers" in selected:
                cookie_headers = response.headers.get_list("set-cookie")
                cookies = cookie_metadata(cookie_headers)
                record.update(tls=_tls_info(response), cookies=cookies,
                              cookies_truncated=len(cookie_headers) > COOKIE_LIMIT or len(cookies) < min(len(cookie_headers), COOKIE_LIMIT))
            if "page" in selected:
                record["page"] = await asyncio.to_thread(page_inventory, body, url, response.headers.get("content-type", ""),
                                                        encoding=encoding, content_encoding=content_encoding, truncated=truncated)
            return record
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
        finally:
            if response is not None:
                await response.aclose()
    raise WorkbenchError("CONNECT_ERROR", f"Unable to connect to target ({type(last_error).__name__})")


async def probe_url(url: str, *, allow_private: bool, timeout: float, checks: list[str] | None = None) -> dict[str, Any]:
    selected = checks if checks is not None else list(CHECKS)
    original = normalize_url(url)
    start = time.perf_counter()
    current = original
    redirects: list[dict[str, Any]] = []
    try:
        # A total deadline also bounds slow streaming responses that never exceed a
        # socket's inactivity timeout. Certificate verification remains enabled.
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                verify=True, trust_env=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            ) as client:
                for hop in range(4):
                    addresses = await resolve_target(current, allow_private, timeout)
                    observed = await _request(client, current, addresses, timeout, selected)
                    location = observed["headers"].get("location")
                    if observed["status_code"] in {301, 302, 303, 307, 308} and location:
                        if "location" in observed["headers_truncated"]:
                            # Never interpret a captured prefix as a destination
                            # supplied by the server. Preserve this response only.
                            observed["redirect_stopped"] = "location_truncated"
                            break
                        destination = normalize_url(urljoin(current, location))
                        redirects.append({"from": current, "to": destination, "status_code": observed["status_code"]})
                        if not redirect_in_scope(original, destination):
                            observed["redirect_stopped"] = "out_of_scope"
                            break
                        if hop == 3:
                            observed["redirect_stopped"] = "limit"
                            break
                        current = destination
                        continue
                    break
        result = {
            "url": original, "final_url": current, "reachable": True,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
            "redirects": redirects, **observed,
        }
        if "headers" in selected or "page" in selected:
            result["checks"] = audit_response(result, groups=set(selected) & {"headers", "page"})
        return result
    except (WorkbenchError, httpx.HTTPError, TimeoutError, OSError, LookupError) as exc:
        result = {
            "url": original, "final_url": current, "reachable": False,
            "status_code": None, "title": "", "server": "", "headers": {},
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
            "redirects": redirects,
            "error": {"code": exc.code if isinstance(exc, WorkbenchError) else "TIMEOUT" if isinstance(exc, TimeoutError) else "HTTP_ERROR",
                      "message": str(exc)[:512] or type(exc).__name__},
        }
        result["selected_checks"] = selected
        if "headers" in selected or "page" in selected:
            result["checks"] = audit_response(result, groups=set(selected) & {"headers", "page"})
        return result
