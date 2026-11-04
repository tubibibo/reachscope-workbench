"""Cloud preflight is local parsing, not security rule or paid model execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import LocalInputPreview, WorkbenchError
from reachscope_workbench.modules.cloud.module import CloudModule
from reachscope_workbench.modules.cloud.preview import preview_input
from reachscope_workbench.modules.cloud.rules import RULES
from reachscope_workbench.modules.cloud.sample import demo_document

HEADERS = {"X-ReachScope-Client": "workbench"}


def plan(kind: str, values: dict[str, Any], **extra: Any) -> bytes:
    return json.dumps({"planned_values": {"root_module": {"resources": [{"address": "DO_NOT_RETURN_ADDRESS", "name": "DO_NOT_RETURN_NAME", "type": kind, "values": values, **extra}]}}}).encode()


def test_preview_implements_optional_core_port_without_running_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> Any:
        raise AssertionError("Security rules must not run during input preview")

    for group in RULES:
        monkeypatch.setitem(RULES, group, forbidden)
    module = CloudModule()
    assert isinstance(module, LocalInputPreview)
    result = module.preview({"mode": "demo", "checks": ["network"]}, tmp_path)
    assert result["version"] == 1 and result["resources_total"] == 6
    assert result["supported_resources"] == 5 and result["unsupported_resources"] == 1
    assert result["selected_groups"] == ["network"]
    assert [item["id"] for item in result["group_coverage"]] == ["network"]
    assert result["analysis_executed"] is False and result["network_requests"] is False
    assert list(tmp_path.iterdir()) == []


def test_preview_suppresses_names_addresses_values_and_sensitive_markers(tmp_path: Path) -> None:
    data = plan("aws_iam_policy", {"policy": {"Statement": [{"Effect": "Allow", "Action": "PRIVATE_ACTION", "Resource": "PRIVATE_RESOURCE"}]}, "secret_key": "PRIVATE_KEY"})
    result = preview_input(data, ["iam"])
    text = json.dumps(result)
    assert all(value not in text for value in ("DO_NOT_RETURN_ADDRESS", "DO_NOT_RETURN_NAME", "PRIVATE_ACTION", "PRIVATE_RESOURCE", "PRIVATE_KEY"))
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    result = preview_input(plan("SENSITIVE_UNKNOWN_TYPE", {"PRIVATE_FIELD": "PRIVATE_VALUE"}), ["iam"])
    assert result["resource_types"] == [{"type": "unsupported_resource", "count": 1, "supported": False}]
    assert "SENSITIVE_UNKNOWN_TYPE" not in json.dumps(result)


@pytest.mark.parametrize(("values", "extra", "state"), [({}, {}, "missing"), ({"policy": None}, {}, "invalid"),
                                                         ({"policy": "malformed"}, {}, "invalid"),
                                                         ({"policy": "secret"}, {"sensitive_values": {"policy": True}}, "redacted"),
                                                         ({"policy": {}}, {"sensitive_values": {"policy": {"nested": True}}}, "invalid")])
def test_field_coverage_preserves_missing_unknown_redacted_invalid(values: dict[str, Any], extra: dict[str, Any], state: str) -> None:
    result = preview_input(plan("aws_iam_policy", values, **extra), ["iam"])
    assert result["field_gaps"][0]["state"] == state
    assert result["field_gaps"][0]["pointer"] == "/planned_values/root_module/resources/0/values" + ("/policy" if "policy" in values else "")
    assert result["group_coverage"][0][state + "_fields"] > 0


def test_plan_unknown_fields_and_empty_statement_are_not_known() -> None:
    raw = json.loads(plan("aws_iam_policy", {"policy": {"Statement": []}}))
    raw["resource_changes"] = [{"address": "DO_NOT_RETURN_ADDRESS", "change": {"after_unknown": {"policy": True}}}]
    result = preview_input(json.dumps(raw).encode(), ["iam"])
    assert result["field_gaps"][0]["state"] == "unknown"
    result = preview_input(plan("aws_iam_policy", {"policy": {"Statement": []}}), ["iam"])
    assert any(item["field"] == "Statement" and item["state"] == "missing" for item in result["field_gaps"])


def test_network_nested_fields_coverage_does_not_report_security_outcome() -> None:
    data = plan("aws_security_group", {"ingress": [{"protocol": "tcp", "from_port": True, "to_port": 22}]})
    result = preview_input(data, ["network"])
    fields = {item["field"]: item for item in result["field_gaps"]}
    assert fields["from_port"]["state"] == "invalid"
    assert fields["source_ranges"]["state"] == "missing"
    assert not {"review", "pass", "safe"}.intersection(result)
    assert all("evidence_ids" not in item for item in result["field_gaps"])


@pytest.mark.parametrize("document", [
    {"Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "private-value"}]},
    {"SecurityGroups": [{"GroupId": "private-group", "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": []}]}]},
    {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True}},
])
def test_supported_export_formats_have_safe_preview(document: dict[str, Any]) -> None:
    result = preview_input(json.dumps(document).encode(), ["network", "iam", "storage"])
    assert result["resources_total"] == 1
    assert "private-value" not in json.dumps(result) and "private-group" not in json.dumps(result)


def test_storage_encryption_and_missing_related_context_have_field_coverage() -> None:
    result = preview_input(plan("aws_s3_bucket_server_side_encryption_configuration", {}), ["storage"])
    assert result["field_gaps"][0]["field"] == "rule"
    result = preview_input(plan("aws_s3_bucket", {}), ["storage"])
    assert result["field_gaps"][0]["field"] == "related_configuration"


@pytest.mark.parametrize("data", [b"[]", b"not JSON", b'{"Statement":[],"Statement":[]}', b'{"unknown":"SECRET_PAYLOAD"}'])
def test_unsupported_or_malformed_inputs_are_actionable_without_echoing(data: bytes) -> None:
    with pytest.raises(WorkbenchError) as caught:
        preview_input(data, ["iam"])
    assert caught.value.code in {"INVALID_CLOUD_INPUT", "CLOUD_INPUT_LIMIT"}
    assert "SECRET_PAYLOAD" not in str(caught.value)


def test_duplicate_addresses_are_rejected_and_gaps_are_bounded() -> None:
    raw = demo_document()
    resources = raw["planned_values"]["root_module"]["resources"]
    resources.append(resources[0])
    with pytest.raises(WorkbenchError, match="资源地址重复"):
        preview_input(json.dumps(raw).encode(), ["network"])
    document = {"SecurityGroups": [{} for _ in range(100)]}
    result = preview_input(json.dumps(document).encode(), ["network"])
    assert result["field_gaps_total"] == 100 and len(result["field_gaps"]) == 80 and result["truncated"]


def uploaded_asset(client: TestClient, data: bytes) -> dict[str, Any]:
    upload = client.post("/api/uploads", files={"file": ("config.json", data)}, headers=HEADERS).json()
    response = client.post("/api/assets", json={"kind": "cloud", "name": "Cloud preview fixture", "source": {
        "profile_id": "cloud-config", "mode": "import", "upload_id": upload["id"], "filename": upload["filename"]}}, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def test_real_preflight_returns_preview_and_creates_no_jobs(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = uploaded_asset(client, json.dumps(demo_document()).encode())
        before = set(tmp_path.rglob("*"))
        response = client.post(f"/api/assets/{saved['id']}/preflight", json={"checks": ["network"]}, headers=HEADERS)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ready"] and data["input_preview"]["resources_total"] == 6
        assert data["input_preview"]["selected_groups"] == ["network"]
        assert client.get("/api/jobs").json()["total"] == 0
        assert set(tmp_path.rglob("*")) == before


def test_real_preflight_blocks_malformed_file_and_inspection_before_job_creation(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = uploaded_asset(client, b'{"unrecognized":"DO_NOT_LEAK"}')
        response = client.post(f"/api/assets/{saved['id']}/preflight", json={"checks": ["network"]}, headers=HEADERS)
        assert response.status_code == 200 and not response.json()["ready"]
        assert "input_preview" not in response.json() and "DO_NOT_LEAK" not in response.text
        assert next(item for item in response.json()["items"] if item["id"] == "input_preview")["status"] == "blocked"
        submitted = client.post(f"/api/assets/{saved['id']}/inspections", json={"checks": ["network"]}, headers=HEADERS)
        assert submitted.status_code == 409 and submitted.json()["error"]["code"] == "PREFLIGHT_BLOCKED"
        assert client.get("/api/jobs").json()["total"] == 0


def test_file_readiness_blocks_preview_before_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(tmp_path)) as client:
        saved = uploaded_asset(client, b'{"Statement":[]}')
        (tmp_path / "uploads" / saved["source"]["upload_id"]).unlink()

        def forbidden(*args: Any) -> Any:
            raise AssertionError("Preview ran before local file readiness")

        monkeypatch.setattr(CloudModule, "preview", forbidden)
        response = client.post(f"/api/assets/{saved['id']}/preflight", json={"checks": ["iam"]}, headers=HEADERS)
        assert response.status_code == 200 and not response.json()["ready"]
        assert "input_preview" not in response.json()
