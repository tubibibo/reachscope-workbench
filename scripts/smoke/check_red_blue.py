"""Verify evidence-backed red/blue workflows through a running local HTTP API.

Creates only synthetic offline cloud inputs; does not alter service configuration,
access the workspace database, contact a cloud account or probe another target.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def synthetic_plan(*, cidr: str, address: str = "aws_security_group.review") -> dict[str, Any]:
    return {"format_version": "1.2", "terraform_version": "synthetic", "planned_values": {"root_module": {
        "resources": [{"address": address, "type": "aws_security_group", "name": "review", "values": {
            "ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": [cidr],
                         "ipv6_cidr_blocks": []}]}}]}}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/redblue-validation"))
    args = parser.parse_args()
    endpoint = urlsplit(args.base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--base-url must be a local HTTP service")
    args.out.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    checks: list[dict[str, Any]] = []
    report: dict[str, Any] = {"run_id": run_id, "started_at": datetime.now(UTC).isoformat(),
                              "base_url": args.base_url, "checks": checks, "assets": {}, "jobs": {}, "requests": [],
                              "scope": "Synthetic uploaded Terraform plans; local API only; no cloud account access"}

    def verify(condition: bool, label: str) -> None:
        if not condition:
            raise RuntimeError(label)
        checks.append({"name": label, "passed": True})

    try:
        with httpx.Client(base_url=args.base_url, timeout=30,
                          headers={"X-ReachScope-Client": "workbench"}) as client:
            def request(method: str, path: str, *, expected: int = 200, **kwargs: Any) -> httpx.Response:
                response = client.request(method, path, **kwargs)
                report["requests"].append({"method": method, "path": path, "status": response.status_code,
                                           "request_id": response.headers.get("X-Request-ID")})
                if response.status_code != expected:
                    raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:500]}")
                return response

            def read(path: str, **kwargs: Any) -> dict[str, Any]:
                value: dict[str, Any] = request("GET", path, **kwargs).json()
                return value

            def post(path: str, payload: dict[str, Any], *, expected: int = 200, key: str | None = None) -> dict[str, Any]:
                headers = {"Idempotency-Key": f"redblue-{run_id}-{key}"} if key else {}
                value: dict[str, Any] = request("POST", path, expected=expected, json=payload, headers=headers).json()
                return value

            def inspect(asset: dict[str, Any], label: str) -> dict[str, Any]:
                readiness = post(f"/api/assets/{asset['id']}/preflight", {"checks": ["network"]})
                verify(readiness["ready"], f"{label}: saved asset preflight ready")
                job = post(f"/api/assets/{asset['id']}/inspections", {"checks": ["network"], "name": f"Red/blue API review: {label}"},
                           expected=201, key=f"inspect-{label}")
                until = time.monotonic() + 40
                while job["status"] in {"queued", "running"} and time.monotonic() < until:
                    time.sleep(.1)
                    job = read(f"/api/jobs/{job['id']}")
                verify(job["status"] == "completed" and job["asset_id"] == asset["id"], f"{label}: immutable asset-bound inspection completed")
                execution = {row["id"]: row["status"] for row in job["result"]["details"]["execution"]}
                verify(execution == {"network": "completed", "iam": "skipped", "storage": "skipped"},
                       f"{label}: only selected network checks executed")
                report["jobs"][label] = job["id"]
                return job

            def upload_plan(label: str, document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                filename = f"redblue-{label}.synthetic.json"
                content = json.dumps(document, ensure_ascii=False, indent=2).encode()
                (args.out / filename).write_bytes(content)
                uploaded = request("POST", "/api/uploads", expected=201,
                                   files={"file": (filename, content, "application/json")}).json()
                asset = post("/api/assets", {"kind": "cloud", "name": f"Red/blue synthetic {label} {run_id[:8]}",
                                             "source": {"profile_id": "cloud-config", "mode": "import",
                                                        "upload_id": uploaded["id"], "filename": uploaded["filename"]}},
                             expected=201, key=f"asset-{label}")
                report["assets"][label] = asset["id"]
                return asset, inspect(asset, label)

            health = read("/api/health")
            report["health"] = health
            original_asset, original_job = upload_plan("baseline", synthetic_plan(cidr="0.0.0.0/0"))
            original_result = copy.deepcopy(original_job["result"])
            report["source_result_sha256"] = hashlib.sha256(json.dumps(original_result, sort_keys=True).encode()).hexdigest()
            scope_payload = {"name": f"Synthetic review <script>unsafe()</script> {run_id[:8]}",
                             "objective": "Preserve evidence, assign remediation and compare an explicitly linked local plan revision",
                             "authorization_note": "Synthetic local configuration owned by this verification run; no deployed cloud testing",
                             "asset_ids": [original_asset["id"]]}
            engagement = post("/api/engagements", scope_payload, expected=201, key="engagement")
            engagement_id = engagement["id"]
            report["engagement_id"] = engagement_id
            verify(post("/api/engagements", scope_payload, expected=201, key="engagement")["id"] == engagement_id,
                   "repeated engagement request is idempotent")
            options = read(f"/api/engagements/{engagement_id}/candidates", params={"job_id": original_job["id"]})
            candidate = next(row for row in options["items"] if row["category"] == "network.public_sensitive_ports")
            case_payload = {"job_id": original_job["id"], "source_kind": candidate["source_kind"], "source_ref": candidate["source_ref"]}
            case = post(f"/api/engagements/{engagement_id}/cases", case_payload, expected=201, key="case")
            case_id = case["id"]
            report["case_id"] = case_id
            original_evidence = copy.deepcopy(case["evidence"])
            verify(case["confidence"] == "static_config" and case["source"]["status"] == "review" and bool(original_evidence),
                   "case preserves static configuration certainty and actual original evidence")
            verify(post(f"/api/engagements/{engagement_id}/cases", case_payload, expected=201, key="case")["id"] == case_id,
                   "repeated case creation is idempotent")
            original_version = case["version"]
            case = request("PATCH", f"/api/cases/{case_id}", json={"expected_version": original_version, "status": "in_progress",
                           "owner": "Synthetic remediation reviewer", "note": "Review the SSH ingress CIDR in the local plan"}).json()
            stale = request("PATCH", f"/api/cases/{case_id}", expected=409,
                            json={"expected_version": original_version, "owner": "Stale edit"}).json()
            verify(stale["error"]["code"] == "CASE_CONFLICT", "stale version is rejected with 409 and CASE_CONFLICT")
            denied = request("PATCH", f"/api/cases/{case_id}", expected=409,
                             json={"expected_version": case["version"], "status": "resolved", "note": "No retest supplied"}).json()
            verify(denied["error"]["code"] == "RETEST_REQUIRED", "resolution without completed comparable retest is rejected")

            revised_asset, revised_job = upload_plan("revised", synthetic_plan(cidr="10.0.0.0/24"))
            before_link = read(f"/api/cases/{case_id}/retest", params={"job_id": revised_job["id"]})
            verify(before_link["outcome"] == "not_comparable" and not before_link["input_revision"],
                   "new immutable file asset is not comparable before explicit association")
            outside = request("POST", f"/api/engagements/{engagement_id}/cases", expected=400,
                              json={**case_payload, "job_id": revised_job["id"]}).json()
            verify(outside["error"]["code"] == "OUT_OF_SCOPE", "out-of-scope source job cannot create an engagement case")
            case = post(f"/api/cases/{case_id}/retest-inputs", {"expected_version": case["version"], "asset_id": revised_asset["id"],
                        "note": "Explicit revised local plan for the same aws_security_group.review resource; SSH restricted to private CIDR"})
            cleared = read(f"/api/cases/{case_id}/retest", params={"job_id": revised_job["id"]})
            verify(cleared["outcome"] == "not_observed_in_scope" and cleared["input_revision"]
                   and cleared["source_job_id"] == original_job["id"] and cleared["retest_job_id"] == revised_job["id"],
                   "linked revision compares the same resource and rule without changing actual job identities")
            report["assessments"] = {"before_link": before_link, "revised": cleared}

            missing_asset, missing_job = upload_plan("resource-absent", synthetic_plan(cidr="0.0.0.0/0", address="aws_security_group.different"))
            case = post(f"/api/cases/{case_id}/retest-inputs", {"expected_version": case["version"], "asset_id": missing_asset["id"],
                        "note": "Synthetic revision deliberately omits the original resource to verify conservative comparison"})
            missing = read(f"/api/cases/{case_id}/retest", params={"job_id": missing_job["id"]})
            verify(missing["outcome"] == "not_comparable" and missing["input_revision"],
                   "missing original resource remains not comparable after explicit file association")
            report["assessments"]["resource_absent"] = missing
            denied = request("PATCH", f"/api/cases/{case_id}", expected=409,
                             json={"expected_version": case["version"], "status": "resolved", "note": "Resource absent is not proof of remediation",
                                   "retest_job_id": missing_job["id"]}).json()
            verify(denied["error"]["code"] == "RETEST_NOT_CLEARED", "missing resource cannot authorize resolution")
            scope = read(f"/api/engagements/{engagement_id}")
            verify(scope["asset_ids"] == [original_asset["id"]] and case["asset_id"] == original_asset["id"],
                   "revision associations preserve the original engagement scope and case asset")
            choices = read(f"/api/cases/{case_id}/retest-jobs", params={"limit": 1, "offset": 0})
            next_choices = read(f"/api/cases/{case_id}/retest-jobs", params={"limit": 1, "offset": 1})
            verify(choices["total"] >= 2 and len(choices["items"]) == len(next_choices["items"]) == 1
                   and choices["items"][0]["id"] != next_choices["items"][0]["id"], "eligible retest jobs paginate without duplicate rows")

            case = post(f"/api/cases/{case_id}/retests", {"expected_version": case["version"], "job_id": revised_job["id"],
                        "note": "Matching network rule was executed; the revised plan no longer includes public SSH CIDR"})
            verify(case["status"] == "in_progress", "recording a successful comparison does not automatically close the case")
            case = request("PATCH", f"/api/cases/{case_id}", json={"expected_version": case["version"], "status": "resolved",
                           "note": "Human review accepts the matching local plan check; deployment and effective access are outside this static scope",
                           "retest_job_id": revised_job["id"]}).json()
            verify(case["status"] == "resolved" and case["confidence"] == "static_config" and case["evidence"] == original_evidence,
                   "human CAS resolution preserves original evidence and source certainty")
            verify(read(f"/api/jobs/{original_job['id']}")["result"] == original_result,
                   "original completed inspection result remains unchanged")
            page = read(f"/api/cases/{case_id}/events", params={"limit": 1})
            following = read(f"/api/cases/{case_id}/events", params={"limit": 1, "after": page["next_cursor"]})
            verify(len(page["items"]) == len(following["items"]) == 1 and page["items"][0]["id"] < following["items"][0]["id"],
                   "audit event cursor reads successive retained events")
            listing = read(f"/api/engagements/{engagement_id}/cases", params={"status": "resolved", "limit": 1})
            verify(listing["total"] == 1 and listing["items"][0]["id"] == case_id,
                   "case status filtering returns the resolved source case")

            export_json = request("GET", f"/api/engagements/{engagement_id}/export", params={"format": "json"})
            export_html = request("GET", f"/api/engagements/{engagement_id}/export", params={"format": "html"})
            (args.out / "redblue-workflow.json").write_bytes(export_json.content)
            (args.out / "redblue-workflow.html").write_bytes(export_html.content)
            exported = export_json.json()
            verify(exported["export_scope"]["exported_cases"] == 1 and exported["cases"][0]["status"] == "resolved"
                   and exported["cases"][0]["evidence"] == original_evidence, "JSON export retains resolution, original evidence and declared scope")
            verify("sandbox" in export_html.headers.get("Content-Security-Policy", "")
                   and "<script>unsafe()</script>" not in export_html.text and "&lt;script&gt;" in export_html.text,
                   "HTML export escapes source labels and includes restrictive sandbox CSP")
            report["final_case"] = {key: case[key] for key in ("id", "status", "version", "confidence", "asset_id", "job_id")}
            report["passed"] = len(checks)
            report["ok"] = True
            return 0
    except (RuntimeError, httpx.HTTPError, KeyError, StopIteration, OSError, ValueError, TypeError) as exc:
        report.update(ok=False, passed=len(checks), error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (args.out / "redblue-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report.get(key) for key in ("ok", "passed", "engagement_id", "case_id", "error")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
