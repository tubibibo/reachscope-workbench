"""Business-state races use saved local evidence and valid application actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.workbench.test_redblue_api import saved_cloud

from reachscope_workbench.core.case_service import CaseService
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.repository import JobRepository


def test_predicted_future_version_cannot_reclose_a_concurrently_reopened_case_without_retest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JobRepository(tmp_path / "state.sqlite3")
    asset, baseline = saved_cloud(repository)
    _, cleared = saved_cloud(repository, revision_of=asset, mitigated=True)
    service = CaseService(repository)
    engagement = service.collaboration.create_engagement("Local case race", "Review fixed synthetic data",
        "Offline fixture only; no cloud account or deployed scope claim", [asset["id"]])
    source = next(row for row in service.candidate_list(engagement["id"], baseline["id"])["items"]
                  if row["category"] == "network.public_sensitive_ports")
    case = service.create_case(engagement["id"], baseline["id"], source["source_kind"], source["source_ref"])
    closed = service.update(case["id"], case["version"], {"status": "resolved", "note": "Valid comparable fixture retest"},
                            retest_job_id=cleared["id"])
    assert closed["status"] == "resolved"

    other = CaseService(repository)
    original_read = service.collaboration.get_case
    race_once = True

    def interleaved_read(identifier: str) -> dict[str, Any]:
        nonlocal race_once
        snapshot = original_read(identifier)
        if race_once:
            race_once = False
            # Pause the first operation after its read and complete a second,
            # fully valid reopen before the first operation reaches its CAS.
            reopened = other.update(identifier, snapshot["version"], {
                "status": "open", "note": "New context requires a fresh operator decision",
            })
            assert reopened["version"] == snapshot["version"] + 1 and reopened["status"] == "open"
        return snapshot

    monkeypatch.setattr(service.collaboration, "get_case", interleaved_read)
    with pytest.raises(WorkbenchError) as failure:
        service.update(case["id"], closed["version"] + 1, {"status": "resolved", "note": "No retest selected for this update"})
    assert failure.value.code == "CASE_CONFLICT"
    latest = other.detail(case["id"])
    assert latest["status"] == "open" and latest["version"] == closed["version"] + 1
    assert latest["events"][-1]["data"]["changes"]["status"] == "open"
