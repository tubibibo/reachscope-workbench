"""Configuration outcomes describe captured evidence, never verified vulnerabilities."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from reachscope_workbench.modules.web.audit import audit_response


def _record(**changes: Any) -> dict[str, Any]:
    return {
        "reachable": True, "final_url": "https://example.test/page", "content_type": "text/html",
        "headers": {"content-security-policy": "default-src 'self'; frame-ancestors 'none'",
                    "x-content-type-options": "nosniff", "referrer-policy": "strict-origin-when-cross-origin",
                    "strict-transport-security": "max-age=31536000"},
        "tls": None, "cookies": [],
        "page": {"analyzed": True, "forms": [], "scripts": [], "stylesheets": [], "images": [],
                 "links": [], "counts": {}, "truncated": False},
        **changes,
    }


def _by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {rule["id"]: rule for rule in audit_response(record)}


def _cookie(**changes: Any) -> dict[str, Any]:
    return {"name": "session", "secure": True, "http_only": True, "same_site": "lax",
            "domain": "", "path": "/", "partitioned": False, **changes}


def test_unreachable_is_not_evaluated_as_missing_security_configuration() -> None:
    rules = audit_response({"reachable": False, "headers": {}, "error": {"code": "TIMEOUT"}})
    assert len(rules) == 1
    assert rules[0]["id"] == "response_unavailable"
    assert rules[0]["status"] == "info"


def test_rule_schema_is_stable_json_and_does_not_mutate_input() -> None:
    record = _record(cookies=[_cookie()])
    before = copy.deepcopy(record)
    rules = audit_response(record)
    assert record == before
    assert len(rules) == len({rule["id"] for rule in rules}) == 12
    assert all(set(rule) == {"id", "title", "status", "severity", "description", "recommendation", "evidence"} for rule in rules)
    assert {rule["status"] for rule in rules} <= {"pass", "review", "info", "not_applicable"}
    json.dumps(rules)
    indexed = {rule["id"]: rule for rule in rules}
    for name in ("csp", "frame_protection", "nosniff", "hsts", "referrer_policy", "cookie_secure", "cookie_http_only", "cookie_same_site"):
        assert indexed[name]["status"] == "pass"
    assert indexed["tls_expiry"]["status"] == "not_applicable"


def test_json_does_not_inherit_html_configuration_requirements() -> None:
    rules = _by_id(_record(content_type="application/json", headers={}, page={"analyzed": False}))
    for name in ("csp", "frame_protection", "referrer_policy", "password_forms", "mixed_content"):
        assert rules[name]["status"] == "not_applicable"
    assert rules["cors"]["status"] == "info"


@pytest.mark.parametrize("value", ["", "not-a-directive", "default-src 'broken'", "script-src 'unsafe-inline'", "script-src 'unsafe-eval'", "default-src *", "script-src https://*", "script-src data:"])
def test_csp_missing_unrecognised_or_permissive_values_require_review(value: str) -> None:
    rule = _by_id(_record(headers={"content-security-policy": value}))["csp"]
    assert rule["status"] == "review"


def test_report_only_and_frame_src_do_not_implement_ancestor_protection() -> None:
    rules = _by_id(_record(headers={
        "content-security-policy-report-only": "default-src 'self'; frame-ancestors 'none'",
        "content-security-policy": "frame-src 'none'",
    }))
    assert rules["csp"]["evidence"]["report_only_present"]
    assert rules["frame_protection"]["status"] == "review"
    missing = _by_id(_record(headers={"content-security-policy-report-only": "default-src 'none'"}))
    assert missing["csp"]["status"] == "review"


def test_csp_exact_tokens_duplicates_nonce_and_multiple_policies() -> None:
    rule = _by_id(_record(headers={
        "Content-Security-Policy": "script-src 'nonce-YWJjZA==' 'strict-dynamic' 'unsafe-inline' *; script-src 'unsafe-eval', frame-ancestors 'none'",
    }))["csp"]
    assert rule["status"] == "pass"
    assert rule["evidence"]["policy_count"] == 2
    literal = _by_id(_record(headers={"content-security-policy": "script-src https://unsafe-inline.example"}))["csp"]
    assert literal["status"] == "pass"


@pytest.mark.parametrize(("headers", "expected"), [
    ({"X-Frame-Options": "  SAMEORIGIN "}, "pass"),
    ({"x-frame-options": "DENY"}, "pass"),
    ({"x-frame-options": "ALLOW-FROM https://trusted.test"}, "review"),
    ({"x-frame-options": "DENY, SAMEORIGIN"}, "review"),
    ({"content-security-policy": "frame-ancestors https://trusted.test"}, "pass"),
    ({"content-security-policy": "frame-ancestors 'unsafe-inline'", "x-frame-options": "DENY"}, "review"),
    ({"content-security-policy": "frame-ancestors *", "x-frame-options": "DENY"}, "review"),
    ({"content-security-policy": "frame-ancestors https://*", "x-frame-options": "DENY"}, "review"),
    ({"content-security-policy": "frame-ancestors https:", "x-frame-options": "DENY"}, "review"),
    ({"content-security-policy": "frame-ancestors *; frame-ancestors 'none'"}, "review"),
    ({"content-security-policy": "frame-ancestors *, frame-ancestors 'none'"}, "pass"),
])
def test_ancestor_policy_and_valid_xfo_only(headers: dict[str, str], expected: str) -> None:
    assert _by_id(_record(headers=headers))["frame_protection"]["status"] == expected


@pytest.mark.parametrize(("value", "expected"), [("nosniff", "pass"), ("NoSnIfF", "pass"), ("nosniff, nosniff", "review"), ("", "review"), ("nosniff; yes", "review")])
def test_nosniff_requires_a_recognised_value(value: str, expected: str) -> None:
    assert _by_id(_record(headers={"x-content-type-options": value}))["nosniff"]["status"] == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("max-age=31536000; includeSubDomains", "pass"), ("max-age=1", "pass"),
    ('max-age="300"', "pass"), ("max-age=0", "review"), ("max-age=-1", "review"),
    ("max-age=100years", "review"), ("max-age=1.5", "review"),
    ("max-age=300; max-age=300", "review"), ("includeSubDomains", "review"),
    ("max-age=300, max-age=500", "review"), ("", "review"),
])
def test_hsts_valid_positive_age_on_https(value: str, expected: str) -> None:
    assert _by_id(_record(headers={"strict-transport-security": value}))["hsts"]["status"] == expected


def test_hsts_not_applied_to_plain_http() -> None:
    assert _by_id(_record(final_url="http://example.test/"))["hsts"]["status"] == "not_applicable"


@pytest.mark.parametrize("url", ["https://192.0.2.1/", "https://[2001:db8::1]/", "https://127.0.0.1:8443/"])
@pytest.mark.parametrize("headers", [{}, {"strict-transport-security": "max-age=31536000"}])
def test_hsts_not_applied_to_https_ip_literals(url: str, headers: dict[str, str]) -> None:
    rule = _by_id(_record(final_url=url, headers=headers))["hsts"]
    assert rule["status"] == "not_applicable"
    assert rule["evidence"]["hostname"]
    assert "IP" in rule["description"]


@pytest.mark.parametrize(("value", "expected", "effective"), [
    ("", "info", None), ("invalid", "review", None), ("unsafe-url", "review", "unsafe-url"),
    ("no-referrer, strict-origin-when-cross-origin", "pass", "strict-origin-when-cross-origin"),
    ("no-referrer, unsupported-future-policy", "pass", "no-referrer"),
    ("strict-origin-when-cross-origin, unsafe-url", "review", "unsafe-url"),
])
def test_referrer_policy_uses_last_recognised_value(value: str, expected: str, effective: str | None) -> None:
    rule = _by_id(_record(headers={"referrer-policy": value}))["referrer_policy"]
    assert rule["status"] == expected
    assert rule["evidence"]["effective_policy"] == effective


@pytest.mark.parametrize(("headers", "expected"), [
    ({}, "info"), ({"access-control-allow-origin": "*"}, "info"),
    ({"access-control-allow-origin": "*", "access-control-allow-credentials": "true"}, "review"),
    ({"access-control-allow-origin": "https://trusted.test", "access-control-allow-credentials": "true"}, "info"),
    ({"access-control-allow-origin": "https://trusted.test, https://other.test"}, "review"),
    ({"access-control-allow-origin": "null"}, "review"),
    ({"access-control-allow-origin": "https://trusted.test/path"}, "review"),
    ({"access-control-allow-origin": "https://trusted.test", "access-control-allow-credentials": "TRUE"}, "review"),
    ({"access-control-allow-credentials": "true"}, "review"),
])
def test_cors_is_only_configuration_observation(headers: dict[str, str], expected: str) -> None:
    rule = _by_id(_record(headers=headers))["cors"]
    assert rule["status"] == expected
    assert not rule["evidence"]["origin_variation_tested"]
    if headers.get("access-control-allow-origin") == "*" and headers.get("access-control-allow-credentials") == "true":
        assert "拒绝" in rule["description"]


def test_cookie_checks_preserve_only_metadata_and_are_not_blanket_session_verdicts() -> None:
    record = _record(cookies=[_cookie(value="DO-NOT-KEEP"), _cookie(name="preferences", secure=False, http_only=False, same_site="none")])
    rules = _by_id(record)
    for name in ("cookie_secure", "cookie_http_only", "cookie_same_site"):
        assert rules[name]["status"] == "review"
        assert rules[name]["evidence"]["affected"][0]["name"] == "preferences"
        assert "DO-NOT-KEEP" not in json.dumps(rules[name])
        assert "value" not in rules[name]["evidence"]["cookies"][0]


@pytest.mark.parametrize(("same_site", "secure", "expected"), [
    ("lax", True, "pass"), ("Strict", True, "pass"), ("None", True, "pass"),
    ("none", False, "review"), ("", True, "review"), ("invalid", True, "review"),
])
def test_cookie_same_site_none_requires_secure(same_site: str, secure: bool, expected: str) -> None:
    assert _by_id(_record(cookies=[_cookie(same_site=same_site, secure=secure)]))["cookie_same_site"]["status"] == expected


def test_no_cookies_not_applicable_and_truncated_cookie_list_never_passes() -> None:
    names = ("cookie_secure", "cookie_http_only", "cookie_same_site")
    assert all(_by_id(_record())[name]["status"] == "not_applicable" for name in names)
    for cookies in ([], [_cookie()]):
        assert all(_by_id(_record(cookies=cookies, cookies_truncated=True))[name]["status"] == "info" for name in names)
    assert _by_id(_record(cookies=[_cookie(secure=False)], cookies_truncated=True))["cookie_secure"]["status"] == "review"


def test_password_get_and_http_action_checked_without_submit() -> None:
    record = _record()
    record["page"]["forms"] = [
        {"action": "/login", "method": "POST", "password_fields": 1},
        {"action": "/login", "method": "get", "password_fields": 1},
        {"action": "http://example.test/login", "method": "post", "password_fields": 2},
        {"action": "http://example.test/login", "method": "dialog", "password_fields": 1},
        {"action": "http://example.test/search", "method": "get", "password_fields": 0},
    ]
    rule = _by_id(record)["password_forms"]
    assert rule["status"] == "review"
    assert [form["index"] for form in rule["evidence"]["affected"]] == [1, 2]
    assert rule["evidence"]["password_form_count"] == 4


def test_password_forms_missing_method_is_get_and_secure_post_passes() -> None:
    record = _record()
    record["page"]["forms"] = [{"action": "", "password_fields": 1}]
    assert _by_id(record)["password_forms"]["status"] == "review"
    record["page"]["forms"][0]["method"] = "post"
    assert _by_id(record)["password_forms"]["status"] == "pass"


def test_mixed_content_includes_images_but_not_http_navigation_links() -> None:
    record = _record()
    record["page"]["links"] = [{"url": "http://example.test/link", "mixed_content": True}]
    assert _by_id(record)["mixed_content"]["status"] == "pass"
    record["page"]["scripts"] = [{"url": "http://example.test/script.js", "mixed_content": True}]
    record["page"]["stylesheets"] = [{"url": "https://example.test/style.css"}]
    record["page"]["images"] = [{"url": "http://example.test/image.png", "mixed_content": True}]
    rule = _by_id(record)["mixed_content"]
    assert rule["status"] == "review"
    assert {resource["kind"] for resource in rule["evidence"]["resources"]} == {"scripts", "images"}
    record["final_url"] = "http://example.test/page"
    assert _by_id(record)["mixed_content"]["status"] == "not_applicable"


def test_truncated_html_inventory_cannot_produce_negative_page_pass() -> None:
    record = _record()
    record["page"]["truncated"] = True
    rules = _by_id(record)
    assert rules["password_forms"]["status"] == rules["mixed_content"]["status"] == "info"
    assert rules["csp"]["status"] == "pass"
    record["page"]["scripts"] = [{"url": "http://example.test/script.js"}]
    assert _by_id(record)["mixed_content"]["status"] == "review"


@pytest.mark.parametrize(("header", "rules"), [
    ("Content-Security-Policy", ["csp", "frame_protection"]),
    ("X-Frame-Options", ["frame_protection"]),
    ("X-Content-Type-Options", ["nosniff"]),
    ("Referrer-Policy", ["referrer_policy"]),
    ("Strict-Transport-Security", ["hsts"]),
])
def test_truncated_headers_cannot_produce_pass(header: str, rules: list[str]) -> None:
    record = _record(headers_truncated=[header])
    indexed = _by_id(record)
    for name in rules:
        assert indexed[name]["status"] == "info"
        assert indexed[name]["evidence"]["truncated_headers"] == [header.lower()]
        assert indexed[name]["evidence"]["capture_note"]


def test_truncated_header_reviews_retained_with_capture_note() -> None:
    rules = _by_id(_record(headers={"content-security-policy": "script-src *",
                                    "access-control-allow-origin": "*", "access-control-allow-credentials": "true"},
                           headers_truncated=["content-security-policy", "access-control-allow-origin"]))
    for name in ("csp", "cors"):
        assert rules[name]["status"] == "review"
        assert rules[name]["evidence"]["capture_note"]


def test_truncated_html_headers_do_not_change_not_applicable_rules() -> None:
    rule = _by_id(_record(content_type="application/json", page={"analyzed": False}, headers_truncated=["content-security-policy"]))["csp"]
    assert rule["status"] == "not_applicable"
    assert "capture_note" not in rule["evidence"]


@pytest.mark.parametrize(("days", "expected", "severity"), [(-1, "review", "medium"), (10, "review", "low"), (60, "pass", "info")])
def test_tls_certificate_time_compared_in_utc(days: int, expected: str, severity: str) -> None:
    expiry = datetime.now(UTC) + timedelta(days=days)
    not_after = expiry.strftime("%b %d %H:%M:%S %Y GMT")
    rule = _by_id(_record(tls={"not_after": not_after}))["tls_expiry"]
    assert rule["status"] == expected
    assert rule["severity"] == severity
    assert rule["evidence"]["expires_at"].endswith("+00:00")
    assert rule["evidence"]["evaluated_at"].endswith("+00:00")
    assert abs(rule["evidence"]["remaining_days"] - days) < 0.01


@pytest.mark.parametrize("not_after", ["", "not-a-date", "Jan 99 99:99:99 2030 GMT", None])
def test_tls_unparseable_metadata_is_unknown(not_after: str | None) -> None:
    assert _by_id(_record(tls={"not_after": not_after}))["tls_expiry"]["status"] == "info"
