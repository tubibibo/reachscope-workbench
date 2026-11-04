"""Exercise an installed wheel's frontend, modules and saved-evidence workflow."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    args.data = args.data.resolve()
    if args.data.exists() and (not args.data.is_dir() or any(args.data.iterdir())):
        parser.error("Installed acceptance requires a new or empty temporary data directory; existing records must not be used.")
    environment = {key: value for key, value in os.environ.items()
                   if key != "PYTHONPATH" and not key.startswith("REACHSCOPE_AI_")}
    diagnostic = subprocess.run(
        [sys.executable, "-I", "-m", "reachscope_workbench", "doctor", "--json", "--data", str(args.data)],
        capture_output=True, text=True, encoding="utf-8", env={**environment, "PYTHONIOENCODING": "utf-8"},
        check=True, timeout=15,
    )
    readiness = json.loads(diagnostic.stdout)
    assert readiness["ready"] and not readiness["network_contacted"] and not readiness["workspace_modified"]
    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    # All HTTP in this acceptance script is loopback. Do not use inherited
    # proxies or require any operator model credentials/settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    args.data.mkdir(parents=True, exist_ok=True)
    with (args.data / "smoke-server.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-I", "-m", "reachscope_workbench", "serve", "--port", str(port), "--data", str(args.data)],
            env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )

        def request(path: str, body: object | None = None, *, method: str | None = None,
                    operation_key: str | None = None) -> Any:
            encoded = json.dumps(body).encode() if body is not None else None
            headers = {
                "Content-Type": "application/json", "X-ReachScope-Client": "workbench",
            }
            if operation_key:
                headers["Idempotency-Key"] = operation_key
            req = urllib.request.Request(base + path, data=encoded, headers=headers, method=method)
            with opener.open(req, timeout=10) as response:
                return json.load(response)

        def completed(job: dict[str, Any]) -> dict[str, Any]:
            until = time.monotonic() + 15
            while job["status"] in {"queued", "running"} and time.monotonic() < until:
                time.sleep(.1)
                job = request("/api/jobs/" + job["id"])
            assert job["status"] == "completed", job
            return job

        def cloud_file(name: str, cidr: str) -> dict[str, Any]:
            """Import a controlled, offline AWS-shaped fixture through real uploads."""
            document = {"SecurityGroups": [{"GroupId": "sg-installed-smoke", "GroupName": "installed-smoke",
                         "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                                            "IpRanges": [{"CidrIp": cidr}]}]}]}
            boundary = "reachscope-installed-smoke-upload"
            payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                       f"filename=\"{name}.json\"\r\nContent-Type: application/json\r\n\r\n").encode()
            payload += json.dumps(document).encode() + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(base + "/api/uploads", data=payload, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}", "X-ReachScope-Client": "workbench",
            })
            with opener.open(req, timeout=10) as response:
                uploaded = json.load(response)
            asset: dict[str, Any] = request("/api/assets", {"kind": "cloud", "name": name, "source": {
                "profile_id": "cloud-config", "mode": "import", "upload_id": uploaded["id"], "filename": uploaded["filename"],
            }})
            return asset

        def host_file(filename: str, raw: bytes, profile: str, host_id: str) -> dict[str, Any]:
            """Upload a controlled host file through the installed public API."""
            mode = {"host-baseline": "baseline", "host-access-log": "access_log", "host-auth-log": "auth_log"}[profile]
            boundary = "reachscope-installed-host-input"
            payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                       f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
            payload += raw + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(base + "/api/uploads", data=payload, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}", "X-ReachScope-Client": "workbench",
            })
            with opener.open(req, timeout=10) as response:
                uploaded = json.load(response)
            asset: dict[str, Any] = request("/api/assets", {"kind": "host", "name": "Installed controlled host / " + filename,
                "source": {"profile_id": profile, "mode": mode, "host_id": host_id,
                           "upload_id": uploaded["id"], "filename": uploaded["filename"]}})
            return asset

        def host_collection_workflow() -> dict[str, Any]:
            """Download/preview the real zipapp; uploaded failure never means pass."""
            jobs_before = request("/api/jobs")["total"]
            downloaded = []
            for endpoint in ("/api/host/collector", "/api/host/collector/source"):
                with opener.open(base + endpoint, timeout=10) as response:
                    body = response.read(1024 * 1024 + 1)
                    declared_digest = response.headers["X-Content-SHA256"]
                assert body and len(body) <= 1024 * 1024
                assert hashlib.sha256(body).hexdigest() == declared_digest
                downloaded.append(body)
            assert downloaded[0] == downloaded[1]
            with zipfile.ZipFile(io.BytesIO(downloaded[0])) as archive:
                assert set(archive.namelist()) == {"__main__.py", *(
                    "reachscope_host_collector/" + filename for filename in (
                        "__init__.py", "collector.py", "runner.py", "projection.py", "builder.py", "LICENSE"))}
                assert b"reachscope_host_collector.collector import main" in archive.read("__main__.py")
                license_text = archive.read("reachscope_host_collector/LICENSE")
                assert b"MIT License" in license_text and b"ReachScope contributors" in license_text
            bundle = args.data / "installed-collector.pyz"
            with bundle.open("xb") as stream:
                stream.write(downloaded[0])
            bundle.chmod(0o600)
            unused_output = args.data / "collector-preview-must-not-exist.json"
            preview_run = subprocess.run([sys.executable, "-I", str(bundle), "--host-id", "installed-collector-01",
                "--ssh-context", "global", "--output", str(unused_output)],
                capture_output=True, text=True, encoding="utf-8", env=environment, check=True, timeout=15,
                cwd=args.data)
            plan = json.loads(preview_run.stdout)
            assert not unused_output.exists()
            assert plan["output"] == str(unused_output.absolute())
            assert plan["commands"] == {"ssh": ["/usr/sbin/sshd", "-T"], "nginx": ["/usr/sbin/nginx", "-T"]}
            assert plan["network_upload"] is False and plan["automatic_sudo"] is False
            assert plan["reload_or_configuration_change"] is False
            without_digest = {key: value for key, value in plan.items() if key != "plan_sha256"}
            canonical = json.dumps(without_digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            assert hashlib.sha256(canonical).hexdigest() == plan["plan_sha256"]
            assert request("/api/jobs")["total"] == jobs_before

            host_id = "installed-v2-failed-01"
            document = {"schema_version": "reachscope-host/2", "host_id": host_id,
                "collected_at": "2026-11-02T00:02:00Z", "ssh": {"connection_context": "global",
                    "effective_config": "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"},
                "nginx": {"config_dump": None}, "collector": {"version": "0.14.0", "projection": "reachscope-minimal/1",
                    "plan_sha256": plan["plan_sha256"], "components": {
                        "ssh": {"state": "failed", "complete": False, "exit_code": 1, "reason_code": "nonzero_exit"},
                        "nginx": {"state": "unavailable", "complete": False, "reason_code": "missing_executable"}}}}
            asset = host_file("host-v2-controlled-failed.json", json.dumps(document).encode(), "host-baseline", host_id)
            asset_path = f"/api/assets/{asset['id']}"
            preview = request(asset_path + "/preflight", {"checks": ["ssh"]})
            assert preview["ready"] and preview["input_preview"]["analysis_executed"] is False
            capture = preview["input_preview"]["collection_metadata"]
            assert capture["format_version"] == 2 and capture["projection"] == "reachscope-minimal/1"
            assert capture["components"]["ssh"]["state"] == "failed"
            assert capture["components"]["ssh"]["complete"] is False
            assert request("/api/jobs")["total"] == jobs_before
            job = completed(request(asset_path + "/inspections", {"checks": ["ssh"], "name": "Installed failed-capture boundary"}))
            details = job["result"]["details"]
            assert details["collection_metadata"] == capture and details["live_state_verified"] is False
            assert len(details["checks"]) == 4
            assert all(row["status"] == "unknown" and row["complete"] is False
                       and row["comparison_identity"]["complete"] is False for row in details["checks"])
            assert all(proof["data"]["collection"]["capture"]["state"] == "failed" for proof in job["result"]["evidence"])
            assert request(f"/api/jobs/{job['id']}/advisory/preview")["eligible"] is False
            assert request(f"/api/jobs/{job['id']}/advisories")["total"] == 0
            return {"scope": "installed collector download, isolated preview and controlled v2 failed-capture upload",
                    "collector_bundle_sha256": hashlib.sha256(downloaded[0]).hexdigest(),
                    "source_zip_matches_bundle": True, "zipapp_preview": "passed", "preview_created_job": False,
                    "preview_created_snapshot": False, "failed_capture_checks": "unknown",
                    "capture_metadata_preserved": True, "real_linux_commands_executed": False,
                    "runtime_state_verified": False, "commercial_ai_requests": 0}

        def host_defense_workflow() -> dict[str, Any]:
            """Real uploaded fixtures, never a remote host or a model request."""
            template = request("/api/host/template")
            assert template["schema_version"] == "reachscope-host/1"
            host_id = "installed-host-01"
            original_document = {**template, "host_id": host_id, "collected_at": "2026-11-02T00:00:00Z",
                                 "ssh": {**template["ssh"], "connection_context": "global",
                                         "effective_config": template["ssh"]["effective_config"].replace("permitrootlogin no", "permitrootlogin yes")}}
            jobs_before = request("/api/jobs")["total"]
            original = host_file("host-original.json", json.dumps(original_document).encode(), "host-baseline", host_id)
            asset_path = f"/api/assets/{original['id']}"
            preview = request(asset_path + "/preflight", {"checks": ["ssh"]})
            assert preview["ready"] and preview["network"] is False
            assert preview["input_preview"]["module"] == "host" and preview["input_preview"]["host_id"] == host_id
            assert preview["input_preview"]["analysis_executed"] is False and preview["input_preview"]["network_requests"] is False
            assert request("/api/jobs")["total"] == jobs_before
            assert "effective_config" not in json.dumps(preview)
            before = completed(request(asset_path + "/inspections", {"checks": ["ssh"], "name": "Installed SSH baseline"}))
            details = before["result"]["details"]
            assert details["origin"] == "operator_supplied_export" and details["live_state_verified"] is False
            assert len(details["checks"]) == 4 and all(row["id"].startswith("host.ssh.") for row in details["checks"])
            execution = {row["id"]: row["status"] for row in details["execution"]}
            assert execution == {"ssh": "completed", "nginx": "skipped", "web_logs": "skipped", "auth_logs": "skipped"}
            root_check = next(row for row in details["checks"] if row["id"] == "host.ssh.root_login")
            assert root_check["status"] == "review" and root_check["complete"] is True
            assert root_check["guidance"]["verification"] and root_check["guidance"]["rollback"]

            engagement = request("/api/engagements", {"name": "Installed host static remediation",
                "asset_ids": [original["id"]], "authorization_note": "Controlled synthetic uploaded export; no host contact or actual deployment claim."})
            scope = f"/api/engagements/{engagement['id']}"
            choices = request(scope + "/candidates?job_id=" + before["id"])["items"]
            candidate = next(row for row in choices if row["category"] == "host.ssh.root_login")
            case = request(scope + "/cases", {"job_id": before["id"], "source_kind": candidate["source_kind"],
                                               "source_ref": candidate["source_ref"]})
            case_path = f"/api/cases/{case['id']}"
            revised_document = {**original_document, "collected_at": "2026-11-02T00:01:00Z",
                                "ssh": {**original_document["ssh"], "effective_config": template["ssh"]["effective_config"]}}
            revised = host_file("host-revised.json", json.dumps(revised_document).encode(), "host-baseline", host_id)
            after = completed(request(f"/api/assets/{revised['id']}/inspections", {"checks": ["ssh"], "name": "Installed SSH revised export"}))
            assert request(case_path + "/retest?job_id=" + after["id"])["outcome"] == "not_comparable"
            linked = request(case_path + "/retest-inputs", {"expected_version": case["version"], "asset_id": revised["id"],
                "note": "Same declared host and global SSH context; newer synthetic export, manual association only."})
            assessment = request(case_path + "/retest?job_id=" + after["id"])
            assert assessment["outcome"] == "not_observed_in_scope" and assessment["input_revision"] and assessment["evidence"]
            closed = request(case_path, {"expected_version": linked["version"], "status": "resolved", "retest_job_id": after["id"],
                "note": "Compared supplied same-context static declarations; actual service loading and business behavior require separate verification."}, method="PATCH")
            assert closed["status"] == "resolved" and closed["asset_id"] == original["id"]
            assert request("/api/jobs/" + before["id"]) == before
            assert request(scope)["asset_ids"] == [original["id"]]

            access_rows = [f'192.0.2.99 - PRIVATE_ACCOUNT [02/Nov/2026:10:00:{index:02d} +0000] '
                           '"GET /PRIVATE_REQUEST?token=PRIVATE_TOKEN HTTP/1.1" 401 0 "PRIVATE_REFERER" "PRIVATE_AGENT"'
                           for index in range(10)]
            access_asset = host_file("host-access.log", ("\n".join(access_rows) + "\n").encode(), "host-access-log", host_id)
            access_preview = request(f"/api/assets/{access_asset['id']}/preflight", {"checks": ["web_logs"]})
            assert access_preview["ready"] and access_preview["input_preview"]["coverage"]["parsed_events"] == 10
            access_job = completed(request(f"/api/assets/{access_asset['id']}/inspections", {"checks": ["web_logs"]}))
            access_result = access_job["result"]
            access_checks = {row["id"]: row for row in access_result["details"]["checks"]}
            assert access_checks["host.logs.http_auth_burst"]["status"] == "review"
            assert all(row["status"] != "pass" and row["retest_can_prove_fix"] is False for row in access_checks.values())
            rendered = json.dumps([access_result, access_preview])
            assert all(secret not in rendered for secret in ["192.0.2.99", "PRIVATE_ACCOUNT", "PRIVATE_REQUEST", "PRIVATE_TOKEN", "PRIVATE_REFERER", "PRIVATE_AGENT"])
            assert all(row["actor_alias"].startswith("client-") for row in access_result["details"]["log_events"])

            auth_rows = [f'2026-11-02T10:00:{index:02d}Z node sshd[101]: Failed password for invalid user PRIVATE_USER from 198.51.100.99 port 4242 ssh2'
                         for index in range(5)]
            auth_rows.append('Nov  2 10:01:00 node sshd[101]: Failed password for PRIVATE_USER from 198.51.100.99 port 4242 ssh2')
            auth_asset = host_file("host-auth.log", ("\n".join(auth_rows) + "\n").encode(), "host-auth-log", host_id)
            auth_job = completed(request(f"/api/assets/{auth_asset['id']}/inspections", {"checks": ["auth_logs"]}))
            auth_result = auth_job["result"]
            auth_check = auth_result["details"]["checks"][0]
            assert auth_check["id"] == "host.logs.ssh_failure_burst" and auth_check["status"] == "review" and auth_check["complete"] is False
            unknown = [row for row in auth_result["details"]["log_events"] if row["timestamp_status"] == "unknown"]
            assert len(unknown) == 1 and unknown[0]["timestamp"] is None and unknown[0]["rule_eligible"] is False
            assert "PRIVATE_USER" not in json.dumps(auth_result) and "198.51.100.99" not in json.dumps(auth_result)
            assert all(request(f"/api/jobs/{job['id']}/advisories")["total"] == 0 for job in (before, after, access_job, auth_job))
            return {"scope": "uploaded synthetic configuration and log fixtures through installed loopback API",
                    "preview_created_job": False, "selected_ssh_only": True, "host_id": host_id,
                    "retest_outcome": assessment["outcome"], "case_status": closed["status"], "baseline_immutable": True,
                    "access_events": len(access_result["details"]["log_events"]), "auth_events": len(auth_result["details"]["log_events"]),
                    "legacy_year_zone_unknown": len(unknown), "raw_log_identifiers_redacted": True,
                    "log_absence_proves_fix": False, "remote_host_connections": 0, "commands_executed_on_target": 0,
                    "model_requests": 0, "runtime_state_verified": False}

        def local_teaching_workflow() -> dict[str, Any]:
            assert request("/api/lab")["status"] == "stopped"
            assert not request("/api/ai/config")["has_key"]
            started = request("/api/lab/start", method="POST")
            assert started["status"] == "running" and not started["source"]["production"]
            assert started["url"].startswith("http://127.0.0.1:")
            try:
                asset = request("/api/assets", started["asset_template"], operation_key="installed-teaching-asset")
                assert asset["provenance"]["kind"] == "local_training"
                assert asset["provenance"]["session_id"] == started["session_id"]
                asset_path = f"/api/assets/{asset['id']}"
                baseline = completed(request(asset_path + "/inspections", {
                    "name": "Installed teaching baseline", "checks": ["http", "headers", "page"],
                }, operation_key="installed-teaching-baseline"))
                captured = baseline["result"]["details"]["assets"][0]
                before_checks = {row["id"]: row["status"] for row in captured["checks"]}
                for check in ("csp", "nosniff", "frame_protection", "referrer_policy"):
                    assert before_checks[check] == "review"
                assert captured["reachable"] and captured["status_code"] == 200
                assert captured["headers"]["x-reachscope-lab-session"] == started["session_id"]
                assert captured["headers"]["x-reachscope-lab-profile"] == "baseline"
                assert baseline["asset_snapshot"]["provenance"] == asset["provenance"]
                baseline_path = f"/api/jobs/{baseline['id']}"

                jobs_before_guide = request("/api/jobs")["total"]
                controls = request(baseline_path + "/controls")
                assert controls["origin"] == "local_training" and controls["ai_required"] is False
                assert controls["source_kind"] == "deterministic_saved_evidence"
                indexed = {row["control_id"]: row for row in controls["items"]}
                assert indexed["web.mime"]["states"] == ["review"] and indexed["web.mime"]["evidence_ids"]
                guide = request(baseline_path + "/controls/web.mime/guide?environment=nginx")
                assert guide["origin"] == "local_training" and guide["environment"] == "nginx"
                assert guide["observed_stack"] is None and guide["requires_environment_confirmation"]
                assert guide["states"] == ["review"] and guide["evidence_ids"] == indexed["web.mime"]["evidence_ids"]
                assert len(guide["templates"]) == 1 and guide["templates"][0]["language"] == "nginx"
                assert "nosniff" in guide["templates"][0]["content"]
                assert request("/api/jobs")["total"] == jobs_before_guide
                assert request(baseline_path) == baseline and request("/api/lab") == started
                assert request(baseline_path + "/advisories")["total"] == 0

                engagement = request("/api/engagements", {
                    "name": "Installed local teaching / response headers", "asset_ids": [asset["id"]],
                    "authorization_note": "Owned loopback teaching session with fixed harmless content; not a production target.",
                }, operation_key="installed-teaching-engagement")
                engagement_path = f"/api/engagements/{engagement['id']}"
                choices = request(engagement_path + "/candidates?job_id=" + baseline["id"])["items"]
                candidate = next(row for row in choices if row["category"] == "nosniff")
                case = request(engagement_path + "/cases", {
                    "job_id": baseline["id"], "source_kind": candidate["source_kind"], "source_ref": candidate["source_ref"],
                }, operation_key="installed-teaching-case")
                case_path = f"/api/cases/{case['id']}"
                assert case["evidence"] and case["status"] == "open"

                hardened_state = request("/api/lab/configure", {"generation": started["generation"], "profile": "hardened"})
                assert hardened_state["url"] == started["url"] and hardened_state["session_id"] == started["session_id"]
                assert request("/api/jobs")["total"] == jobs_before_guide
                hardened = completed(request(asset_path + "/inspections", {
                    "name": "Installed teaching hardened", "checks": ["http", "headers", "page"],
                }, operation_key="installed-teaching-hardened"))
                after = hardened["result"]["details"]["assets"][0]
                after_checks = {row["id"]: row["status"] for row in after["checks"]}
                for check in ("csp", "nosniff", "frame_protection", "referrer_policy"):
                    assert after_checks[check] == "pass"
                assert after["url"] == captured["url"] and after["headers"]["x-reachscope-lab-profile"] == "hardened"
                assert after["body_sha256"] != captured["body_sha256"]
                assert "strict-transport-security" not in captured["headers"] and "strict-transport-security" not in after["headers"]
                comparison = request(f"/api/jobs/{hardened['id']}/compare?baseline={baseline['id']}")
                assert comparison["summary"]["changed"] == 1 and comparison["summary"]["not_comparable"] == 0
                assert comparison["assets"][0]["before_evidence_ids"] and comparison["assets"][0]["after_evidence_ids"]
                assessment = request(case_path + "/retest?job_id=" + hardened["id"])
                assert assessment["outcome"] == "not_observed_in_scope" and assessment["evidence"]
                closed = request(case_path, {"expected_version": case["version"], "status": "resolved",
                    "retest_job_id": hardened["id"], "note": "Same owned loopback URL now returns nosniff; reviewed teaching evidence only."}, method="PATCH")
                assert closed["status"] == "resolved" and closed["job_id"] == baseline["id"]
                assert request(baseline_path) == baseline
                assert request(asset_path)["provenance"] == asset["provenance"]
                assert request(f"/api/jobs/{hardened['id']}/advisories")["total"] == 0
                result = {
                    "origin": controls["origin"], "production": started["source"]["production"],
                    "same_url": after["url"] == captured["url"],
                    "baseline_checks": {check: before_checks[check] for check in ("csp", "nosniff", "frame_protection", "referrer_policy")},
                    "hardened_checks": {check: after_checks[check] for check in ("csp", "nosniff", "frame_protection", "referrer_policy")},
                    "deterministic_guide": {"control_id": guide["control_id"], "environment": guide["environment"],
                                            "observed_stack": guide["observed_stack"], "templates": len(guide["templates"]),
                                            "ai_required": controls["ai_required"]},
                    "comparison": comparison["summary"], "retest_outcome": assessment["outcome"],
                    "case_status": closed["status"], "ai_reports": request(baseline_path + "/advisories")["total"],
                    "network": "loopback API and managed local teaching HTTP only",
                }
            finally:
                stopped = request("/api/lab/stop", method="POST")
                assert stopped["status"] == "stopped"
            result["lab_status"] = stopped["status"]
            return result

        try:
            until = time.monotonic() + 20
            while True:
                try:
                    request("/api/health")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > until:
                        raise RuntimeError("Installed server did not start") from None
                    time.sleep(.1)
            with opener.open(base + "/", timeout=10) as response:
                html = response.read().decode()
            assert '<div id="root">' in html and "/assets/" in html
            outputs = []
            for module, config in [("web", {"mode": "demo"}),
                                   ("android", {"mode": "demo", "sample": "cross_component"}),
                                   ("cloud", {"mode": "demo"}),
                                   ("host", {"mode": "demo"})]:
                job = request("/api/jobs", {"module": module, "name": "Installed smoke", "config": config})
                until = time.monotonic() + 45
                while job["status"] in {"queued", "running"} and time.monotonic() < until:
                    time.sleep(.1)
                    job = request("/api/jobs/" + job["id"])
                assert job["status"] == "completed", job
                assert job["result"]["evidence"]
                outputs.append({"module": module, "summary": job["result"]["summary"]})
                if module == "android":
                    methods = request(f"/api/jobs/{job['id']}/methods?search=CrossTarget")
                    from urllib.parse import urlencode

                    code = request(f"/api/jobs/{job['id']}/method?" + urlencode({"ref": methods["data"][0]["method_ref"]}))
                    assert "getStringExtra" in code["data"]["code"]
            saved = request("/api/assets", {"kind": "cloud", "name": "Installed cloud asset",
                                            "source": {"profile_id": "cloud-demo", "mode": "demo"}})
            conditions = request(f"/api/assets/{saved['id']}/preflight", {"checks": ["network"]})
            assert conditions["ready"] and not conditions["network"]
            linked = request(f"/api/assets/{saved['id']}/inspections", {"name": "Linked selective inspection", "checks": ["network"]})
            until = time.monotonic() + 10
            while linked["status"] in {"queued", "running"} and time.monotonic() < until:
                time.sleep(.1)
                linked = request("/api/jobs/" + linked["id"])
            assert linked["status"] == "completed", linked
            assert request(f"/api/assets/{saved['id']}/jobs")["total"] == 1
            execution = linked["result"]["details"]["execution"]
            assert next(item for item in execution if item["id"] == "iam")["status"] == "skipped"

            # This workflow imports real supported JSON through HTTP, but contacts
            # no cloud target and makes no deployed-reachability or exploit claim.
            original = cloud_file("Installed original configuration", "0.0.0.0/0")
            source_job = completed(request(f"/api/assets/{original['id']}/inspections", {"checks": ["network"]}))
            engagement_body = {"name": "Installed red/blue smoke", "objective": "Review a saved offline configuration",
                               "authorization_note": "Controlled local synthetic fixture; no cloud account or target traffic.",
                               "asset_ids": [original["id"]]}
            engagement_key = "installed-engagement-" + original["id"]
            engagement = request("/api/engagements", engagement_body, operation_key=engagement_key)
            assert request("/api/engagements", engagement_body, operation_key=engagement_key)["id"] == engagement["id"]
            scope = f"/api/engagements/{engagement['id']}"
            choices = request(scope + "/candidates?job_id=" + source_job["id"])["items"]
            candidate = next(item for item in choices if item["category"] == "network.public_sensitive_ports")
            case_body = {"job_id": source_job["id"], "source_kind": candidate["source_kind"], "source_ref": candidate["source_ref"]}
            case_key = "installed-case-" + source_job["id"]
            case = request(scope + "/cases", case_body, operation_key=case_key)
            assert request(scope + "/cases", case_body, operation_key=case_key)["id"] == case["id"]
            case_path = f"/api/cases/{case['id']}"
            assert case["confidence"] == "static_config" and case["evidence"] and case["source"]["job_id"] == source_job["id"]
            version = case["version"]
            case = request(case_path, {"expected_version": version, "status": "in_progress", "owner": "Local fixture owner",
                                      "note": "Review the saved rule condition; no live reachability inferred."}, method="PATCH")
            try:
                request(case_path, {"expected_version": version, "owner": "Stale change"}, method="PATCH")
            except urllib.error.HTTPError as conflict:
                assert conflict.code == 409 and json.load(conflict)["error"]["code"] == "CASE_CONFLICT"
            else:
                raise AssertionError("A stale case update must not succeed")

            revised = cloud_file("Installed revised configuration", "10.0.0.0/8")
            cleared_job = completed(request(f"/api/assets/{revised['id']}/inspections", {"checks": ["network"]}))
            # Another saved asset is not comparable until explicitly associated.
            assert request(case_path + "/retest?job_id=" + cleared_job["id"])["outcome"] == "not_comparable"
            case = request(case_path + "/retest-inputs", {"expected_version": case["version"], "asset_id": revised["id"],
                           "note": "Same synthetic security-group identity and type, revised supported local JSON."})
            assert request(scope)["asset_ids"] == [original["id"]]
            assert request(case_path + "/retest-inputs")["items"][0]["id"] == revised["id"]
            assessment = request(case_path + "/retest?job_id=" + cleared_job["id"])
            assert assessment["outcome"] == "not_observed_in_scope" and assessment["input_revision"] and assessment["evidence"]
            assert cleared_job["id"] in {job["id"] for job in request(case_path + "/retest-jobs")["items"]}
            case = request(case_path + "/retests", {"expected_version": case["version"], "job_id": cleared_job["id"],
                           "note": "Saved supported condition comparison reviewed separately from closure."})
            assert case["status"] == "in_progress"
            case = request(case_path, {"expected_version": case["version"], "status": "resolved", "retest_job_id": cleared_job["id"],
                           "note": "Matching saved configuration rule no longer observed; limited static scope reviewed."}, method="PATCH")
            assert case["status"] == "resolved" and case["job_id"] == source_job["id"] and case["asset_id"] == original["id"]
            events, cursor = [], 0
            while True:
                page = request(case_path + f"/events?after={cursor}&limit=2")
                if not page["items"]:
                    break
                assert page["next_cursor"] > cursor
                events.extend(page["items"])
                cursor = page["next_cursor"]
            assert [event["event_type"] for event in events] == ["created", "updated", "retest_input", "retest", "resolved"]
            exported = request(scope + "/export?format=json")
            assert exported["export_scope"]["exported_cases"] == 1 and not exported["export_scope"]["truncated"]
            assert exported["export_scope"]["events_per_case"] == 100 and set(exported["perspectives"]) == {"red", "blue"}
            with opener.open(base + scope + "/export?format=html", timeout=10) as response:
                assert response.headers["Content-Type"].startswith("text/html") and response.read()
            host_defense = host_defense_workflow()
            host_collection = host_collection_workflow()
            teaching = local_teaching_workflow()
            print(json.dumps({"installed_api_and_frontend": "passed", "modules": outputs,
                              "redblue_saved_cloud_workflow": {"status": case["status"], "events": len(events),
                                                                "scope_preserved": True, "network": "localhost API only"},
                              "local_teaching_workflow": teaching, "host_defense_workflow": host_defense,
                              "host_collection_workflow": host_collection}, ensure_ascii=True, indent=2))
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
