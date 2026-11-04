"""Host exports preserve context, unknowns and secret-minimized configuration proof."""

from __future__ import annotations

import json
from typing import Any

import pytest

from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.host.baseline import assess_baseline
from reachscope_workbench.modules.host.input import (
    MAX_BYTES,
    MAX_CONFIG_BYTES,
    parse_baseline,
    preview_baseline,
)

SAFE_SSH = "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"
SAFE_NGINX = "http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; server { listen 443 ssl; server_name example.test; location / { } } }"


def document(*, ssh: Any = SAFE_SSH, nginx: Any = SAFE_NGINX, **extra: Any) -> dict[str, Any]:
    return {"schema_version": "reachscope-host/1", "host_id": "host-01", "collected_at": "2026-11-02T08:00:00+08:00",
            "ssh": {"effective_config": ssh, "connection_context": "global"}, "nginx": {"config_dump": nginx}, **extra}


def analyze(value: dict[str, Any] | None = None, selected: list[str] | None = None) -> dict[str, Any]:
    parsed = parse_baseline(json.dumps(value if value is not None else document()).encode(), "host-01")
    return assess_baseline(parsed, selected if selected is not None else ["ssh", "nginx"])


def indexed(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in result["checks"]}


def test_explicit_safe_export_has_seven_known_static_checks_and_guidance() -> None:
    result = analyze()
    assert len(result["checks"]) == len(result["evidence"]) == 7
    assert all(row["status"] == "pass" and row["complete"] is True for row in result["checks"])
    assert result["coverage"]["runtime_state_verified"] is False
    assert result["coverage"]["collected_at"] == "2026-11-02T00:00:00+00:00"
    for check in result["checks"]:
        assert check["comparison_identity"]["scope_keys"] and check["comparison_identity"]["complete"]
        assert all(check["guidance"][key] for key in ("prerequisites", "red_review", "blue_steps", "verification", "rollback", "limitations", "references"))
        assert check["evidence_ids"][0] in {row["id"] for row in result["evidence"]}


@pytest.mark.parametrize("selected,expected", [(["ssh"], 4), (["nginx"], 3), ([], 0), (["web_logs"], 0)])
def test_real_group_selection_runs_only_requested_baseline(selected: list[str], expected: int) -> None:
    result = analyze(selected=selected)
    assert len(result["checks"]) == expected
    assert all(row["id"].split(".")[1] in selected for row in result["checks"])


@pytest.mark.parametrize("field,weak,identifier", [
    ("permitrootlogin", "yes", "root_login"), ("permitrootlogin", "prohibit-password", "root_login"),
    ("permitrootlogin", "forced-commands-only", "root_login"), ("passwordauthentication", "yes", "password_auth"),
    ("permitemptypasswords", "yes", "empty_passwords"), ("maxauthtries", "6", "max_auth_tries"),
])
def test_ssh_reviewed_conditions_are_not_verified_vulnerabilities(field: str, weak: str, identifier: str) -> None:
    lines = [line for line in SAFE_SSH.splitlines() if not line.startswith(field + " ")]
    result = indexed(analyze(document(ssh="\n".join([*lines, field + " " + weak])), ["ssh"]))
    check = result["host.ssh." + identifier]
    assert check["status"] == "review" and check["complete"] is True
    assert "不是漏洞" in check["description"]


@pytest.mark.parametrize("value", ["0", "-1", "65536", "True", "NaN", "99999999999999999999999999999999999"])
def test_invalid_attempt_limits_never_become_pass(value: str) -> None:
    check = indexed(analyze(document(ssh=SAFE_SSH.replace("maxauthtries 3", "maxauthtries " + value)), ["ssh"]))["host.ssh.max_auth_tries"]
    assert check["status"] == "unknown" and check["complete"] is False


@pytest.mark.parametrize("suffix", ["\nMatch User somebody\n", "\nInclude /not/read/by/tool\n", '\ninvalid "unterminated\n'])
def test_raw_conditional_include_or_invalid_syntax_blocks_ssh_pass(suffix: str) -> None:
    result = analyze(document(ssh=SAFE_SSH + suffix), ["ssh"])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


def test_missing_or_duplicate_ssh_fields_are_unknown_without_guessing_defaults() -> None:
    missing = indexed(analyze(document(ssh="permitrootlogin no\n"), ["ssh"]))
    assert missing["host.ssh.root_login"]["status"] == "pass"
    assert missing["host.ssh.password_auth"]["status"] == "unknown"
    duplicate = indexed(analyze(document(ssh=SAFE_SSH + "permitrootlogin yes\n"), ["ssh"]))
    assert duplicate["host.ssh.root_login"]["status"] == "unknown"


@pytest.mark.parametrize("component", ["ssh", "nginx"])
def test_missing_configuration_is_unknown_not_safe(component: str) -> None:
    data = document()
    del data[component]
    result = analyze(data, [component])
    assert all(row["status"] == "unknown" and row["complete"] is False for row in result["checks"])


@pytest.mark.parametrize("directive,weak,identifier", [("autoindex off", "autoindex on", "autoindex"),
                                                       ("server_tokens off", "server_tokens on", "server_tokens"),
                                                       ("server_tokens off", "server_tokens build", "server_tokens"),
                                                       ("TLSv1.2 TLSv1.3", "TLSv1 TLSv1.2", "tls_protocols")])
def test_nginx_explicit_weak_declaration_is_review(directive: str, weak: str, identifier: str) -> None:
    check = indexed(analyze(document(nginx=SAFE_NGINX.replace(directive, weak)), ["nginx"]))["host.nginx." + identifier]
    assert check["status"] == "review" and check["complete"] is True


def test_nginx_location_override_cannot_be_hidden_by_safe_parent() -> None:
    data = document(nginx=SAFE_NGINX.replace("location / { }", "location / { autoindex on; }"))
    check = indexed(analyze(data, ["nginx"]))["host.nginx.autoindex"]
    assert check["status"] == "review"
    values = check["evidence"]["values"]["facts"]
    assert any(fact.get("values") == ["on"] and fact["context_kind"] == "location" for fact in values)


def test_nginx_http_default_is_not_guessed_when_field_missing() -> None:
    config = "http { server { listen 443 ssl; server_name example.test; } }"
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" for row in result["checks"])


def test_non_tls_listener_is_not_applicable_not_fake_tls_pass() -> None:
    check = indexed(analyze(document(nginx=SAFE_NGINX.replace("443 ssl", "80")), ["nginx"]))["host.nginx.tls_protocols"]
    assert check["status"] == "not_applicable" and check["complete"] is True


@pytest.mark.parametrize("extra", ["include /not/provided/*.conf;", "include relative/file.conf;", "include $prefix/*.conf;",
                                  "if ($request_method = GET) { autoindex off; }", "strange_module { autoindex on; }"])
def test_unsupported_include_or_scope_cannot_create_safe_nginx_pass(extra: str) -> None:
    config = SAFE_NGINX.replace("http {", "http { " + extra, 1)
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


def test_known_weak_field_with_incomplete_include_stays_review_but_not_complete() -> None:
    config = SAFE_NGINX.replace("autoindex off", "autoindex on; include /missing.conf")
    check = indexed(analyze(document(nginx=config), ["nginx"]))["host.nginx.autoindex"]
    assert check["status"] == "review" and check["complete"] is False


def test_actual_dump_include_is_resolved_from_text_without_local_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("No local file reads"))
    config = '''# configuration file /etc/nginx/nginx.conf:
events {}
http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; include /etc/nginx/conf.d/*.conf; }
# configuration file /etc/nginx/conf.d/site.conf:
server { listen 443 ssl; server_name example.test; location / {} }
'''
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "pass" for row in result["checks"])
    assert result["coverage"]["nginx"]["gap_codes"] == []


def test_include_glob_does_not_match_across_directory_boundaries() -> None:
    config = '''# configuration file /etc/nginx/nginx.conf:
http { autoindex off; server_tokens off; include /etc/nginx/*.conf; }
# configuration file /etc/nginx/subdir/site.conf:
server { listen 80; }
'''
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" for row in result["checks"])


def test_include_cycles_are_bounded_and_unknown() -> None:
    config = '''# configuration file /etc/nginx/nginx.conf:
http { include /etc/nginx/loop.conf; }
# configuration file /etc/nginx/loop.conf:
include /etc/nginx/nginx.conf;
'''
    result = analyze(document(nginx=config), ["nginx"])
    assert "include_cycle" in result["coverage"]["nginx"]["gap_codes"]
    assert all(row["status"] == "unknown" for row in result["checks"])


@pytest.mark.parametrize("config", ["http { server {", "http { autoindex off }", 'http { server_name "unfinished;',
                                  "http{} http{}", "server { autoindex off; }"])
def test_malformed_or_snippet_input_does_not_claim_complete_nginx(config: str) -> None:
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


def test_context_identity_ignores_line_numbers_and_directive_values() -> None:
    before = indexed(analyze(document(nginx=SAFE_NGINX.replace("autoindex off", "autoindex on")), ["nginx"]))
    after = indexed(analyze(document(nginx="\n\n# Extra comment\n" + SAFE_NGINX), ["nginx"]))
    assert before["host.nginx.autoindex"]["comparison_identity"] == after["host.nginx.autoindex"]["comparison_identity"]
    other = indexed(analyze(document(nginx=SAFE_NGINX.replace("example.test", "other.test")), ["nginx"]))
    assert before["host.nginx.autoindex"]["comparison_identity"] != other["host.nginx.autoindex"]["comparison_identity"]


def test_duplicate_context_identity_blocks_remediation_evidence() -> None:
    config = SAFE_NGINX.replace("location / { }", "location / { } location / { }")
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


def test_secrets_and_unrelated_values_never_enter_preview_or_result() -> None:
    data = document(ssh=SAFE_SSH + "setenv SECRET=SHOULD_NEVER_APPEAR\nhostkey /private/secret/path\n",
                    nginx=SAFE_NGINX.replace("server_name example.test;", 'server_name PRIVATE_SERVER_NAME; proxy_set_header Authorization "Bearer SHOULD_NEVER_APPEAR"; ssl_certificate_key /private/secret/path;'))
    data["api_key"] = "SHOULD_NEVER_APPEAR"
    parsed = parse_baseline(json.dumps(data).encode(), "host-01")
    preview = preview_baseline(parsed, ["ssh", "nginx"])
    rendered = json.dumps([preview, assess_baseline(parsed, ["ssh", "nginx"])])
    assert all(secret not in rendered for secret in ["SHOULD_NEVER_APPEAR", "PRIVATE_SERVER_NAME", "/private/secret/path"])


def test_user_supplied_origin_cannot_spoof_server_owned_synthetic_label() -> None:
    parsed = parse_baseline(json.dumps(document(source_kind="synthetic_demo")).encode(), "host-01")
    assert parsed["source_kind"] == "operator_supplied_export"
    result = assess_baseline(parsed, ["ssh", "nginx"])
    assert result["coverage"]["source_kind"] == "operator_supplied_export"
    assert all(proof["data"]["capture_kind"] == "operator_supplied_export" for proof in result["evidence"])


def test_server_owned_demo_origin_is_consistent_before_hashing_evidence() -> None:
    import hashlib

    parsed = parse_baseline(json.dumps(document()).encode(), "host-01")
    imported = assess_baseline(parsed, ["ssh", "nginx"])
    parsed["source_kind"] = "synthetic_demo"
    demo = assess_baseline(parsed, ["ssh", "nginx"])
    assert demo["coverage"]["source_kind"] == "synthetic_demo"
    for original, proof in zip(imported["evidence"], demo["evidence"], strict=True):
        assert proof["data"]["capture_kind"] == "synthetic_demo"
        assert original["sha256"] != proof["sha256"]
        encoded = json.dumps(proof["data"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == proof["sha256"]
    assert all(row["evidence"]["values"]["capture_kind"] == "synthetic_demo" for row in demo["checks"])


@pytest.mark.parametrize("bad", [b"", b"not json", b"[]", b'{"schema_version":"reachscope-host/2"}',
                                 b'{"schema_version":"reachscope-host/1","host_id":"x","host_id":"host-01"}',
                                 b'{"schema_version":"reachscope-host/1","host_id":"host-01","secret":NaN}',
                                 b'{"schema_version":"reachscope-host/1","host_id":"host-01","secret":"\\ud800"}',
                                 b'\xff'])
def test_invalid_input_is_structured_error(bad: bytes) -> None:
    with pytest.raises(WorkbenchError):
        parse_baseline(bad, "host-01")


def test_host_identity_mismatch_is_explicit() -> None:
    with pytest.raises(WorkbenchError) as error:
        parse_baseline(json.dumps(document(host_id="different")).encode(), "host-01")
    assert error.value.code == "HOST_ID_MISMATCH"


def test_missing_ssh_context_keeps_static_facts_but_blocks_scope_comparison() -> None:
    data = document()
    del data["ssh"]["connection_context"]
    result = analyze(data, ["ssh"])
    assert all(row["status"] == "pass" and row["complete"] for row in result["checks"])
    assert all(row["comparison_identity"]["complete"] is False for row in result["checks"])
    assert result["coverage"]["ssh"]["connection_context_provided"] is False


def test_explicit_connection_context_changes_cannot_share_retest_identity() -> None:
    before = indexed(analyze(document(), ["ssh"]))["host.ssh.root_login"]
    data = document()
    data["ssh"]["connection_context"] = "user=service,addr=192.0.2.1"
    after = indexed(analyze(data, ["ssh"]))["host.ssh.root_login"]
    assert before["comparison_identity"]["scope_keys"] != after["comparison_identity"]["scope_keys"]
    assert "192.0.2.1" not in json.dumps(after)


@pytest.mark.parametrize("value", ["", "x" * 129, " x ", "x\ny", [], {}])
def test_invalid_connection_context_is_rejected(value: Any) -> None:
    data = document()
    data["ssh"]["connection_context"] = value
    with pytest.raises(WorkbenchError):
        parse_baseline(json.dumps(data).encode(), "host-01")


@pytest.mark.parametrize("host", [None, [], "", " x ", "a\nb", "a" * 129])
def test_invalid_host_identity_is_rejected(host: Any) -> None:
    with pytest.raises(WorkbenchError):
        parse_baseline(json.dumps(document(host_id=host)).encode(), "host-01")


@pytest.mark.parametrize("timestamp", [None, "2026-11-02", "2026-11-02T00:00:00", "invalid", "2026-11-02 00:00:00Z",
                                      "2026-11-02T00:00:00+01:99", "2026-11-02T00:00:00+24:00", "2026-11-02T00:00:00-01:60"])
def test_missing_or_invalid_collection_timestamp_stays_unknown(timestamp: str | None) -> None:
    parsed = parse_baseline(json.dumps(document(collected_at=timestamp)).encode(), "host-01")
    assert parsed["collected_at"] is None and parsed["collection_state"] == "unknown"


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"])
def test_timezone_conversion_overflow_stays_unknown(timestamp: str) -> None:
    parsed = parse_baseline(json.dumps(document(collected_at=timestamp)).encode(), "host-01")
    assert parsed["collection_state"] == "unknown" and parsed["collected_at"] is None


@pytest.mark.parametrize("replacement", ['autoindex "" off', 'server_tokens "" off', 'autoindex ""off', 'autoindex of"f"'])
def test_invalid_quoted_arguments_cannot_be_flattened_into_safe_directive(replacement: str) -> None:
    name = replacement.split()[0]
    config = SAFE_NGINX.replace(name + " off", replacement)
    row = indexed(analyze(document(nginx=config), ["nginx"]))["host.nginx." + name]
    assert row["status"] == "unknown" and not row["complete"]


@pytest.mark.parametrize("plain", ["443", "0.0.0.0:443"])
def test_shared_ssl_listener_does_not_hide_default_server_protocol_scope(plain: str) -> None:
    config = "http { autoindex off; server_tokens off; server { listen " + plain + " default_server; server_name default.test; ssl_protocols TLSv1; } server { listen 443 ssl; server_name secure.test; ssl_protocols TLSv1.2 TLSv1.3; } }"
    row = indexed(analyze(document(nginx=config), ["nginx"]))["host.nginx.tls_protocols"]
    assert row["status"] == "unknown" and not row["complete"]
    assert row["comparison_identity"]["complete"] is False


@pytest.mark.parametrize("component", ["ssh", "nginx"])
@pytest.mark.parametrize("control", ["\x00", "\x01", "\x1f", "\x7f"])
def test_binary_control_characters_do_not_disappear_from_component_scope(component: str, control: str) -> None:
    data = document(**{component: (SAFE_SSH if component == "ssh" else SAFE_NGINX) + "\n# ignored " + control})
    result = analyze(data, [component])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


@pytest.mark.parametrize("replacement", ["http unexpected {", "http { server unexpected {", "http { server { location {", "http { server { listen;"])
def test_obviously_unsupported_block_or_listen_syntax_is_not_safe(replacement: str) -> None:
    config = (replacement + " autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; "
              + "}" * replacement.count("{"))
    result = analyze(document(nginx=config), ["nginx"])
    assert all(row["status"] == "unknown" and not row["complete"] for row in result["checks"])


def test_budgets_reject_large_input_and_large_component() -> None:
    with pytest.raises(WorkbenchError):
        parse_baseline(b" " * (MAX_BYTES + 1), "host-01")
    with pytest.raises(WorkbenchError):
        parse_baseline(json.dumps(document(ssh="a" * (MAX_CONFIG_BYTES + 1))).encode(), "host-01")


def test_fact_truncation_and_context_budget_never_create_complete_pass() -> None:
    config = "http { autoindex off; server_tokens off; " + " ".join(f"server {{ listen {1000 + i}; server_name x{i}; }}" for i in range(105)) + " }"
    rows = indexed(analyze(document(nginx=config), ["nginx"]))
    assert rows["host.nginx.autoindex"]["facts_truncated"] is True
    assert rows["host.nginx.autoindex"]["status"] == "unknown" and not rows["host.nginx.autoindex"]["complete"]
    config = "http { " + " ".join(f"server {{ listen {1000 + i}; }}" for i in range(205)) + " }"
    assert all(row["status"] == "unknown" for row in analyze(document(nginx=config), ["nginx"])["checks"])


@pytest.mark.parametrize(("directive", "weak", "identifier"), [("autoindex", "on", "host.nginx.autoindex"),
                                                               ("server_tokens", "on", "host.nginx.server_tokens"),
                                                               ("ssl_protocols", "TLSv1", "host.nginx.tls_protocols")])
def test_late_review_context_survives_the_retained_evidence_budget(directive: str, weak: str, identifier: str) -> None:
    servers = " ".join(f"server {{ listen {1000 + index} ssl; server_name x{index}; "
                       + (f"{directive} {weak}; " if index == 104 else "") + "}" for index in range(105))
    config = "http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; " + servers + " }"
    check = indexed(analyze(document(nginx=config), ["nginx"]))[identifier]
    facts = check["evidence"]["values"]["facts"]
    assert check["status"] == "review" and check["facts_truncated"] is True and check["complete"] is False
    assert any(row.get("values") == [weak] for row in facts), "Retained proof must explain the actual review condition"
    assert any(row.get("export_sha256") for row in facts)
