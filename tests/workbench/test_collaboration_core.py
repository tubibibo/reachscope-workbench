"""Scope, immutable sources and versioned red/blue decisions survive real storage."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.assets import AssetRepository
from reachscope_workbench.core.collaboration import CASE_STATUSES, CollaborationRepository
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository


def fixture(root: Path) -> tuple[JobRepository, CollaborationRepository, dict[str, Any], dict[str, Any], dict[str, Any]]:
    jobs = JobRepository(root / "workbench.sqlite3")
    asset = AssetRepository(jobs).create("cloud", "Cloud sample", {"profile_id": "cloud-demo", "mode": "demo"})
    job = jobs.create("cloud", "Completed inspection", {"mode": "demo"}, asset=asset)
    assert jobs.transition(job["id"], {"queued"}, "completed", "saved", result={"evidence": [], "observations": []})
    repository = CollaborationRepository(jobs)
    engagement = repository.create_engagement("Scoped review", "Review configuration", "Local synthetic input", [asset["id"]])
    return jobs, repository, asset, job, engagement


def case_at(repository: CollaborationRepository, asset: dict[str, Any], job: dict[str, Any], engagement: dict[str, Any],
            *, source: str = "check-1", key: str | None = None) -> dict[str, Any]:
    return repository.create_case(engagement["id"], asset["id"], job["id"], source, "check", "Inspect configuration", "low", "observed", idempotency_key=key)


@pytest.mark.parametrize("old_version", [1, 2, 3])
def test_additive_v4_migration_retains_legacy_jobs_assets_and_requests(tmp_path: Path, old_version: int) -> None:
    jobs, _repository, asset, job, _engagement = fixture(tmp_path)
    with jobs.connection() as db:
        for table in ("case_requests", "case_events", "case_retest_inputs", "cases", "engagement_requests", "engagement_assets", "engagements"):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE schema_meta SET version=?", (old_version,))
    reopened = JobRepository(jobs.path)
    with reopened.connection() as db:
        assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 7
    assert reopened.get(job["id"])["asset_id"] == asset["id"]
    assert AssetRepository(reopened).get(asset["id"])["name"] == "Cloud sample"
    assert CollaborationRepository(reopened).list_engagements()["total"] == 0


def test_future_schema_is_not_mutated(tmp_path: Path) -> None:
    jobs, *_ = fixture(tmp_path)
    with jobs.connection() as db:
        db.execute("UPDATE schema_meta SET version=999")
    before = hashlib.sha256(jobs.path.read_bytes()).hexdigest()
    with pytest.raises(WorkbenchError) as failure:
        JobRepository(jobs.path)
    assert failure.value.code == "SCHEMA_UNSUPPORTED"
    assert hashlib.sha256(jobs.path.read_bytes()).hexdigest() == before


def test_scope_is_persisted_and_case_counts_reflect_only_this_engagement(tmp_path: Path) -> None:
    jobs, repository, asset, job, engagement = fixture(tmp_path)
    created = case_at(repository, asset, job, engagement)
    assert created["asset_name"] == asset["name"] and created["job_name"] == job["name"]
    reopened = CollaborationRepository(JobRepository(jobs.path))
    saved = reopened.get_engagement(engagement["id"])
    assert saved["assets"] == [{"id": asset["id"], "kind": "cloud", "name": asset["name"]}]
    assert saved["asset_ids"] == [asset["id"]] and saved["asset_count"] == 1
    assert saved["case_count"] == 1 and saved["case_counts"] == {status: int(status == "open") for status in CASE_STATUSES}
    assert reopened.list_engagements()["items"][0]["case_counts"]["open"] == 1
    assert reopened.list_cases(engagement["id"])["total"] == 1


def test_case_cannot_escape_scope_or_relabel_a_job_asset(tmp_path: Path) -> None:
    jobs, repository, asset, job, engagement = fixture(tmp_path)
    other = AssetRepository(jobs).create("website", "Other", {"profile_id": "website-demo", "mode": "demo"})
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, other, job, engagement)
    assert failure.value.code == "OUT_OF_SCOPE"
    scoped = repository.create_engagement("Both", "", "", [asset["id"], other["id"]])
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, other, job, scoped)
    assert failure.value.code == "ASSET_MISMATCH"
    incomplete = jobs.create("web", "Not finished", {"mode": "demo"}, asset=other)
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, other, incomplete, scoped)
    assert failure.value.code == "RESULT_UNAVAILABLE"
    assert repository.list_cases()["total"] == 0


def test_missing_scope_and_job_fail_without_partial_records(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    with pytest.raises(WorkbenchError) as failure:
        repository.create_engagement("Bad scope", "", "", ["0" * 32])
    assert failure.value.code == "ASSET_NOT_FOUND"
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, asset, job, {"id": "0" * 32})
    assert failure.value.code == "ENGAGEMENT_NOT_FOUND"
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, asset, {"id": "0" * 32}, engagement)
    assert failure.value.code == "JOB_NOT_FOUND"
    assert repository.list_engagements()["total"] == 1


def test_same_source_and_request_replay_do_not_duplicate_events(tmp_path: Path) -> None:
    jobs, repository, asset, job, engagement = fixture(tmp_path)
    first = case_at(repository, asset, job, engagement, key="one-request")
    assert case_at(repository, asset, job, engagement, key="one-request")["id"] == first["id"]
    assert case_at(repository, asset, job, engagement)["id"] == first["id"]
    assert case_at(repository, asset, job, engagement, key="another-request")["id"] == first["id"]
    reopened = CollaborationRepository(JobRepository(jobs.path))
    assert case_at(reopened, asset, job, engagement, key="one-request")["id"] == first["id"]
    assert len(reopened.get_events(first["id"])["items"]) == 1
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, asset, job, engagement, source="another-source", key="one-request")
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"
    assert repository.list_cases()["total"] == 1


def test_parallel_promotions_of_one_source_create_one_case(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: case_at(repository, asset, job, engagement), range(8)))
    assert len({row["id"] for row in rows}) == 1
    assert len(repository.get_events(rows[0]["id"])["items"]) == 1


def test_versioned_update_is_atomic_with_its_history(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    updated = repository.update_case(case["id"], 1, {"status": "in_progress", "owner": "Responder", "due_date": "2026-11-30", "note": "Investigating"})
    assert updated["version"] == 2 and updated["owner"] == "Responder" and updated["due_date"] == "2026-11-30"
    with pytest.raises(WorkbenchError) as failure:
        repository.update_case(case["id"], 1, {"status": "ready_for_retest"})
    assert failure.value.code == "CASE_CONFLICT"
    events = repository.get_events(case["id"])["items"]
    assert len(events) == 2 and events[-1]["data"]["changes"]["status"] == "in_progress"
    assert repository.get_case(case["id"])["version"] == 2


@pytest.mark.parametrize("status", ["resolved", "accepted_risk", "false_positive"])
def test_decisions_require_a_fresh_explanation_even_after_prior_notes(tmp_path: Path, status: str) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    repository.update_case(case["id"], 1, {"note": "An earlier investigation note"})
    with pytest.raises(WorkbenchError) as failure:
        repository.update_case(case["id"], 2, {"status": status})
    assert failure.value.code == "DECISION_NOTE_REQUIRED"
    decided = repository.update_case(case["id"], 2, {"status": status, "note": "Current decision and evidence context"})
    assert decided["status"] == status and decided["version"] == 3


def test_retest_event_and_decision_share_version_without_overriding_audit_metadata(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    updated = repository.update_case(case["id"], 1, {}, event_type="retest_recorded", event_data={"retest_job_id": "f" * 32, "version": 99})
    assert updated["version"] == 2
    event = repository.get_events(case["id"])["items"][-1]
    assert event["event_type"] == "retest_recorded" and event["data"]["version"] == 2 and event["data"]["retest_job_id"] == "f" * 32
    assert event["data"]["changes"] == {}


@pytest.mark.parametrize("patch", [{"due_date": "2026-02-30"}, {"due_date": "2026-1-01"}, {"due_date": False},
                                  {"status": "done"}, {"owner": "x" * 81}, {"note": "x" * 4001},
                                  {"job_id": "new-source"}, {"owner": "\ud800"}, {}])
def test_invalid_updates_preserve_case_and_event_count(tmp_path: Path, patch: dict[str, Any]) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    with pytest.raises(WorkbenchError):
        repository.update_case(case["id"], 1, patch)
    assert repository.get_case(case["id"])["version"] == 1 and len(repository.get_events(case["id"])["items"]) == 1


def test_non_json_or_oversized_event_fails_before_mutation(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    for event in ({"score": float("nan")}, {"text": "x" * 17000}, {"bad": object()}, {"key": "\ud800"}):
        with pytest.raises(WorkbenchError) as failure:
            repository.update_case(case["id"], 1, {"note": "must not persist"}, event_data=event)
        assert failure.value.code == "INVALID_CASE_EVENT"
    assert repository.get_case(case["id"])["note"] == ""


def test_paging_filters_and_unknown_ids_are_explicit(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    first = case_at(repository, asset, job, engagement)
    case_at(repository, asset, job, engagement, source="check-2")
    repository.update_case(first["id"], 1, {"status": "in_progress"})
    assert repository.list_cases(status="in_progress")["total"] == 1
    assert len(repository.list_cases(limit=1, offset=1)["items"]) == 1
    events = repository.get_events(first["id"], limit=1)
    assert len(events["items"]) == 1 and len(repository.get_events(first["id"], after=events["next_cursor"])["items"]) == 1
    for action in [lambda: repository.list_cases(limit=0), lambda: repository.list_engagements(offset=-1),
                   lambda: repository.list_cases(status="unknown"), lambda: repository.get_events(first["id"], after=-1),
                   lambda: repository.get_case("0" * 32), lambda: repository.get_events("0" * 32), lambda: repository.get_engagement("0" * 32)]:
        with pytest.raises(WorkbenchError):
            action()


@pytest.mark.parametrize("assets", [[], ["x"] * 101, [None], "asset-id"])
def test_invalid_scope_is_not_saved(tmp_path: Path, assets: Any) -> None:
    _, repository, *_ = fixture(tmp_path)
    with pytest.raises(WorkbenchError):
        repository.create_engagement("Bad", "", "", assets)
    assert repository.list_engagements()["total"] == 1


def test_event_payload_is_an_independent_saved_copy(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    payload = {"assessment": {"status": "not_comparable", "reasons": ["not collected"]}}
    repository.update_case(case["id"], 1, {}, event_type="retest_recorded", event_data=payload)
    payload["assessment"]["reasons"].append("later mutation")
    saved = repository.get_events(case["id"])["items"][-1]
    assert "later mutation" not in json.dumps(saved)


def test_engagement_request_replay_and_scope_conflict_survive_restart(tmp_path: Path) -> None:
    jobs, repository, asset, _job, _engagement = fixture(tmp_path)
    first = repository.create_engagement("Scoped", "Review", "Local", [asset["id"]], idempotency_key="create-project")
    reopened = CollaborationRepository(JobRepository(jobs.path))
    assert reopened.create_engagement(" Scoped ", "Review", "Local", [asset["id"], asset["id"]], idempotency_key="create-project")["id"] == first["id"]
    with pytest.raises(WorkbenchError) as failure:
        reopened.create_engagement("Different", "Review", "Local", [asset["id"]], idempotency_key="create-project")
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"
    assert repository.list_engagements()["total"] == 2


def test_revised_input_is_case_scoped_and_preserves_original_source(tmp_path: Path) -> None:
    jobs, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    revised = AssetRepository(jobs).create("cloud", "Revised configuration", {"profile_id": "cloud-config", "mode": "import", "upload_id": "b" * 32})
    updated = repository.add_retest_input(case["id"], 1, revised["id"], "Explicit revised input for this case")
    assert updated["version"] == 2 and updated["asset_id"] == asset["id"] and updated["job_id"] == job["id"]
    assert repository.get_engagement(engagement["id"])["asset_ids"] == [asset["id"]]
    inputs = repository.get_retest_inputs(case["id"])
    assert inputs[0]["source"]["upload_id"] == "b" * 32 and inputs[0]["id"] == revised["id"] and inputs[0]["linked_at"]
    assert repository.add_retest_input(case["id"], 2, revised["id"], "Same current input")["version"] == 2
    assert len(repository.get_events(case["id"])["items"]) == 2
    with pytest.raises(WorkbenchError) as failure:
        repository.add_retest_input(case["id"], 1, revised["id"], "Stale client")
    assert failure.value.code == "CASE_CONFLICT"
    with pytest.raises(WorkbenchError) as failure:
        case_at(repository, revised, job, engagement)
    assert failure.value.code == "OUT_OF_SCOPE"


def test_retest_input_errors_leave_case_and_audit_unchanged(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    with pytest.raises(WorkbenchError) as failure:
        repository.add_retest_input(case["id"], 1, "0" * 32, "Missing input")
    assert failure.value.code == "ASSET_NOT_FOUND"
    with pytest.raises(WorkbenchError):
        repository.add_retest_input(case["id"], 1, asset["id"], " ")
    assert repository.get_case(case["id"])["version"] == 1
    assert repository.get_retest_inputs(case["id"]) == []


def test_competing_updates_have_one_version_winner_and_one_event(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)

    def update(owner: str) -> str:
        try:
            repository.update_case(case["id"], 1, {"owner": owner})
            return "updated"
        except WorkbenchError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, ["First", "Second"]))
    assert sorted(outcomes) == ["CASE_CONFLICT", "updated"]
    assert repository.get_case(case["id"])["version"] == 2
    assert len(repository.get_events(case["id"])["items"]) == 2


def test_event_failure_rolls_back_a_case_update_already_issued_in_transaction(tmp_path: Path) -> None:
    _, repository, asset, job, engagement = fixture(tmp_path)
    case = case_at(repository, asset, job, engagement)
    # Each individual field is valid; the combined audit payload exceeds its
    # budget only after UPDATE, proving the decision and event share rollback.
    with pytest.raises(WorkbenchError) as failure:
        repository.update_case(case["id"], 1, {"note": "n" * 4000}, event_data={"detail": "d" * 14000})
    assert failure.value.code == "INVALID_CASE_EVENT"
    assert repository.get_case(case["id"])["note"] == "" and repository.get_case(case["id"])["version"] == 1
    assert len(repository.get_events(case["id"])["items"]) == 1
