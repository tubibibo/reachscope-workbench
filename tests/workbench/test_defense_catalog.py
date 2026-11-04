"""Public guidance is stable data, not an executable or observed detection claim."""

from __future__ import annotations

import ast
import inspect
import json
from urllib.parse import urlsplit

import pytest

from reachscope_workbench.core import defense_catalog

_IDS = (
    "web.tls", "web.csp", "web.frame", "web.cookies", "web.cors", "web.mixed_content", "web.forms",
    "web.mime", "web.referrer", "app.input_validation", "app.access_control", "ops.logging", "ops.patching", "endpoint.hygiene",
)
_FIELDS = {"id", "title", "category", "applicability", "red_review", "blue_actions", "verification", "limitations", "references", "signals"}
_SIGNALS = {"hsts", "tls_expiry", "csp", "frame_protection", "cookie_secure", "cookie_http_only", "cookie_same_site",
            "cors", "mixed_content", "password_forms", "nosniff", "referrer_policy"}


def test_catalogue_has_exact_stable_ids_and_json_schema() -> None:
    rows = defense_catalog.catalog()
    assert tuple(row["id"] for row in rows) == _IDS
    assert len(rows) == len({row["id"] for row in rows}) == 14
    assert json.loads(json.dumps(rows, ensure_ascii=False)) == rows
    assert len(json.dumps(rows, ensure_ascii=False).encode("utf-8")) < 64 * 1024
    for row in rows:
        assert set(row) == _FIELDS
        for field in ("id", "title", "category", "applicability"):
            assert isinstance(row[field], str) and 0 < len(row[field]) <= 120
        for field in ("red_review", "blue_actions", "verification", "limitations"):
            assert isinstance(row[field], list) and 1 <= len(row[field]) <= 4
            assert all(isinstance(text, str) and 0 < len(text) <= 500 for text in row[field])
        assert isinstance(row["signals"], list) and len(set(row["signals"])) == len(row["signals"])
        assert set(row["signals"]) <= _SIGNALS
        assert row["applicability"] in {"web_config", "manual_review", "endpoint_hygiene"}


@pytest.mark.parametrize("identifier", _IDS)
def test_every_control_has_only_attributed_public_references(identifier: str) -> None:
    row = next(item for item in defense_catalog.catalog() if item["id"] == identifier)
    assert 1 <= len(row["references"]) <= 3
    assert len({ref["url"] for ref in row["references"]}) == len(row["references"])
    for ref in row["references"]:
        assert set(ref) == {"title", "url", "kind"}
        assert isinstance(ref["title"], str) and 0 < len(ref["title"]) < 200
        parsed = urlsplit(ref["url"])
        assert parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        if ref["kind"] == "owasp_guidance":
            assert parsed.hostname == "cheatsheetseries.owasp.org" and parsed.path.startswith("/cheatsheets/")
        else:
            assert ref["kind"] == "vendor_public_overview" and parsed.hostname == "support.kaspersky.com"
            assert parsed.path in {"/KESWin/11/en-US/128016.htm", "/keswin/11.5.0/en-US/151109.htm", "/KESWin/11.4.0/en-US/173855.htm"}


def test_manual_and_endpoint_guidance_never_advertise_observed_web_signals() -> None:
    rows = {row["id"]: row for row in defense_catalog.catalog()}
    assert {signal for row in rows.values() for signal in row["signals"]} == _SIGNALS
    for identifier in _IDS[:9]:
        assert rows[identifier]["applicability"] == "web_config" and rows[identifier]["signals"]
    for identifier in _IDS[9:13]:
        assert rows[identifier]["applicability"] == "manual_review" and rows[identifier]["signals"] == []
    endpoint = rows["endpoint.hygiene"]
    assert endpoint["applicability"] == "endpoint_hygiene" and endpoint["signals"] == []
    assert any("专有规则" in text for text in endpoint["limitations"])
    assert any("不是杀毒软件" in text for text in endpoint["limitations"])
    assert all("授权" in row["red_review"][0] or "批准" in row["red_review"][0] for row in rows.values())


def test_mutating_a_response_cannot_change_catalogue_or_other_references() -> None:
    expected = defense_catalog.catalog()
    mutated = defense_catalog.catalog()
    mutated[0]["title"] = "untrusted replacement"
    mutated[0]["signals"].append("fabricated")
    mutated[0]["blue_actions"].clear()
    mutated[0]["references"][0]["url"] = "https://untrusted.invalid/"
    mutated.append({"id": "invented"})
    assert defense_catalog.catalog() == expected


def test_core_catalogue_has_no_http_api_modules_or_io_dependencies() -> None:
    tree = ast.parse(inspect.getsource(defense_catalog))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "compile", "__import__"}
    assert set(imported) <= {"__future__", "copy", "typing"}
