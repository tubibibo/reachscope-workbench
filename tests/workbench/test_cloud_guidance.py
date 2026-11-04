"""Cloud guides remain manual, scoped to actual selected saved checks and evidence."""

from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import urlsplit

import pytest

from reachscope_workbench.modules.cloud.guidance import implementation_guide
from reachscope_workbench.modules.cloud.module import CloudModule
from reachscope_workbench.modules.cloud.sample import demo_document

RULE_IDS = {
    "network.public_sensitive_ports", "iam.broad_allow", "iam.trust_principal",
    "storage.public_access_block", "storage.bucket_policy_principal", "storage.encryption_declaration", "storage.bucket_context",
}


def document() -> bytes:
    value = demo_document()
    value["planned_values"]["root_module"]["resources"].extend([
        {"address": "aws_s3_bucket_policy.review", "type": "aws_s3_bucket_policy", "name": "review", "values": {
            "policy": {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::fixture/*"}]}}},
        {"address": "aws_s3_bucket.context", "type": "aws_s3_bucket", "name": "context", "values": {"bucket": "fixture"}},
    ])
    return json.dumps(value).encode()


def test_all_seven_existing_rules_get_manual_evidence_bound_guidance() -> None:
    result = CloudModule._analyze(document(), {"checks": ["network", "iam", "storage"]}, "offline-fixture.json")
    checks = result.details["checks"]
    assert {row["id"] for row in checks} == RULE_IDS
    known = {row.id for row in result.evidence}
    for check in checks:
        guide = check["guidance"]
        assert guide["version"] == 1
        assert guide["rule_id"] == check["id"] and guide["resource_id"] == check["resource_id"]
        assert guide["status"] == check["status"]
        assert guide["evidence_ids"] == check["evidence_ids"] and set(guide["evidence_ids"]) <= known
        assert guide["source_pointer"] == check["evidence"]["pointer"]
        assert guide["ai_required"] is False and guide["executed"] is False and guide["deployed_state_verified"] is False
        for field in ("prerequisites", "red_review", "blue_steps", "verification", "rollback", "limitations"):
            assert guide[field] and all(isinstance(text, str) and text for text in guide[field])
        assert guide["references"]
        for ref in guide["references"]:
            parsed = urlsplit(ref["url"])
            assert parsed.scheme == "https" and parsed.hostname == "docs.aws.amazon.com" and ref["title"]


@pytest.mark.parametrize("group,prefix", [("network", "network."), ("iam", "iam."), ("storage", "storage.")])
def test_guidance_does_not_bypass_selected_check_groups(group: str, prefix: str) -> None:
    result = CloudModule._analyze(document(), {"checks": [group]}, "offline-fixture.json")
    assert result.details["checks"]
    assert all(row["id"].startswith(prefix) and row["guidance"]["rule_id"] == row["id"] for row in result.details["checks"])
    assert all(row["status"] == ("completed" if row["id"] == group else "skipped") for row in result.details["execution"])


@pytest.mark.parametrize("status", ["unknown", "pass", "info", "not_applicable", "review"])
def test_guidance_preserves_unknown_and_non_finding_states(status: str) -> None:
    check = {"id": "storage.public_access_block", "resource_id": "bucket", "status": status,
             "evidence_ids": ["stored-proof"], "evidence": {"pointer": "/resource/0"}}
    guide = implementation_guide(check)
    assert guide is not None and guide["status"] == status
    if status == "unknown":
        assert "先补充" in guide["prerequisites"][0]
    elif status in {"pass", "info", "not_applicable"}:
        assert "不要求" in guide["prerequisites"][0]
    assert check["status"] == status


@pytest.mark.parametrize("status", [None, {}, [], True, "success"])
def test_malformed_status_is_unknown_not_success(status: Any) -> None:
    guide = implementation_guide({"id": "iam.broad_allow", "status": status})
    assert guide is not None and guide["status"] == "unknown"
    assert guide["source_pointer"] == "" and guide["resource_id"] == "" and guide["evidence_ids"] == []


def test_guides_do_not_copy_private_evidence_values_or_mutate_source() -> None:
    check = {"id": "iam.trust_principal", "resource_id": "role", "status": "review", "evidence_ids": ["known"],
             "evidence": {"pointer": "/policies/0", "values": {"unrelated_secret": "secret-sentinel-DO-NOT-COPY"}}}
    before = copy.deepcopy(check)
    guide = implementation_guide(check)
    assert guide is not None and "secret-sentinel-DO-NOT-COPY" not in json.dumps(guide)
    guide["blue_steps"].clear()
    guide["evidence_ids"].clear()
    second = implementation_guide(check)
    assert second is not None and second["blue_steps"] and second["evidence_ids"] == ["known"]
    assert check == before


@pytest.mark.parametrize("identifier", ["made.up", None, 1, {}, []])
def test_unrecognized_rule_cannot_gain_a_generic_success_or_guessed_guide(identifier: Any) -> None:
    assert implementation_guide({"id": identifier}) is None


def test_unsupported_resource_has_no_invented_check_or_guide() -> None:
    raw = json.dumps({"planned_values": {"root_module": {"resources": [{
        "address": "aws_instance.unknown", "type": "aws_instance", "name": "unknown", "values": {},
    }]}}}).encode()
    result = CloudModule._analyze(raw, {"checks": ["network", "iam", "storage"]}, "fixture.json")
    assert result.details["checks"] == []
    assert result.summary["unsupported_resources"] == 1


def test_standalone_policy_guide_keeps_actual_document_root_pointer() -> None:
    raw = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}).encode()
    result = CloudModule._analyze(raw, {"checks": ["iam"]}, "policy.json")
    assert result.details["checks"][0]["guidance"]["source_pointer"] == ""
