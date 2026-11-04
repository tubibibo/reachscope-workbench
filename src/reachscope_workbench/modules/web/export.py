"""Spreadsheet-friendly Web inventory export; raw structured values remain in JSON."""

from __future__ import annotations

import csv
import io
import unicodedata
from typing import Any

from ...core.models import WorkbenchError

_FIELDS = (
    "url", "title", "status_code", "reachability_source", "server", "ip", "tech", "category",
    "fingerprint_confidence", "review_checks", "forms", "scripts", "body_sha256", "evidence_ids",
)


def spreadsheet_cell(value: object) -> str:
    """Quote CSV separately; neutralize common formula prefixes including NFKC forms.

    Spreadsheet programs differ. The apostrophe intentionally changes risky text;
    JSON is the lossless format. Exporting CSV does not guarantee safety after a
    spreadsheet application subsequently rewrites or strips these characters.
    """
    text = str(value) if value is not None else ""
    normalized = unicodedata.normalize("NFKC", text).lstrip(" \t\r\n\v\f\ufeff")
    if normalized.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def inventory_csv(job: dict[str, Any]) -> bytes:
    if job.get("module") != "web":
        raise WorkbenchError("MODULE_MISMATCH", "资产 CSV 仅适用于 Web 任务")
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(_FIELDS)
    result = job["result"]
    for asset in result["details"]["assets"]:
        page = asset.get("page") or {}
        checks = asset.get("checks", [])
        row = {
            **asset,
            "reachability_source": asset.get("reachability_source", "active_probe" if result["summary"]["mode"] == "probe" else "unknown"),
            "review_checks": sum(item.get("status") == "review" for item in checks) if "checks" in asset else None,
            "forms": page.get("counts", {}).get("forms"),
            "scripts": page.get("counts", {}).get("scripts"),
            "evidence_ids": ";".join(asset.get("evidence_ids", [])),
        }
        writer.writerow([spreadsheet_cell(row.get(field)) for field in _FIELDS])
    return output.getvalue().encode("utf-8-sig")
