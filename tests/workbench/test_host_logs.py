"""Offline host log indicators retain evidence, uncertainty and privacy boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.host.logs import (
    MAX_BYTES,
    MAX_EVENTS,
    MAX_LINES,
    MAX_WINDOW_LINES,
    WINDOW_SECONDS,
    assess_logs,
    preview_logs,
)

HOST = "web-01"


def access(index: int = 0, *, status: int = 200, client: str = "192.0.2.8", target: str = "/private?token=NEVER_SAVE_TOKEN",
           timestamp: str | None = None, common: bool = False) -> str:
    moment = datetime(2026, 11, 2, 10, 0, tzinfo=UTC) + timedelta(seconds=index)
    value = timestamp or moment.strftime("%d/%b/%Y:%H:%M:%S %z")
    tail = '' if common else ' "https://ref.example/NEVER_SAVE_REFERER" "NEVER_SAVE_USERAGENT"'
    return f'{client} - NEVER_SAVE_USER [{value}] "GET {target} HTTP/1.1" {status} 124' + tail


def auth(index: int = 0, *, action: str = "Failed", client: str = "198.51.100.8", method: str = "password",
         timestamp: str | None = None, invalid_user: bool = False) -> str:
    moment = datetime(2026, 11, 2, 10, 0, tzinfo=UTC) + timedelta(seconds=index)
    value = timestamp or moment.isoformat().replace("+00:00", "Z")
    invalid = 'invalid user ' if invalid_user else ''
    return f'{value} node sshd[101]: {action} {method} for {invalid}NEVER_SAVE_ACCOUNT from {client} port 4242 ssh2'


def run(lines: list[str], kind: str = "access_log", host: str = HOST) -> dict:
    return assess_logs(('\n'.join(lines) + '\n').encode(), kind, host)


@pytest.mark.parametrize("common", [False, True])
def test_supported_access_formats_keep_only_allowed_fields(common: bool) -> None:
    value = run([access(common=common)])
    event = value["log_events"][0]
    assert event == {"id": "access_log:event:1", "line_number": 1, "input_kind": "access_log", "source_kind": "operator_supplied_log",
                     "timestamp": "2026-11-02T10:00:00Z",
                     "timestamp_status": "known", "actor_alias": event["actor_alias"], "event_class": "http_access",
                     "status_code": 200, "method": "GET", "path_category": "other", "rule_eligible": True}
    serialized = json.dumps(value)
    for private in ["192.0.2.8", "NEVER_SAVE", "/private", "ref.example"]:
        assert private not in serialized
    assert value["coverage"]["complete"] and all(check["status"] == "info" for check in value["checks"])


def test_root_path_is_a_category_never_a_query_disclosure() -> None:
    value = run([access(target="/?session=PRIVATE_SECRET")])
    assert value["log_events"][0]["path_category"] == "root"
    assert "PRIVATE_SECRET" not in json.dumps(value)


def test_client_alias_is_stable_within_file_but_scoped_to_host_and_input() -> None:
    raw = (access(0) + '\n' + access(1)).encode()
    first = assess_logs(raw, "access_log", HOST)
    assert first["log_events"][0]["actor_alias"] == first["log_events"][1]["actor_alias"]
    assert first == assess_logs(raw, "access_log", HOST)
    assert first["log_events"][0]["actor_alias"] != assess_logs(raw, "access_log", "other-host")["log_events"][0]["actor_alias"]
    changed = assess_logs(raw + b'\n', "access_log", HOST)
    assert first["log_events"][0]["actor_alias"] != changed["log_events"][0]["actor_alias"]


def test_http_auth_threshold_uses_same_actor_and_exact_boundary() -> None:
    value = run([access(i, status=401 if i % 2 else 403) for i in range(10)])
    check = value["checks"][0]
    assert check["id"] == "host.logs.http_auth_burst" and check["status"] == "review" and check["complete"]
    window = next(row for row in value["evidence"] if row["kind"] == "host_log_indicator")["data"]["window"]
    assert window["threshold"] == 10 and window["count"] == 10
    assert window["line_numbers"] == list(range(1, 11))
    assert all(row["id"] in {item["id"] for item in value["evidence"]} for row in [{"id": eid} for eid in check["evidence_ids"]])
    below = run([access(i, status=401) for i in range(9)])
    assert below["checks"][0]["status"] == "info"
    split = run([access(i, status=401, client="192.0.2.1" if i < 5 else "192.0.2.2") for i in range(10)])
    assert split["checks"][0]["status"] == "info"


def test_http_server_failures_aggregate_service_not_actors_and_are_not_attack_verdicts() -> None:
    value = run([access(i, status=500 + i, client=f"192.0.2.{i + 1}") for i in range(5)])
    assert value["checks"][1]["status"] == "review"
    windows = [row["data"]["window"] for row in value["evidence"] if row["kind"] == "host_log_indicator"]
    assert windows[0]["actor_alias"] is None
    assert "服务失败" in "".join(value["checks"][1]["guidance"]["limitations"])
    assert not any(check.get("confirmed_incident") for check in value["checks"])


def test_known_offsets_are_normalized_and_file_order_does_not_change_counts() -> None:
    lines = [access(i, status=401) for i in range(10)]
    lines[0] = access(0, status=401, timestamp="02/Nov/2026:18:00:00 +0800")
    value = run(list(reversed(lines)))
    assert value["checks"][0]["status"] == "review"
    assert value["log_events"][-1]["timestamp"] == "2026-11-02T10:00:00Z"
    assert value["rule_parameters"]["window_seconds"] == WINDOW_SECONDS
    assert value["rule_parameters"]["window_is_sliding"] is False


def test_fixed_window_boundary_is_disclosed_and_not_a_sliding_window_claim() -> None:
    lines = [access(299 - i, status=401) for i in range(5)] + [access(300 + i, status=401) for i in range(5)]
    value = run(lines)
    assert value["checks"][0]["status"] == "info"
    assert any("跨窗口" in item for item in value["limitations"])


@pytest.mark.parametrize("timestamp", ["02/Nov/2026:10:00:00", "31/Feb/2026:10:00:00 +0000",
                                        "02/Nov/2026:10:00:00 +2400", "02/Nov/2026:10:00:00 +0060",
                                        "02/Bad/2026:10:00:00 +0000", "00/Nov/2026:10:00:00 +0000"])
def test_unknown_access_time_never_invents_zone_or_participates(timestamp: str) -> None:
    value = run([access(i, status=401, timestamp=timestamp) for i in range(10)])
    assert value["coverage"]["timestamp_unknown_events"] == 10
    assert all(event["timestamp"] is None and not event["rule_eligible"] for event in value["log_events"])
    assert value["checks"][0]["status"] == "unknown"


@pytest.mark.parametrize("client", ["example.test", "192.0.2.1:443", "999.1.1.1", "fe80::1%eth0", "-", "[2001:db8::1]"])
def test_invalid_actor_never_resolves_dns_or_becomes_a_shared_client(client: str) -> None:
    value = run([access(i, status=401, client=client) for i in range(10)])
    assert value["coverage"]["invalid_ip_lines"] == 10
    assert all(event["actor_alias"] is None for event in value["log_events"])
    assert value["checks"][0]["status"] == "unknown"
    assert client not in json.dumps(value) or client == "-"


def test_ipv6_actor_is_parsed_and_only_alias_is_saved() -> None:
    value = run([access(i, status=403, client="2001:db8::1") for i in range(10)])
    assert value["checks"][0]["status"] == "review"
    assert "2001:db8::1" not in json.dumps(value)


@pytest.mark.parametrize("method", ["password", "publickey", "keyboard-interactive"])
def test_auth_failures_and_success_are_safe_distinct_events(method: str) -> None:
    value = run([auth(i, method=method, invalid_user=i % 2 == 0) for i in range(5)] + [auth(6, action="Accepted", method=method)], "auth_log")
    assert value["checks"][0]["id"] == "host.logs.ssh_failure_burst"
    assert value["checks"][0]["status"] == "review"
    assert value["log_events"][-1]["event_class"] == "ssh_auth_success"
    assert value["evidence"][0]["data"]["window"]["count"] == 5
    assert "NEVER_SAVE_ACCOUNT" not in json.dumps(value) and "198.51.100.8" not in json.dumps(value)


def test_rfc3164_year_and_zone_remain_unknown_even_if_threshold_would_be_met() -> None:
    value = run([auth(i, timestamp=f"Nov  2 10:00:{i:02d}") for i in range(5)], "auth_log")
    assert value["coverage"]["timestamp_unknown_events"] == 5
    assert value["checks"][0]["status"] == "unknown"
    assert all(event["timestamp"] is None for event in value["log_events"])


@pytest.mark.parametrize("timestamp", ["2026-11-02T10:00:00", "2026-11-02T10:00:00+24:00", "2026-02-30T10:00:00Z"])
def test_auth_time_rejects_missing_zone_or_invalid_dates(timestamp: str) -> None:
    value = run([auth(i, timestamp=timestamp) for i in range(5)], "auth_log")
    assert value["checks"][0]["status"] == "unknown"


def test_unknown_auth_method_is_sanitized_not_copied() -> None:
    value = run([auth(method="CUSTOM_SECRET_METHOD")], "auth_log")
    assert value["coverage"]["unparsed_lines"] == 1
    assert "CUSTOM_SECRET_METHOD" not in json.dumps(value)


def test_unrelated_or_custom_log_format_remains_visible_gap() -> None:
    value = run([access(0), 'PRIVATE_UNSUPPORTED_LOG', access(1) + ' "extra custom variable"'])
    assert value["coverage"]["unparsed_lines"] == 2
    assert not value["coverage"]["complete"]
    assert all(check["status"] == "unknown" for check in value["checks"])
    assert "PRIVATE_UNSUPPORTED_LOG" not in json.dumps(value)


def test_duplicate_rows_are_disclosed_without_silently_deduplicating_real_requests() -> None:
    value = run([access(status=401)] * 10)
    assert value["checks"][0]["status"] == "review"
    assert value["coverage"]["duplicate_events"] == 9
    assert value["checks"][0]["complete"] is False
    assert value["evidence"][0]["data"]["window"]["count"] == 10


def test_preview_never_builds_rule_evidence_or_discloses_events(monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.modules.host import logs

    def unexpected(*args: object) -> None:
        raise AssertionError("preview must not run detection windows")

    monkeypatch.setattr(logs, "_windows", unexpected)
    value = preview_logs((access() + '\n').encode(), "access_log", HOST)
    assert value["analysis_executed"] is False and value["network_requests"] is False
    assert value["coverage"]["parsed_events"] == 1
    assert not {"checks", "evidence", "log_events"} & value.keys()
    assert "NEVER_SAVE" not in json.dumps(value)


@pytest.mark.parametrize("raw,kind,host,code", [(b'', 'access_log', HOST, 'HOST_LOG_LIMIT'),
    (b'x' * (MAX_BYTES + 1), 'auth_log', HOST, 'HOST_LOG_LIMIT'), (b'\xff', 'access_log', HOST, 'INVALID_HOST_LOG'),
    (b'\x00', 'auth_log', HOST, 'INVALID_HOST_LOG'), (b'x', 'invented', HOST, 'INVALID_HOST_LOG_KIND'),
    (b'x', 'access_log', '', 'INVALID_HOST_ID'), (b'x', 'access_log', 'bad\nhost', 'INVALID_HOST_ID')])
def test_invalid_inputs_have_safe_domain_errors(raw: bytes, kind: str, host: str, code: str) -> None:
    with pytest.raises(WorkbenchError) as exc:
        assess_logs(raw, kind, host)
    assert exc.value.code == code


def test_event_budget_and_line_budget_are_explicit() -> None:
    value = run([access(i) for i in range(MAX_EVENTS + 1)])
    assert len(value["log_events"]) == MAX_EVENTS
    assert value["coverage"]["parsed_events"] == MAX_EVENTS + 1
    assert value["coverage"]["event_budget_exhausted"] and value["coverage"]["truncated"]
    assert all(check["status"] == "unknown" for check in value["checks"])
    lines = run([''] * (MAX_LINES + 1))
    assert lines["coverage"]["total_lines"] == MAX_LINES + 1
    assert lines["coverage"]["line_budget_exhausted"] and lines["coverage"]["examined_lines"] == MAX_LINES


def test_window_line_evidence_is_bounded_and_does_not_claim_completeness() -> None:
    value = run([access(i, status=401) for i in range(MAX_WINDOW_LINES + 1)])
    window = value["evidence"][0]["data"]["window"]
    assert len(window["line_numbers"]) == MAX_WINDOW_LINES and window["line_numbers_truncated"]
    assert value["checks"][0]["complete"] is False


def test_all_log_outcomes_never_clear_incidents_or_request_automatic_actions() -> None:
    for value in [run([access()]), run([access(i, status=401) for i in range(10)]), run(['unparsed'])]:
        for check in value["checks"]:
            assert check["status"] in {"review", "info", "unknown"}
            assert check["retest_can_prove_fix"] is False
            for field in ['prerequisites', 'red_review', 'blue_steps', 'verification', 'rollback', 'limitations', 'references']:
                assert check["guidance"][field]
            assert check["guidance"]["executed"] is False


def test_mutating_result_does_not_change_later_rule_parameters_or_guidance() -> None:
    first = run([access()])
    first["rule_parameters"]["http_auth_statuses"].clear()
    first["checks"][0]["evidence"]["values"]["rule_parameters"]["http_auth_statuses"].append(200)
    first["checks"][0]["guidance"]["references"][0]["url"] = "untrusted"
    second = run([access()])
    assert second["rule_parameters"]["http_auth_statuses"] == [401, 403]
    assert second["checks"][0]["guidance"]["references"][0]["url"].startswith("https://nginx.org/")


@pytest.mark.parametrize("timestamp", ["01/Jan/0001:00:00:00 +0000", "01/Jan/1900:00:00:00 +0000"])
def test_extreme_old_dates_do_not_depend_on_windows_epoch_support(timestamp: str) -> None:
    value = run([access(status=500, timestamp=timestamp)] * 5)
    assert value["checks"][1]["status"] == "review"


def test_extreme_future_time_cannot_overflow_window_end() -> None:
    value = run([access(status=500, timestamp="31/Dec/9999:23:59:59 +0000")] * 5)
    assert value["checks"][1]["status"] == "unknown"
    assert value["coverage"]["timestamp_unknown_events"] == 5


@pytest.mark.parametrize("host", ["bad\ud800host", "bad\x85host"])
def test_invalid_host_unicode_is_rejected_without_echoing_input(host: str) -> None:
    with pytest.raises(WorkbenchError) as exc:
        assess_logs(access().encode(), "access_log", host)
    assert exc.value.code == "INVALID_HOST_ID" and host not in str(exc.value)


def test_unicode_separator_inside_request_does_not_invent_a_file_line() -> None:
    raw = (access(target="/private\u2028path?token=HIDDEN") + '\r\n' + access(1)).encode()
    value = assess_logs(raw, "access_log", HOST)
    assert value["coverage"]["total_lines"] == 2
    assert [row["line_number"] for row in value["log_events"]] == [1, 2]
    assert "HIDDEN" not in json.dumps(value)


def test_alert_budget_is_visible_and_results_stay_bounded() -> None:
    lines = [access(index, status=401, client=f"10.0.{actor // 250}.{actor % 250 + 1}")
             for actor in range(101) for index in range(10)]
    value = run(lines)
    assert value["coverage"]["alert_windows_total"] == 101
    assert value["coverage"]["alert_windows_returned"] == 100
    assert value["coverage"]["alert_budget_exhausted"] and value["coverage"]["truncated"]
    assert value["checks"][0]["complete"] is False
    assert len([item for item in value["evidence"] if item["kind"] == "host_log_indicator"]) == 100


def test_combined_log_events_have_unique_source_qualified_identities() -> None:
    access_events = run([access()])["log_events"]
    auth_events = run([auth()], "auth_log")["log_events"]
    rows = [*access_events, *auth_events]
    assert len({item["id"] for item in rows}) == len(rows) == 2
    assert {item["input_kind"] for item in rows} == {"access_log", "auth_log"}


@pytest.mark.parametrize("kind", ["access_log", "auth_log"])
def test_synthetic_origin_is_preserved_everywhere_in_log_result(kind: str) -> None:
    raw = ('\n'.join(access(i, status=401) if kind == "access_log" else auth(i) for i in range(10)) + '\n').encode()
    value = assess_logs(raw, kind, HOST, source_kind="synthetic_demo")
    assert value["source_kind"] == value["coverage"]["source_kind"] == "synthetic_demo"
    assert all(item["source_kind"] == "synthetic_demo" for item in value["checks"])
    assert all(item["source_kind"] == "synthetic_demo" for item in value["log_events"])
    assert all(item["data"]["source_kind"] == "synthetic_demo" for item in value["evidence"])
    assert value["redaction"]["original_upload_retained_locally"] is False


@pytest.mark.parametrize("source", ["verified_production", "", [], None])
def test_log_origin_cannot_claim_unimplemented_or_verified_source(source: Any) -> None:
    with pytest.raises(WorkbenchError) as exc:
        assess_logs(access().encode(), "access_log", HOST, source_kind=source)
    assert exc.value.code == "INVALID_HOST_LOG_SOURCE"
