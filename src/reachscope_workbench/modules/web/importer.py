"""Bounded HTTP website records from generic, httpx and Nuclei input files."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ...core.models import WorkbenchError
from .legacy.models import Asset, guess_protocol
from .scope import normalize_url

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ASSETS = 5000


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key, value in pairs:
        if key in record:
            raise WorkbenchError("INVALID_IMPORT", "JSON contains duplicate fields; asset identity would be ambiguous")
        record[key] = value
    return record


def _json_constant(_: str) -> None:
    raise WorkbenchError("INVALID_IMPORT", "JSON must not contain NaN or Infinity")


def _validate_structure(value: Any) -> None:
    """Bound text conversion and reject strings that cannot be saved as UTF-8."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 200000 or depth > 35:
            raise WorkbenchError("IMPORT_LIMIT", "Asset data exceeds the node or nesting-depth budget")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError as exc:
                raise WorkbenchError("INVALID_IMPORT", "Asset strings must contain valid Unicode characters") from exc


def _status_code(value: Any) -> int | None:
    # str.isdigit also accepts superscript digits, which int() cannot parse.
    # Require an ordinary three-digit HTTP status instead of trusting that predicate.
    if type(value) is int:
        return value if 100 <= value <= 599 else None
    if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isdecimal():
        number = int(value)
        return number if 100 <= number <= 599 else None
    return None


def _text(value: object, limit: int = 4096) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:20])[:limit]
    if value is None:
        return ""
    return str(value)[:limit].strip()


def _first(record: dict[str, Any], *keys: str) -> str:
    return next((_text(record[key]) for key in keys if record.get(key) is not None and _text(record[key])), "")


def _records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        if any(not isinstance(record, dict) for record in data):
            raise WorkbenchError("INVALID_IMPORT", "Each asset record must be a JSON object")
        return data
    if isinstance(data, dict):
        for key in ("results", "assets", "data", "items"):
            values = data.get(key)
            if isinstance(values, list):
                if values and isinstance(values[0], list):
                    columns = ("host", "ip", "port", "title", "server")
                    if any(not isinstance(record, list) for record in values):
                        raise WorkbenchError("INVALID_IMPORT", "FOFA rows must be arrays")
                    return [dict(zip(columns, record)) for record in values]
                return _records(values)
        if any(key in data for key in ("host", "url", "matched-at", "hostname", "domain")):
            return [data]
    raise WorkbenchError("INVALID_IMPORT", "Expected an asset object, array or results/assets/data/items array")


def parse_import(data: bytes, filename: str) -> tuple[list[Asset], list[dict[str, Any]], list[str]]:
    if len(data) > MAX_IMPORT_BYTES:
        raise WorkbenchError("IMPORT_LIMIT", "Asset import is limited to 2 MiB")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".json", ".csv", ".jsonl", ".ndjson"}:
        raise WorkbenchError("INVALID_IMPORT", "Use JSON, CSV or JSONL asset files")
    try:
        text = data.decode("utf-8-sig")
        if suffix == ".csv":
            reader = csv.DictReader(io.StringIO(text), strict=True)
            if not reader.fieldnames:
                raise ValueError("CSV headers are missing")
            records: list[dict[str, Any]] = [dict(record) for record in reader]
        elif suffix in {".jsonl", ".ndjson"}:
            records = []
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line, object_pairs_hook=_json_object, parse_constant=_json_constant)
                except ValueError as exc:
                    raise WorkbenchError("INVALID_IMPORT", f"Invalid JSONL at line {number}") from exc
                if not isinstance(record, dict):
                    raise WorkbenchError("INVALID_IMPORT", f"Line {number} must contain an object")
                records.append(record)
        else:
            records = _records(json.loads(text, object_pairs_hook=_json_object, parse_constant=_json_constant))
    except (UnicodeError, ValueError, csv.Error, RecursionError) as exc:
        raise WorkbenchError("INVALID_IMPORT", f"Cannot parse asset file: {exc}") from exc
    if len(records) > MAX_ASSETS:
        raise WorkbenchError("IMPORT_LIMIT", f"At most {MAX_ASSETS} asset records are accepted")
    _validate_structure(records)
    assets: list[Asset] = []
    imported: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, record in enumerate(records, 1):
        location = _first(record, "url", "matched-at", "matched_at", "host", "hostname", "domain", "target", "input")
        if not location:
            warnings.append(f"Record {index}: no host/url/domain; skipped")
            continue
        raw_info = record.get("info")
        info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
        status = record.get("status_code", record.get("status-code"))
        status_code = _status_code(status)
        try:
            parsed = urlsplit(location if "://" in location else "//" + location)
            hostname = parsed.hostname or ""
            if not hostname or parsed.username or parsed.password:
                raise ValueError("invalid host")
            parsed_port = parsed.port
            port = _first(record, "port") or (str(parsed_port) if parsed_port is not None else "")
            if port and (not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535):
                raise ValueError("invalid port")
            if parsed_port is not None and port and int(port) != parsed_port:
                raise ValueError("conflicting port")
            declared_protocol = _first(record, "scheme", "protocol").lower()
            protocol = parsed.scheme.lower() or declared_protocol
            if declared_protocol and declared_protocol not in {"http", "https"}:
                raise ValueError("non-HTTP protocol")
            if parsed.scheme and declared_protocol and parsed.scheme.lower() != declared_protocol:
                raise ValueError("conflicting HTTP scheme")
            inferred = not protocol
            if not protocol:
                guessed = guess_protocol(port)
                if guessed in {"http", "https"}:
                    protocol = guessed
                elif port and status_code is None:
                    raise ValueError("port has no HTTP website evidence")
                else:
                    protocol = "http"
            if protocol not in {"http", "https"}:
                raise ValueError("non-HTTP URL")
            authority = f"[{hostname}]" if ":" in hostname else hostname
            if port:
                authority += f":{port}"
            website_url = normalize_url(urlunsplit((protocol, authority, parsed.path or "/", parsed.query, "")))
        except (ValueError, WorkbenchError):
            warnings.append(f"Record {index}: invalid or non-HTTP(S) website URL/port; skipped")
            continue
        if not port and protocol in {"http", "https"}:
            port = "443" if protocol == "https" else "80"
        normalized_host = urlsplit(website_url).hostname or hostname
        title = _first(record, "title", "name") or _text(info.get("name"))
        server = _first(record, "webserver", "web-server", "server", "banner", "product", "tech")
        asset = Asset(
            host=normalized_host[:512], ip=_first(record, "ip", "address", "a")[:512],
            port=port, title=title[:512], server=server[:512], protocol=protocol[:32],
        )
        assets.append(asset)
        if status is not None and status_code is None:
            warnings.append(f"Record {index}: invalid HTTP status; preserved asset without a historical response status")
        finding = None
        if record.get("template-id") or record.get("templateID"):
            finding = {
                "template_id": _first(record, "template-id", "templateID")[:512],
                "name": _text(info.get("name"), 512),
                "severity": _text(info.get("severity"), 32),
                "matcher_name": _first(record, "matcher-name", "matcher_name")[:512],
                "verified": False,
            }
        imported.append({
            "url": website_url, "input_location": location[:4096], "url_inferred": inferred, "status_code": status_code,
            "reachable": status_code is not None, "reachability_source": "imported_unverified",
            "record": index, "format": "nuclei" if finding else "httpx_or_asset",
            "imported_finding": finding,
        })
    if not assets:
        raise WorkbenchError("INVALID_IMPORT", "No usable HTTP(S) website records found; non-Web services are not website inputs")
    return assets, imported, warnings
