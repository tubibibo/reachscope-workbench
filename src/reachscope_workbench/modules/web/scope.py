"""URL validation and pinned DNS addresses for a bounded, explicit target scope."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from ...core.models import WorkbenchError

_METADATA_NAMES = {"metadata.google.internal", "metadata", "instance-data.ec2.internal"}


def normalize_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise WorkbenchError("INVALID_TARGET", "A target must be an HTTP(S) URL without whitespace")
    try:
        value.encode("utf-8")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or "\\" in value or "%" in parsed.hostname
        ):
            raise ValueError("unsupported URL")
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if not hostname:
            raise ValueError("empty normalized hostname")
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("invalid port")
        if hostname in _METADATA_NAMES:
            raise ValueError("metadata endpoint")
        formatted = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None:
            formatted += f":{port}"
        return urlunsplit((parsed.scheme, formatted, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise WorkbenchError("INVALID_TARGET", "Only exact HTTP(S) URLs without credentials are supported") from exc


def permitted_address(address: str, allow_private: bool) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # Metadata/link-local, unspecified and multicast are never ordinary target endpoints.
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    if str(ip) in {"100.100.100.200", "168.63.129.16"}:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return permitted_address(str(ip.ipv4_mapped), allow_private)
    return allow_private or ip.is_global


async def resolve_target(url: str, allow_private: bool, timeout: float) -> list[str]:
    hostname = urlsplit(url).hostname
    assert hostname is not None
    try:
        literal = str(ipaddress.ip_address(hostname))
        addresses = [literal]
    except ValueError:
        try:
            resolved = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM),
                timeout=timeout,
            )
        except (OSError, TimeoutError) as exc:
            raise WorkbenchError("DNS_ERROR", f"Could not resolve target host {hostname}") from exc
        addresses = list(dict.fromkeys(str(item[4][0]) for item in resolved))
    if not addresses or any(not permitted_address(address, allow_private) for address in addresses):
        raise WorkbenchError("OUT_OF_SCOPE", "Target DNS includes an address outside the selected network scope")
    return addresses


def redirect_in_scope(original: str, destination: str) -> bool:
    first, target = urlsplit(original), urlsplit(destination)
    if first.hostname != target.hostname:
        return False
    first_port = first.port or (443 if first.scheme == "https" else 80)
    target_port = target.port or (443 if target.scheme == "https" else 80)
    return (first.scheme == target.scheme and first_port == target_port) or (
        first.scheme == "http" and first_port == 80 and target.scheme == "https" and target_port == 443
    )
