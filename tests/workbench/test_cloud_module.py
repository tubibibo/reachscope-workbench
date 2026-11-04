"""Offline cloud review: bounded input, conservative semantics and actual rule selection."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.modules.cloud import CloudModule
from reachscope_workbench.modules.cloud.input import MAX_BYTES, REDACTED, UNKNOWN, parse_input
from reachscope_workbench.modules.cloud.rules import RULES
from reachscope_workbench.modules.cloud.sample import demo_document


def plan(kind: str, values: dict[str, Any], **extras: Any) -> dict[str, Any]:
    return {"format_version": "1.2", "planned_values": {"root_module": {"resources": [
        {"address": "resource.test", "type": kind, "name": "test", "values": values, **extras}]}}}


def analyze(document: dict[str, Any], checks: list[str] | None = None) -> dict[str, Any]:
    return CloudModule._analyze(json.dumps(document).encode(), {"mode": "import", "checks": checks or ["network", "iam", "storage"]}, "config.json").to_dict()


def outcome(document: dict[str, Any]) -> dict[str, Any]:
    return analyze(document)["details"]["checks"][0]


def policy(statement: Any) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": statement}


def test_demo_real_module_progress_evidence_and_no_cloud_io(tmp_path: Path) -> None:
    progress = []
    result = asyncio.run(CloudModule().run({"mode": "demo"}, RunContext("job", tmp_path, tmp_path, lambda value, message: progress.append(value))))
    assert result.summary["resources"] == 6 and result.summary["review_checks"] == 4
    assert result.summary["unsupported_resources"] == 1
    assert progress == [5, 25, 100]
    ids = {item.id for item in result.evidence}
    assert all(set(check["evidence_ids"]) <= ids for check in result.details["checks"])
    assert all(set(item.evidence_ids) <= ids and item.confidence == "static_config" for item in result.observations)
    assert "intentionally never persisted" not in json.dumps(result.to_dict())
    assert "synthetic-condition" not in json.dumps(result.to_dict())
    assert not result.details["deployed_state_verified"]


def test_selected_group_only_executes_selected_rule_function(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_: Any) -> list[Any]:
        raise AssertionError("Unselected rule executed")
    monkeypatch.setitem(RULES, "iam", forbidden)
    monkeypatch.setitem(RULES, "storage", forbidden)
    result = analyze(demo_document(), ["network"])
    assert result["summary"]["checks"] == 1
    assert [item["status"] for item in result["details"]["execution"]] == ["completed", "skipped", "skipped"]


@pytest.mark.parametrize("config", [{"mode": "probe"}, {"checks": []}, {"checks": "network"}, {"checks": ["nope"]},
                                   {"checks": [True]}, {"mode": "import", "upload_id": "../file", "filename": "x.json"},
                                   {"mode": "import", "upload_id": "a" * 32, "filename": "x.yaml"}])
def test_invalid_config_rejected(config: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError):
        CloudModule().validate(config)


def test_checks_deduplicate_and_upload_basename_is_metadata() -> None:
    config = CloudModule().validate({"mode": "import", "upload_id": "a" * 32, "filename": "some/path/config.json", "checks": ["iam", "iam"]})
    assert config["filename"] == "config.json" and config["checks"] == ["iam"]


def test_import_reads_uploaded_file(tmp_path: Path) -> None:
    (tmp_path / ("a" * 32)).write_text(json.dumps(policy({"Effect": "Allow", "Action": "*", "Resource": "*"})))
    result = asyncio.run(CloudModule().run({"mode": "import", "upload_id": "a" * 32, "filename": "policy.json"},
                                         RunContext("job", tmp_path, tmp_path, lambda *_: None)))
    assert result.details["input_kind"] == "iam_policy" and result.summary["review_checks"] == 1
    with pytest.raises(WorkbenchError):
        asyncio.run(CloudModule().run({"mode": "import", "upload_id": "b" * 32, "filename": "policy.json"},
                                     RunContext("job", tmp_path, tmp_path, lambda *_: None)))


@pytest.mark.parametrize("values,status", [
    ({"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}]}, "review"),
    ({"ingress": [{"protocol": "6", "from_port": 3306, "to_port": 3306, "ipv6_cidr_blocks": ["::/0"]}]}, "review"),
    ({"ingress": [{"protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}]}, "review"),
    ({"ingress": [{"protocol": "tcp", "from_port": 443, "to_port": 443, "cidr_blocks": ["0.0.0.0/0"]}]}, "pass"),
    ({"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["10.0.0.0/8"]}]}, "pass"),
    ({"ingress": [{"protocol": "udp", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}]}, "pass"),
    ({"ingress": []}, "pass"), ({}, "unknown"), ({"ingress": UNKNOWN}, "unknown"),
    ({"ingress": [{"protocol": "tcp", "from_port": True, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}]}, "unknown"),
    ({"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["bad"]}]}, "unknown"),
])
def test_network_rules_are_configuration_not_connectivity(values: dict[str, Any], status: str) -> None:
    check = outcome(plan("aws_security_group", values))
    assert check["status"] == status
    if status == "review":
        assert "实际监听" in check["description"]


def test_standalone_ingress_and_egress_are_distinguished() -> None:
    values = {"type": "egress", "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}
    assert outcome(plan("aws_security_group_rule", values))["status"] == "not_applicable"
    values["type"] = "ingress"
    assert outcome(plan("aws_security_group_rule", values))["status"] == "review"
    assert outcome(plan("aws_vpc_security_group_ingress_rule", {"ip_protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_ipv4": "0.0.0.0/0"}))["status"] == "review"


def test_terraform_child_modules_unknown_and_sensitive_merge() -> None:
    document = plan("aws_security_group", {"ingress": []})
    entry = document["planned_values"]["root_module"]["resources"][0]
    document["planned_values"]["root_module"] = {"child_modules": [{"resources": [entry]}]}
    document["resource_changes"] = [{"address": "resource.test", "change": {"after_unknown": {"ingress": True}}}]
    assert outcome(document)["status"] == "unknown"
    document = plan("aws_iam_policy", {"policy": "SECRET_POLICY"}, sensitive_values={})
    document["resource_changes"] = [{"address": "resource.test", "change": {"after_sensitive": {"policy": True}}}]
    result = analyze(document)
    assert "SECRET_POLICY" not in json.dumps(result) and REDACTED in json.dumps(result)
    assert result["details"]["checks"][0]["status"] == "unknown"


def test_extra_list_masks_and_unknown_directions_are_not_safe_defaults() -> None:
    for direction in (None, UNKNOWN, REDACTED, "unexpected"):
        assert outcome(plan("aws_security_group_rule", {"type": direction, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}))["status"] == "unknown"
    document = plan("aws_security_group", {"ingress": []})
    document["resource_changes"] = [{"address": "resource.test", "change": {"after_unknown": {"ingress": [True]}}}]
    assert outcome(document)["status"] == "unknown"
    document["planned_values"]["root_module"]["resources"][0]["values"] = {}
    assert outcome(document)["status"] == "unknown"


@pytest.mark.parametrize("version", [[], {}, None, "secret-version"])
def test_malformed_policy_version_is_not_retained(version: Any) -> None:
    document = policy({"Effect": "Allow", "Action": "*", "Resource": "*"})
    document["Version"] = version
    result = analyze(document)
    assert result["summary"]["review_checks"] == 1
    assert result["evidence"][0]["data"]["values"]["policy"]["Version"] == ""


@pytest.mark.parametrize("statement,status", [
    ({"Effect": "Allow", "Action": "*", "Resource": "*"}, "review"),
    ({"Effect": "Allow", "Action": ["s3:*"], "Resource": ["*"]}, "review"),
    ({"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}, "info"),
    ({"Effect": "Allow", "Action": "s3:*", "Resource": "arn:aws:s3:::specific/*"}, "info"),
    ({"Effect": "Deny", "Action": "*", "Resource": "*"}, "info"),
    ({"Effect": "Allow", "NotAction": "s3:*", "Resource": "*"}, "unknown"),
    ({"Effect": "Allow", "Action": "*", "NotResource": "x"}, "unknown"),
    ({"Effect": "Allow", "Action": UNKNOWN, "Resource": "*"}, "unknown"),
    ({"Effect": "Allow", "Action": "*"}, "unknown"),
    ({"Effect": "Unexpected", "Action": "*", "Resource": "*"}, "unknown"),
])
def test_iam_policy_review_does_not_compute_effective_permissions(statement: dict[str, Any], status: str) -> None:
    check = outcome(policy(statement))
    assert check["status"] == status and not check["evidence"]["values"]["effective_permissions_evaluated"]


def test_condition_values_omitted_and_explicit_deny_retained_as_context() -> None:
    document = policy([{"Effect": "Allow", "Action": "*", "Resource": "*", "Condition": {"StringEquals": {"sts:ExternalId": "SECRET_EXTERNAL_ID"}}},
                       {"Effect": "Deny", "Action": "*", "Resource": "*", "Unused": "SECRET_UNUSED"}])
    result = analyze(document)
    encoded = json.dumps(result)
    assert "SECRET_EXTERNAL_ID" not in encoded and "SECRET_UNUSED" not in encoded
    check = result["details"]["checks"][0]
    assert check["status"] == "review" and check["evidence"]["values"]["deny_statements_not_evaluated"] == 1
    assert check["evidence"]["values"]["conditioned_statements"] == 1


def test_trust_and_bucket_wildcard_principal_rules() -> None:
    value = policy({"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": "*"}})
    assert outcome(plan("aws_iam_role", {"assume_role_policy": value}))["id"] == "iam.trust_principal"
    assert outcome(plan("aws_s3_bucket_policy", {"policy": value}))["status"] == "review"
    value["Statement"]["Principal"] = {"AWS": "arn:aws:iam::123456789012:root"}
    assert outcome(plan("aws_iam_role", {"assume_role_policy": json.dumps(value)}))["status"] == "info"


@pytest.mark.parametrize("flags,status", [({"block_public_acls": True, "block_public_policy": True, "ignore_public_acls": True, "restrict_public_buckets": True}, "pass"),
                                        ({"block_public_acls": False}, "review"), ({"block_public_acls": True}, "unknown"),
                                        ({"block_public_acls": "false"}, "unknown")])
def test_bucket_public_access_protection_is_not_public_access_proof(flags: dict[str, Any], status: str) -> None:
    assert outcome(plan("aws_s3_bucket_public_access_block", flags))["status"] == status


def test_bucket_encryption_and_missing_associations_never_claim_plaintext() -> None:
    assert outcome(plan("aws_s3_bucket", {"secret": "IGNORED"}))["status"] == "unknown"
    document = plan("aws_s3_bucket_server_side_encryption_configuration", {"rule": [{"apply_server_side_encryption_by_default": [{"sse_algorithm": "aws:kms", "secret": "IGNORED"}]}]})
    result = analyze(document)
    assert result["details"]["checks"][0]["status"] == "info" and "IGNORED" not in json.dumps(result)
    assert outcome(plan("aws_s3_bucket_server_side_encryption_configuration", {}))["status"] == "unknown"


def test_aws_export_adapters() -> None:
    group = {"GroupId": "sg-test", "GroupName": "demo", "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
              "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "IGNORED"}]}]}
    assert outcome({"SecurityGroups": [group]})["status"] == "review"
    assert outcome({"PublicAccessBlockConfiguration": {"BlockPublicAcls": False}})["status"] == "review"


@pytest.mark.parametrize("data", [b'{}', b'[]', b'{"x":1,"x":2}', b'{"Statement":NaN}', b'not json',
                                 json.dumps({"planned_values": {"root_module": {"resources": []}}}).encode(),
                                 json.dumps({"format_version": "2.0", "planned_values": {"root_module": {}}}).encode()])
def test_unrecognized_invalid_or_empty_input_rejected(data: bytes) -> None:
    with pytest.raises(WorkbenchError):
        parse_input(data)


def test_budget_overflow_and_duplicate_resource_addresses_are_explicit() -> None:
    with pytest.raises(WorkbenchError) as error:
        parse_input(b"x" * (MAX_BYTES + 1))
    assert error.value.code == "CLOUD_INPUT_LIMIT"
    document = plan("aws_instance", {})
    entries = document["planned_values"]["root_module"]["resources"]
    entries.append(entries[0])
    with pytest.raises(WorkbenchError):
        analyze(document)
    entries.extend(entries * 250)
    with pytest.raises(WorkbenchError) as error:
        parse_input(json.dumps(document).encode())
    assert error.value.code == "CLOUD_INPUT_LIMIT"
    with pytest.raises(WorkbenchError):
        parse_input(json.dumps(policy([{"Effect": "Deny"}] * 1001)).encode())


def test_one_thousand_statements_allowed_but_total_budget_still_applies() -> None:
    document = policy([{"Effect": "Deny", "Action": "*", "Resource": "*"}] * 1000)
    assert outcome(document)["evidence"]["values"]["deny_statements_not_evaluated"] == 1000
    document = plan("aws_iam_policy", {"policy": policy([{"Effect": "Deny"}] * 600)})
    extra = {"address": "aws_iam_policy.other", "type": "aws_iam_policy", "values": {"policy": policy([{"Effect": "Deny"}] * 401)}}
    document["planned_values"]["root_module"]["resources"].append(extra)
    with pytest.raises(WorkbenchError):
        analyze(document)


@pytest.mark.parametrize("marker", [{"Statement": True}, [True]])
def test_mismatched_nested_sensitive_markers_do_not_reveal_scalar_policy(marker: Any) -> None:
    secret_policy = json.dumps(policy({"Effect": "Allow", "Action": "*", "Resource": "SECRET_RESOURCE"}))
    document = plan("aws_iam_policy", {"policy": secret_policy}, sensitive_values={"policy": marker})
    result = analyze(document)
    assert "SECRET_RESOURCE" not in json.dumps(result)
    assert result["evidence"][0]["data"]["values"]["policy"] == REDACTED
    assert result["details"]["checks"][0]["status"] == "unknown"
    document["resource_changes"] = [{"address": "resource.test", "change": {"after_unknown": {"policy": True}}}]
    assert analyze(document)["evidence"][0]["data"]["values"]["policy"] == REDACTED


@pytest.mark.parametrize("marker", [{"Statement": True}, [True]])
def test_mismatched_nested_unknown_markers_do_not_evaluate_scalar_policy(marker: Any) -> None:
    document = plan("aws_iam_policy", {"policy": json.dumps(policy({"Effect": "Allow", "Action": "*", "Resource": "*"}))})
    document["resource_changes"] = [{"address": "resource.test", "change": {"after_unknown": {"policy": marker}}}]
    result = analyze(document)
    assert result["evidence"][0]["data"]["values"]["policy"] == UNKNOWN
    assert result["details"]["checks"][0]["status"] == "unknown"
