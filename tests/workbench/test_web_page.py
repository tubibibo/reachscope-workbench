"""Passive page/Cookie extraction keeps scope, privacy and inventory bounds explicit."""

from __future__ import annotations

import json

import pytest

from reachscope_workbench.modules.web.cookies import COOKIE_LIMIT, cookie_metadata
from reachscope_workbench.modules.web.page import (
    FORM_LIMIT,
    INPUT_LIMIT,
    RESOURCE_LIMIT,
    page_inventory,
    reference_url,
)


def test_page_forms_resources_and_credentials_are_passive_metadata() -> None:
    body = b'''<html lang="en"><head><base href="/assets/"><meta name="description" content="A useful page">
    <link rel="canonical" href="https://user:private@example.test/catalog#heading">
    <link rel="stylesheet" href="style.css"></head><body>
    <script src="https://cdn.example.test/main.js"></script><script>doNotExecute()</script>
    <img src="http://images.example.test/one.png"><a href="http://docs.example.test/">Docs</a>
    <a href="javascript:alert(1)">Ignored</a><form method="POST" action="/login">
    <input name="username" value="SENSITIVE_FORM_VALUE"><input type="password" name="password" value="SENSITIVE_PASSWORD">
    <textarea name="note">SENSITIVE_TEXTAREA</textarea></form></body></html>'''
    page = page_inventory(body, "https://example.test/start", "text/html")
    assert page["analyzed"] and page["language"] == "en" and page["description"] == "A useful page"
    assert page["canonical"] == "https://example.test/catalog"
    assert page["forms"] == [{"action": "https://example.test/login", "method": "post", "password_fields": 1,
                              "input_names": ["username", "password", "note"], "external": False, "mixed_content": False}]
    assert page["stylesheets"][0]["url"] == "https://example.test/assets/style.css"
    assert page["scripts"][0]["external"] and page["counts"]["inline_scripts"] == 1
    assert page["images"][0]["mixed_content"] and page["counts"]["mixed_content"] == 1
    assert len(page["links"]) == 1 and not page["links"][0]["mixed_content"]
    assert all(value not in json.dumps(page) for value in ("SENSITIVE_FORM_VALUE", "SENSITIVE_PASSWORD", "SENSITIVE_TEXTAREA", "doNotExecute", "user:private"))


def test_default_form_action_is_document_not_base_and_unknown_method_defaults_get() -> None:
    page = page_inventory(b'<base href="https://other.test/"><form method="unknown"><input type="password"></form>',
                          "https://example.test/login?from=home", "text/html")
    assert page["forms"][0]["action"] == "https://example.test/login?from=home"
    assert page["forms"][0]["method"] == "get"


@pytest.mark.parametrize("body,content_type,encoding", [(b"{}", "application/json", "identity"),
                                                        (b"opaque", "text/html", "gzip"),
                                                        (b"\0\0binary", "text/html", "identity")])
def test_unparsed_content_does_not_acquire_fictitious_page_data(body: bytes, content_type: str, encoding: str) -> None:
    result = page_inventory(body, "https://example.test/", content_type, content_encoding=encoding)
    assert not result["analyzed"] and result["reason"] and not result["forms"] and not result["scripts"]


def test_page_lists_and_input_names_are_bounded_with_capture_gap() -> None:
    markup = '<form>' + '<input name="field">' * (INPUT_LIMIT + 5) + '</form>'
    markup += '<form action="/"></form>' * (FORM_LIMIT + 2)
    markup += '<script src="/a.js"></script>' * (RESOURCE_LIMIT + 2)
    page = page_inventory(markup.encode(), "https://example.test/", "text/html")
    assert page["truncated"] and len(page["forms"]) == FORM_LIMIT
    assert len(page["forms"][0]["input_names"]) == INPUT_LIMIT
    assert len(page["scripts"]) == RESOURCE_LIMIT and page["counts"]["scripts"] == RESOURCE_LIMIT + 2
    assert page_inventory(b"<html>", "https://example.test/", "text/html", truncated=True)["truncated"]


def test_invalid_charset_and_bad_references_do_not_break_inventory() -> None:
    page = page_inventory(b'<html lang="en">', "https://example.test/", "text/html", encoding="unknown-encoding")
    assert page["analyzed"] and page["language"] == "en"
    for value in ("javascript:alert(1)", "data:text/html,x", "https://example.test:99999/", "https://example.test/\r\nx", "https://[bad/"):
        assert not reference_url("https://example.test/", value)


def test_cookie_attributes_keep_expires_commas_and_omit_values() -> None:
    records = cookie_metadata([
        'session="SECRET; Path=VALUE_FRAGMENT"; Path=/; HttpOnly; SameSite=None; Secure',
        'preference=OTHER_SECRET; Expires=Wed, 21 Oct 2037 07:28:00 GMT; Domain=.example.test; Partitioned',
    ])
    assert len(records) == 2 and records[0]["path"] == "/" and records[0]["http_only"]
    assert records[0]["same_site"] == "none" and records[0]["secure"]
    assert records[1]["persistent"] and records[1]["partitioned"]
    assert all(secret not in json.dumps(records) for secret in ("SECRET", "VALUE_FRAGMENT", "OTHER_SECRET"))
    assert cookie_metadata(['session="unbalanced; Path=/']) == []
    assert cookie_metadata(['no-equals', 'invalid name=value', 'control=value\r\nHeader:x']) == []
    assert len(cookie_metadata(['s=value'] * (COOKIE_LIMIT + 2))) == COOKIE_LIMIT
