"""Exercise persistent assets and truly selective modules over a running local API."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/asset-flow-validation"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            visited.append(self.path)
            body = b'<html><title>Saved asset fixture</title><form method="get"><input type="password"></form><script src="/never-fetch.js"></script></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "session=ASSET_TEST_SECRET; Secure; HttpOnly; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks: list[dict[str, Any]] = []
    recorded: dict[str, Any] = {"checks": checks, "assets": {}, "jobs": {}}

    def done(label: str) -> None:
        checks.append({"name": label, "passed": True})

    try:
        with httpx.Client(base_url=args.base_url, timeout=30,
                          headers={"X-ReachScope-Client": "workbench"}) as client:
            def read(path: str, payload: object | None = None) -> dict[str, Any]:
                response = client.get(path) if payload is None else client.post(path, json=payload)
                response.raise_for_status()
                value: dict[str, Any] = response.json()
                return value

            def create(kind: str, name: str, source: dict[str, Any]) -> dict[str, Any]:
                return read("/api/assets", {"kind": kind, "name": name, "source": source})

            def run(asset: dict[str, Any], module: str, selected: list[str]) -> dict[str, Any]:
                config = {key: value for key, value in asset["source"].items() if key != "profile_id"}
                result = read("/api/jobs", {"module": module, "name": "资产流程验收 · " + asset["name"],
                                            "asset_id": asset["id"], "config": {**config, "checks": selected}})
                until = time.monotonic() + 40
                while result["status"] in {"queued", "running"} and time.monotonic() < until:
                    time.sleep(.1)
                    result = read("/api/jobs/" + result["id"])
                assert result["status"] == "completed", result
                assert result["asset_id"] == asset["id"] and result["asset_snapshot"]["source"] == asset["source"]
                return result

            catalogue = read("/api/catalog")
            assert len(catalogue["profiles"]) == 8 and {kind["id"] for kind in catalogue["asset_kinds"]} == {"android", "website", "cloud"}
            done("three asset types and eight compatible input profiles")
            cloud = create("cloud", "离线云配置样例", {"profile_id": "cloud-demo", "mode": "demo"})
            recorded["assets"]["cloud"] = cloud["id"]
            network = run(cloud, "cloud", ["network"])
            execution = {row["id"]: row["status"] for row in network["result"]["details"]["execution"]}
            assert execution == {"network": "completed", "iam": "skipped", "storage": "skipped"}
            assert all(row["id"].startswith("network.") for row in network["result"]["details"]["checks"])
            recorded["jobs"]["cloud_network"] = network["id"]
            done("cloud network-only execution keeps IAM and storage skipped")
            full = run(cloud, "cloud", ["network", "iam", "storage"])
            assert full["result"]["summary"]["checks"] > network["result"]["summary"]["checks"]
            assert read(f"/api/assets/{cloud['id']}/jobs")["total"] == 2
            recorded["jobs"]["cloud_all"] = full["id"]
            done("saved cloud asset reused with different checks and two immutable history records")

            url = f"http://127.0.0.1:{server.server_port}/service"
            external = create("cloud", "云服务地址本机样例", {"profile_id": "cloud-external", "mode": "probe",
                                                           "targets": [url], "allow_private": True})
            observed = run(external, "web", ["http"])
            record = observed["result"]["details"]["assets"][0]
            assert record["status_code"] == 200
            assert not record.get("checks") and not record.get("cookies") and not record.get("page", {}).get("analyzed")
            assert not observed["result"]["details"]["paths"]
            assert "ASSET_TEST_SECRET" not in json.dumps(observed)
            recorded["assets"]["external"] = external["id"]
            recorded["jobs"]["external_http"] = observed["id"]
            done("cloud address uses bounded Web HTTP-only collection without account-configuration claims")

            website = create("website", "网站本机样例", {"profile_id": "website-probe", "mode": "probe",
                                                        "targets": [url], "allow_private": True})
            headers = run(website, "web", ["headers"])
            assert headers["config"]["checks"] == ["http", "headers"]
            record = headers["result"]["details"]["assets"][0]
            assert record["checks"] and not record.get("page", {}).get("analyzed")
            assert all(row["id"] not in {"password_forms", "mixed_content"} for row in record["checks"])
            recorded["assets"]["website"] = website["id"]
            recorded["jobs"]["website_headers"] = headers["id"]
            done("selected website headers imply HTTP dependency while page and fingerprint stages remain skipped")

            android = create("android", "应用清单本机样例", {"profile_id": "android-demo", "mode": "demo", "sample": "cross_component"})
            manifest = run(android, "android", ["manifest"])
            assert "artifact_id" not in manifest["result"]["details"]
            response = client.get(f"/api/jobs/{manifest['id']}/methods")
            assert response.status_code == 400 and response.json()["error"]["code"] == "QUERY_UNAVAILABLE"
            recorded["assets"]["android"] = android["id"]
            recorded["jobs"]["android_manifest"] = manifest["id"]
            done("manifest-only Android task creates no source artifact and returns an explicit query scope error")

            policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*",
                      "Condition": {"StringEquals": {"aws:PrincipalTag/environment": "PRIVATE_CONDITION_VALUE"}}}]}
            response = client.post("/api/uploads", files={"file": ("asset-policy.json", json.dumps(policy).encode())})
            response.raise_for_status()
            uploaded = response.json()
            policy_asset = create("cloud", "上传 IAM 策略样例", {"profile_id": "cloud-config", "mode": "import",
                                                               "upload_id": uploaded["id"], "filename": uploaded["filename"]})
            policy_job = run(policy_asset, "cloud", ["iam"])
            assert policy_job["result"]["summary"]["review_checks"] >= 1
            assert "PRIVATE_CONDITION_VALUE" not in json.dumps(policy_job["result"])
            recorded["assets"]["policy"] = policy_asset["id"]
            recorded["jobs"]["policy_iam"] = policy_job["id"]
            done("uploaded IAM policy keeps field evidence and omits sensitive condition values")

            mismatch_config = {**website["source"], "targets": [url + "/different"], "checks": ["http"]}
            mismatch_config.pop("profile_id")
            mismatch = client.post("/api/jobs", json={"module": "web", "asset_id": website["id"], "config": mismatch_config})
            assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "ASSET_MISMATCH"
            assert visited == ["/service", "/service"], visited
            done("mismatched asset input rejected and only the two selected URLs were contacted")
            recorded.update(passed=len(checks), total=len(checks))
            return 0
    except Exception as exc:
        recorded.update(error=f"{type(exc).__name__}: {exc}", passed=len(checks))
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        (args.out / "asset-flow-validation.json").write_text(json.dumps(recorded, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(recorded, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
