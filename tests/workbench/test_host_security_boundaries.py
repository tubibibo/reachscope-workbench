"""Independent host parser, comparison and schema-upgrade boundary regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.case_sources import candidates, compare_retest
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository
from reachscope_workbench.modules.host.baseline import assess_baseline
from reachscope_workbench.modules.host.input import parse_baseline, preview_baseline
from reachscope_workbench.modules.host.module import HostModule

HOST = "independent-host"
SSH = "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"
NGINX = "http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; server { listen 443 ssl; server_name example.test; location / {} } }"


def document(*, ssh: str = SSH, nginx: str = NGINX, context: str | None = "global", timestamp: str = "2026-11-02T00:00:00Z") -> dict[str, Any]:
    return {"schema_version": "reachscope-host/1", "host_id": HOST, "collected_at": timestamp,
            "ssh": {"effective_config": ssh, **({"connection_context": context} if context is not None else {})},
            "nginx": {"config_dump": nginx}}


def analyze(value: dict[str, Any], groups: list[str] | None = None) -> dict[str, Any]:
    return assess_baseline(parse_baseline(json.dumps(value).encode(), HOST), groups or ["ssh", "nginx"])


def check(value: dict[str, Any], identifier: str) -> dict[str, Any]:
    return next(row for row in analyze(value)["checks"] if row["id"] == identifier)


def saved(value: dict[str, Any], identifier: str = "baseline") -> dict[str, Any]:
    assessed = analyze(value)
    return {"id": identifier, "asset_id": "baseline-asset" if identifier == "baseline" else "revised-asset",
            "module": "host", "status": "completed", "config": {"mode": "baseline", "host_id": HOST},
            "result": {"module": "host", "evidence": assessed["evidence"], "observations": [], "details": {
                "review_version": 1, "host_id": HOST, "checks": assessed["checks"], "coverage": assessed["coverage"],
                "collection": {key: assessed["coverage"][key] for key in ("collected_at", "collection_state")},
                "execution": [{"id": group, "status": "completed"} for group in ("ssh", "nginx")]}}}


def compare(before: dict[str, Any], after: dict[str, Any], identifier: str = "host.ssh.root_login") -> dict[str, Any]:
    selected = next(row for row in candidates(before) if row["category"] == identifier)
    return compare_retest(before, selected["source_kind"], selected["source_ref"], after, related_asset_ids={"revised-asset"})


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"])
def test_extreme_collection_zone_overflow_is_unknown_not_an_api_exception(timestamp: str) -> None:
    parsed = parse_baseline(json.dumps(document(timestamp=timestamp)).encode(), HOST)
    assert parsed["collected_at"] is None and parsed["collection_state"] == "unknown"


@pytest.mark.parametrize("field", ["autoindex", "server_tokens"])
def test_empty_quoted_nginx_argument_is_not_dropped_into_a_safe_flag(field: str) -> None:
    value = document(nginx=NGINX.replace(field + " off", field + ' "" off'))
    row = check(value, "host.nginx." + field)
    assert row["status"] == "unknown" and row["complete"] is False


@pytest.mark.parametrize("start,replacement", [("http {", "http unexpected {"), ("server {", "server unexpected {"),
                                               ("location / {}", "location / unexpected {}")])
def test_unsupported_context_arity_cannot_form_complete_safe_scope(start: str, replacement: str) -> None:
    value = document(nginx=NGINX.replace(start, replacement))
    assert all(row["status"] == "unknown" and not row["complete"] for row in analyze(value, ["nginx"])["checks"])


@pytest.mark.parametrize("component", ["ssh", "nginx"])
@pytest.mark.parametrize("character", ["\x00", "\x01", "\x7f"])
def test_control_characters_in_unreviewed_fields_do_not_leave_complete_pass(component: str, character: str) -> None:
    value = document(ssh=SSH + f"setenv ignored{character}secret\n" if component == "ssh" else SSH,
                     nginx=NGINX.replace("http {", f"http {{ set $ignored abc{character}def;") if component == "nginx" else NGINX)
    rows = analyze(value, [component])["checks"]
    assert all(row["status"] == "unknown" and not row["complete"] for row in rows)


def test_shared_tls_listener_does_not_omit_default_servers_protocol_scope() -> None:
    config = '''http { autoindex off; server_tokens off; ssl_protocols TLSv1;
      server { listen 443 default_server; server_name first.test; }
      server { listen 443 ssl; server_name second.test; ssl_protocols TLSv1.2 TLSv1.3; }
    }'''
    row = check(document(nginx=config), "host.nginx.tls_protocols")
    assert row["status"] == "unknown" and row["complete"] is False


def test_include_expansion_cycle_is_local_bounded_and_never_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    config = '''# configuration file /etc/nginx/nginx.conf:
http { autoindex off; server_tokens off; include /etc/nginx/site.conf; }
# configuration file /etc/nginx/site.conf:
server { listen 443 ssl; ssl_protocols TLSv1.2 TLSv1.3; include /etc/nginx/nginx.conf; }
'''
    monkeypatch.setattr(Path, "read_bytes", lambda *args, **kwargs: pytest.fail("Included paths must not be opened"))
    rows = analyze(document(nginx=config), ["nginx"])["checks"]
    assert all(row["status"] == "unknown" and not row["complete"] for row in rows)


def test_raw_secrets_in_context_labels_and_ignored_fields_do_not_enter_result() -> None:
    value = document(ssh=SSH + "setenv TOKEN=PRIVATE_CREDENTIAL\n", context="PRIVATE_CONNECTION_LABEL",
                     nginx=NGINX.replace("example.test", "PRIVATE_SERVER_NAME").replace("location / {}", 'location /PRIVATE_PATH { proxy_set_header Authorization "PRIVATE_CREDENTIAL"; }'))
    parsed = parse_baseline(json.dumps(value).encode(), HOST)
    rendered = json.dumps([assess_baseline(parsed, ["ssh", "nginx"]), preview_baseline(parsed, ["ssh", "nginx"])])
    assert all(private not in rendered for private in ["PRIVATE_CREDENTIAL", "PRIVATE_CONNECTION_LABEL", "PRIVATE_SERVER_NAME", "PRIVATE_PATH"])


def test_ssh_comparison_requires_same_explicit_connection_context() -> None:
    before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes"), context="global"))
    same = saved(document(context="global"), "after")
    assert compare(before, same)["outcome"] == "not_observed_in_scope"
    different = saved(document(context="source-192.0.2.1-user-alice"), "after")
    assert compare(before, different)["outcome"] == "not_comparable"
    absent = saved(document(context=None), "after")
    assert compare(before, absent)["outcome"] == "not_comparable"
    unknown_before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes"), context=None))
    assert compare(unknown_before, same)["outcome"] == "not_comparable"


@pytest.mark.parametrize("gap", ["host", "resource", "version", "bool-version", "skipped", "evidence", "partial", "truncated", "scope", "duplicate-rule"])
def test_host_retest_identity_and_evidence_gaps_never_clear_a_case(gap: str) -> None:
    before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes")))
    after = saved(document(), "after")
    details = after["result"]["details"]
    row = next(item for item in details["checks"] if item["id"] == "host.ssh.root_login")
    if gap == "host":
        details["host_id"] = "other-host"
    elif gap == "resource":
        row["resource_id"] = "other-host::ssh"
    elif gap == "version":
        details["review_version"] = 2
    elif gap == "bool-version":
        details["review_version"] = True
    elif gap == "skipped":
        details["execution"][0]["status"] = "skipped"
    elif gap == "evidence":
        after["result"]["evidence"] = []
    elif gap == "partial":
        row["complete"] = False
    elif gap == "truncated":
        row["facts_truncated"] = True
    elif gap == "scope":
        row["comparison_identity"]["scope_keys"] = []
    else:
        details["checks"].append(copy.deepcopy(row))
    assert compare(before, after)["outcome"] == "not_comparable"


@pytest.mark.parametrize("collection", [None, {}, {"collected_at": None, "collection_state": "unknown"},
    {"collected_at": "2026-11-01T23:59:59Z", "collection_state": "provided_not_verified"},
    {"collected_at": "2026-11-02T00:00:00", "collection_state": "provided_not_verified"},
    {"collected_at": "9999-12-31T23:59:59-23:59", "collection_state": "provided_not_verified"}])
def test_unknown_or_stale_collection_is_not_a_configuration_fix(collection: Any) -> None:
    before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes")))
    after = saved(document(), "after")
    after["result"]["details"]["collection"] = collection
    assert compare(before, after)["outcome"] == "not_comparable"


def test_unknown_baseline_collection_cannot_be_repaired_by_known_retest_time() -> None:
    before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes")))
    before["result"]["details"]["collection"] = {"collected_at": None, "collection_state": "unknown"}
    assert compare(before, saved(document(), "after"))["outcome"] == "not_comparable"


def test_duplicate_scope_keys_cannot_masquerade_as_complete_identity() -> None:
    before = saved(document(ssh=SSH.replace("permitrootlogin no", "permitrootlogin yes")))
    after = saved(document(), "after")
    for job in (before, after):
        row = next(item for item in job["result"]["details"]["checks"] if item["id"] == "host.ssh.root_login")
        row["comparison_identity"]["scope_keys"] *= 2
    assert compare(before, after)["outcome"] == "not_comparable"


def test_actual_combined_host_demo_keeps_log_sources_unique_and_synthetic() -> None:
    result = HostModule._analyze({"mode": "demo", "host_id": HOST, "checks": ["web_logs", "auth_logs"]}, None)
    events = result.details["log_events"]
    assert len({event["id"] for event in events}) == len(events) == 24
    assert {event["input_kind"] for event in events} == {"access_log", "auth_log"}
    assert all(event["source_kind"] == "synthetic_demo" for event in events)
    assert all(item.data["source_kind"] == "synthetic_demo" for item in result.evidence)
    assert result.details["origin"] == "synthetic_demo"


def legacy_v6(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Actual v6 asset schema includes provenance, unlike earlier six-column v5."""
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
          CREATE TABLE schema_meta(version INTEGER NOT NULL); INSERT INTO schema_meta VALUES(6);
          CREATE TABLE assets(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,source TEXT NOT NULL,
              created_at TEXT NOT NULL,updated_at TEXT NOT NULL,provenance TEXT);
          CREATE TABLE jobs(id TEXT PRIMARY KEY,module TEXT NOT NULL,name TEXT NOT NULL,config TEXT NOT NULL,
              status TEXT NOT NULL,progress INTEGER NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,error TEXT,result TEXT);
          CREATE TABLE job_assets(job_id TEXT PRIMARY KEY REFERENCES jobs(id),asset_id TEXT NOT NULL REFERENCES assets(id),snapshot TEXT NOT NULL);
          CREATE TABLE job_requests(key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES jobs(id));
          CREATE TABLE uploads(id TEXT PRIMARY KEY,filename TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(id),
              created_at TEXT NOT NULL,level TEXT NOT NULL,message TEXT NOT NULL,progress INTEGER NOT NULL);
          CREATE TABLE engagements(id TEXT PRIMARY KEY,name TEXT NOT NULL,objective TEXT NOT NULL,
              authorization_note TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          CREATE TABLE engagement_assets(engagement_id TEXT NOT NULL REFERENCES engagements(id),
              asset_id TEXT NOT NULL REFERENCES assets(id),PRIMARY KEY(engagement_id,asset_id));
          CREATE TABLE cases(id TEXT PRIMARY KEY,engagement_id TEXT NOT NULL REFERENCES engagements(id),
              asset_id TEXT NOT NULL REFERENCES assets(id),job_id TEXT NOT NULL REFERENCES jobs(id),source_ref TEXT NOT NULL,
              source_kind TEXT NOT NULL,title TEXT NOT NULL,severity TEXT NOT NULL,confidence TEXT NOT NULL,status TEXT NOT NULL,
              owner TEXT NOT NULL,due_date TEXT NOT NULL,note TEXT NOT NULL,version INTEGER NOT NULL,created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,UNIQUE(engagement_id,job_id,source_kind,source_ref));
          CREATE TABLE case_events(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL REFERENCES cases(id),
              created_at TEXT NOT NULL,event_type TEXT NOT NULL,data TEXT NOT NULL);
          CREATE TABLE ai_settings(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
          CREATE TABLE ai_reports(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
              request_key TEXT NOT NULL UNIQUE,fingerprint TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL);
        ''')
        timestamp = '2026-11-01T10:00:00+00:00'
        source = json.dumps({"profile_id": "website-probe", "mode": "probe", "targets": ["https://example.invalid/"]}, indent=2)
        origin = json.dumps({"kind": "local_training", "session_id": "c" * 32, "label": "Legacy label"}, indent=2)
        asset = {"id": "a" * 32, "kind": "website", "name": "User-owned history", "source": json.loads(source), "provenance": json.loads(origin)}
        snapshot = json.dumps(asset, indent=2)
        result = json.dumps({"module": "web", "summary": {}, "evidence": [], "details": {}, "limitations": ["Historical fixture"]}, indent=2)
        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?)', (asset['id'], asset['kind'], asset['name'], source, timestamp, timestamp, origin))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)', ('b' * 32, 'web', 'Historical job', '{"mode": "probe"}', 'completed', 100, 'Saved', timestamp, timestamp, None, result))
        db.execute('INSERT INTO job_assets VALUES(?,?,?)', ('b' * 32, 'a' * 32, snapshot))
        db.execute('INSERT INTO job_requests VALUES(?,?,?)', ('original-request', 'stable-fingerprint', 'b' * 32))
        db.execute('INSERT INTO uploads VALUES(?,?,?,?,?)', ('d' * 32, 'historical.json', 2, hashlib.sha256(b'{}').hexdigest(), timestamp))
        db.execute('INSERT INTO events(job_id,created_at,level,message,progress) VALUES(?,?,?,?,?)', ('b' * 32, timestamp, 'info', 'Historical message', 100))
        db.execute('INSERT INTO engagements VALUES(?,?,?,?,?,?)', ('e' * 32, 'Historic scope', 'Preserve records', 'Synthetic fixture authorization', timestamp, timestamp))
        db.execute('INSERT INTO engagement_assets VALUES(?,?)', ('e' * 32, 'a' * 32))
        db.execute('INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('f' * 32, 'e' * 32, 'a' * 32, 'b' * 32,
            'historical-source', 'check', 'Original review task', 'low', 'observed_config', 'accepted_risk',
            'fixture-owner', '', 'Original human decision', 3, timestamp, timestamp))
        db.execute('INSERT INTO case_events(case_id,created_at,event_type,data) VALUES(?,?,?,?)', ('f' * 32, timestamp, 'status_changed', '{ "old": "open", "new": "accepted_risk" }'))
        db.execute('INSERT INTO ai_settings VALUES(?,?)', (1, '{ "enabled": false, "model": "fixture-model" }'))
        db.execute('INSERT INTO ai_reports VALUES(?,?,?,?,?,?)', ('1' * 32, 'b' * 32, 'historic-model-operation',
            'historic-model-fingerprint', 'failed', '{ "error": { "code": "AI_NETWORK_ERROR" }, "origin": "probe" }'))
        return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ['assets', 'jobs', 'job_assets', 'job_requests', 'uploads', 'events', 'engagements',
                              'engagement_assets', 'cases', 'case_events', 'ai_settings', 'ai_reports']}


def test_actual_v6_records_survive_v7_without_relabeling_or_json_reformat(tmp_path: Path) -> None:
    path = tmp_path / 'workbench.sqlite3'
    original = legacy_v6(path)
    for _ in range(2):
        repository = JobRepository(path)
        with repository.connection() as db:
            assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == 7
            assert len(db.execute('PRAGMA table_info(assets)').fetchall()) == 7
            for table, rows in original.items():
                assert [tuple(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY 1')] == rows
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        replay = repository.request_job('original-request', 'stable-fingerprint')
        assert replay is not None and replay['id'] == 'b' * 32
        assert AssetRepository(repository).get('a' * 32)['provenance']['kind'] == 'local_training'
        assert repository.get('b' * 32)['asset_snapshot']['kind'] == 'website'


def test_future_v8_is_rejected_before_file_or_journal_changes(tmp_path: Path) -> None:
    path = tmp_path / 'future.sqlite3'
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('CREATE TABLE schema_meta(version INTEGER NOT NULL); INSERT INTO schema_meta VALUES(8); CREATE TABLE future_private(value BLOB); INSERT INTO future_private VALUES(X\'000102FEFF\');')
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    before = path.read_bytes()
    with pytest.raises(WorkbenchError) as error:
        JobRepository(path)
    assert error.value.code == 'SCHEMA_UNSUPPORTED'
    assert path.read_bytes() == before
    assert not path.with_name(path.name + '-wal').exists()
    assert not path.with_name(path.name + '-shm').exists()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
