"""Producer assertions cannot hide failed collection or broaden retest identity."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from reachscope_workbench.core.case_sources import candidates, compare_retest
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.host.baseline import assess_baseline
from reachscope_workbench.modules.host.input import parse_baseline, preview_baseline

SSH = "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"
NGINX = "http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; server { listen 443 ssl; server_name alias.invalid; } }"


def document(*, weak: bool = False) -> dict[str, Any]:
    return {"schema_version": "reachscope-host/2", "host_id": "host-v2", "collected_at": "2026-11-02T00:00:00Z",
            "ssh": {"effective_config": SSH.replace("permitrootlogin no", "permitrootlogin yes") if weak else SSH,
                    "connection_context": "global"}, "nginx": {"config_dump": NGINX},
            "collector": {"version": "0.14.0", "projection": "reachscope-minimal/1", "plan_sha256": "a" * 64,
                          "components": {key: {"state": "collected", "complete": True, "exit_code": 0, "reason_code": "ok"}
                                         for key in ("ssh", "nginx")}}}


def parsed(value: dict[str, Any]) -> dict[str, Any]:
    return parse_baseline(json.dumps(value).encode(), "host-v2")


def analyze(value: dict[str, Any]) -> dict[str, Any]:
    return assess_baseline(parsed(value), ["ssh", "nginx"])


def saved(value: dict[str, Any], *, name: str) -> dict[str, Any]:
    result = analyze(value)
    return {"id": name, "module": "host", "asset_id": name + "-asset", "status": "completed",
            "config": {"mode": "baseline", "host_id": "host-v2"}, "result": {"module": "host", "evidence": result["evidence"],
            "details": {"review_version": 1, "host_id": "host-v2", "checks": result["checks"],
                        "collection": {key: result["coverage"][key] for key in ("collected_at", "collection_state")},
                        "execution": [{"id": key, "status": "completed"} for key in ("ssh", "nginx")]}}}


def test_valid_v2_is_still_operator_supplied_and_evidence_hashes_include_capture() -> None:
    result = analyze(document())
    assert len(result["checks"]) == 7
    assert all(row["status"] == "pass" for row in result["checks"])
    assert result["coverage"]["source_kind"] == "operator_supplied_export"
    assert result["coverage"]["runtime_state_verified"] is False
    for proof in result["evidence"]:
        assert proof["data"]["collection"]["metadata_verified"] is False
        sha = hashlib.sha256(json.dumps(proof["data"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert proof["sha256"] == sha
    assert all(key.startswith("projected:reachscope-minimal/1:") for row in result["checks"]
               for key in row["comparison_identity"]["scope_keys"])


@pytest.mark.parametrize("component", ["ssh", "nginx"])
@pytest.mark.parametrize(("state", "reason", "code"), [
    ("unavailable", "missing_executable", None), ("failed", "nonzero_exit", 1),
    ("timeout", "command_timeout", None), ("budget_exceeded", "output_budget", None),
    ("unsupported", "projection_unsupported", 0), ("unsupported", "context_unsupported", None),
])
def test_failed_capture_cannot_attach_safe_text_and_gain_a_pass(component: str, state: str, reason: str, code: int | None) -> None:
    value = document()
    value["collector"]["components"][component] = {"state": state, "reason_code": reason, "exit_code": code, "complete": False}
    result = analyze(value)
    rows = [row for row in result["checks"] if row["id"].startswith("host." + component + ".")]
    assert rows and all(row["status"] == "unknown" and row["complete"] is False for row in rows)
    assert all(row["comparison_identity"]["complete"] is False for row in rows)
    assert result["coverage"][component]["capture"]["reason_code"] == reason


@pytest.mark.parametrize(("key", "replacement"), [("state", "future"), ("complete", 1), ("exit_code", True),
                                                   ("exit_code", 999), ("reason_code", "secret-content"),
                                                   ("complete", False), ("exit_code", 1), ("reason_code", "nonzero_exit")])
def test_inconsistent_or_unknown_collector_fields_are_rejected_without_echo(key: str, replacement: Any) -> None:
    value = document()
    value["collector"]["components"]["ssh"][key] = replacement
    with pytest.raises(WorkbenchError) as error:
        parsed(value)
    assert error.value.code == "INVALID_HOST_COLLECTION"
    assert "secret-content" not in str(error.value)


@pytest.mark.parametrize(("key", "replacement"), [("version", "9.0.0"), ("projection", "untrusted_projection"),
                                                   ("plan_sha256", "not-a-digest"), ("components", {}),
                                                   ("unexpected", "private-token")])
def test_metadata_is_versioned_and_allowlisted(key: str, replacement: Any) -> None:
    value = document()
    value["collector"][key] = replacement
    with pytest.raises(WorkbenchError) as error:
        parsed(value)
    assert error.value.code == "INVALID_HOST_COLLECTION"
    assert "private-token" not in str(error.value)


def test_preview_never_runs_rules_or_returns_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from reachscope_workbench.modules.host import baseline

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("preview executed rules")

    monkeypatch.setattr(baseline, "assess_baseline", forbidden)
    preview = preview_baseline(parsed(document()), ["ssh"])
    assert preview["collection_metadata"]["format_version"] == 2
    assert preview["analysis_executed"] is False and preview["network_requests"] is False
    assert "permitrootlogin" not in json.dumps(preview)
    assert "config_dump" not in json.dumps(preview)


def test_v1_and_projected_v2_are_not_silently_comparable_but_same_v2_is() -> None:
    before = document(weak=True)
    after = document()
    original, retest = saved(before, name="before"), saved(after, name="after")
    candidate = next(row for row in candidates(original) if row["category"] == "host.ssh.root_login")
    report = compare_retest(original, candidate["source_kind"], candidate["source_ref"], retest, related_asset_ids={"after-asset"})
    assert report["outcome"] == "not_observed_in_scope"
    v1 = copy.deepcopy(before)
    v1["schema_version"] = "reachscope-host/1"
    del v1["collector"]
    original = saved(v1, name="before")
    candidate = next(row for row in candidates(original) if row["category"] == "host.ssh.root_login")
    report = compare_retest(original, candidate["source_kind"], candidate["source_ref"], retest, related_asset_ids={"after-asset"})
    assert report["outcome"] == "not_comparable"


def test_existing_v1_preview_does_not_fabricate_collector_metadata() -> None:
    value = document()
    value["schema_version"] = "reachscope-host/1"
    del value["collector"]
    assert "collection_metadata" not in parsed(value)
    assert "collection_metadata" not in preview_baseline(parsed(value), ["ssh"])


@pytest.mark.parametrize("schema", [[], {}, True, None, 2, "reachscope-host/99"])
def test_untrusted_schema_shapes_are_validation_errors(schema: Any) -> None:
    value = document()
    value["schema_version"] = schema
    with pytest.raises(WorkbenchError) as error:
        parsed(value)
    assert error.value.code == "INVALID_HOST_INPUT"
