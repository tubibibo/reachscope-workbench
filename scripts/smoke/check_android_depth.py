"""Real APK upload/static-review/revised-input/case acceptance on a private server.

Builds two tiny unsigned synthetic APKs with Apktool. They are never installed or
executed. No user workspace, real APK, cloud target or model provider is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]


def build_apk(directory: Path, jar: Path, *, hardened: bool) -> Path:
    source = directory / ("hardened" if hardened else "baseline")
    source.mkdir()
    flags = "false" if hardened else "true"
    (source / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="org.reachscope.staticfixture" android:versionCode="1" android:versionName="1">'
        '<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34"/>'
        f'<application android:label="Static review fixture" android:debuggable="{flags}" '
        'android:allowBackup="false" android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/security">'
        '<activity android:name=".MainActivity" android:exported="false"/></application></manifest>',
        encoding="utf-8",
    )
    resources = source / "res" / "xml"
    resources.mkdir(parents=True)
    user = '' if hardened else '<certificates src="user"/>'
    (resources / "security.xml").write_text(
        f'<network-security-config><base-config cleartextTrafficPermitted="{flags}">'
        '<trust-anchors><certificates src="system"/>' + user
        + '</trust-anchors></base-config></network-security-config>', encoding="utf-8",
    )
    smali = source / "smali" / "org" / "reachscope" / "staticfixture"
    smali.mkdir(parents=True)
    (smali / "MainActivity.smali").write_text(
        '.class public Lorg/reachscope/staticfixture/MainActivity;\n.super Landroid/app/Activity;\n'
        '.method public constructor <init>()V\n.locals 0\n'
        'invoke-direct {p0}, Landroid/app/Activity;-><init>()V\nreturn-void\n.end method\n',
        encoding="utf-8",
    )
    (source / "apktool.yml").write_text(
        "version: 2.11.1\napkFileName: static-fixture.apk\nusesFramework:\n  ids:\n  - 1\n"
        "sdkInfo:\n  minSdkVersion: '24'\n  targetSdkVersion: '34'\n"
        "versionInfo:\n  versionCode: '1'\n  versionName: '1'\n"
        "resourcesInfo:\n  packageId: '127'\n  forcedPackageId: '127'\n"
        "  renameManifestPackage: null\n  sparseResources: false\n  compactEntries: false\n  sharedLibrary: false\n",
        encoding="utf-8",
    )
    destination = directory / ("hardened.apk" if hardened else "baseline.apk")
    result = subprocess.run(
        ["java", "-jar", str(jar), "b", "-f", str(source), "-o", str(destination)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False,
    )
    if result.returncode:
        raise RuntimeError("Synthetic APK build failed: " + (result.stdout + result.stderr)[-2000:])
    with zipfile.ZipFile(destination) as archive:
        assert archive.read("AndroidManifest.xml")[:4] == bytes.fromhex("03000800"), "Expected compiled Android binary manifest"
        assert "classes.dex" in archive.namelist()
        assert "res/xml/security.xml" in archive.namelist()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/validation/android-depth")
    parser.add_argument("--apktool", type=Path, default=os.environ.get("APKTOOL_JAR"))
    args = parser.parse_args()
    if args.apktool is None or not args.apktool.is_file():
        parser.error("--apktool or APKTOOL_JAR must name a locally installed Apktool JAR")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("REACHSCOPE_AI_")}
    environment["APKTOOL_JAR"] = str(args.apktool.resolve())
    environment["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="reachscope-android-acceptance-") as directory:
        temp = Path(directory)
        baseline_file = build_apk(temp, args.apktool.resolve(), hardened=False)
        hardened_file = build_apk(temp, args.apktool.resolve(), hardened=True)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        data = temp / "workspace"
        with (output / "server.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "reachscope_workbench", "serve", "--port", str(port), "--data", str(data)],
                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(base_url=base, trust_env=False, timeout=20,
                                  headers={"X-ReachScope-Client": "workbench"}) as client:
                    deadline = time.monotonic() + 25
                    while True:
                        try:
                            response = client.get("/api/health")
                            if response.status_code == 200 and response.json().get("ready") is True:
                                break
                        except httpx.HTTPError:
                            pass
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Isolated Android acceptance server did not start")
                        time.sleep(.1)

                    def request(method: str, path: str, body: object | None = None, *, key: str | None = None) -> Any:
                        kwargs: dict[str, Any] = {"json": body} if body is not None else {}
                        if key:
                            kwargs["headers"] = {"Idempotency-Key": key}
                        reply = client.request(method, path, **kwargs)
                        assert reply.is_success, (method, path, reply.status_code, reply.text[:2000])
                        return reply.json()

                    def finished(job: dict[str, Any]) -> dict[str, Any]:
                        until = time.monotonic() + 90
                        while job["status"] in {"queued", "running"} and time.monotonic() < until:
                            time.sleep(.1)
                            job = request("GET", "/api/jobs/" + job["id"])
                        assert job["status"] == "completed", job
                        return job

                    def upload_apk(path: Path) -> dict[str, Any]:
                        with path.open("rb") as apk:
                            response = client.post("/api/uploads", files={"file": (path.name, apk, "application/vnd.android.package-archive")})
                        response.raise_for_status()
                        uploaded = response.json()
                        assert uploaded["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
                        return request("POST", "/api/assets", {"kind": "android", "name": "Synthetic " + path.stem,
                            "source": {"profile_id": "android-apk", "mode": "apk", "upload_id": uploaded["id"], "filename": uploaded["filename"]}})

                    original = upload_apk(baseline_file)
                    asset_path = "/api/assets/" + original["id"]
                    preflight = request("POST", asset_path + "/preflight", {"checks": ["manifest"]})
                    assert preflight["ready"] and preflight["network"] is False
                    baseline = finished(request("POST", asset_path + "/inspections", {
                        "name": "Synthetic APK configuration baseline", "checks": ["manifest"]}, key="android-depth-baseline"))
                    original_snapshot = json.dumps(baseline, sort_keys=True)
                    before = {row["id"]: row for row in baseline["result"]["details"]["security_review"]["checks"]}
                    for check in ("android.debuggable", "android.cleartext", "android.trust_anchors"):
                        assert before[check]["status"] == "review" and before[check]["evidence_ids"]
                    execution = {row["id"]: row["status"] for row in baseline["result"]["details"]["execution"]}
                    assert execution == {"manifest": "completed", "code_paths": "skipped"}
                    assert baseline["result"]["details"]["methods"] == []
                    assert not baseline["result"]["details"].get("artifact_id")

                    engagement = request("POST", "/api/engagements", {
                        "name": "Synthetic Android static remediation", "asset_ids": [original["id"]],
                        "authorization_note": "Owned tiny synthetic APKs; static local review only, no app installation or execution."})
                    candidates = request("GET", f"/api/engagements/{engagement['id']}/candidates?job_id={baseline['id']}")["items"]
                    selected = next(row for row in candidates if row["category"] == "android.debuggable")
                    case = request("POST", f"/api/engagements/{engagement['id']}/cases", {
                        "job_id": baseline["id"], "source_kind": selected["source_kind"], "source_ref": selected["source_ref"]})
                    assert case["status"] == "open" and case["evidence"]
                    case_path = "/api/cases/" + case["id"]
                    revised = upload_apk(hardened_file)
                    retest = finished(request("POST", f"/api/assets/{revised['id']}/inspections", {
                        "name": "Synthetic APK corrected configuration", "checks": ["manifest"]}))
                    unlinked = request("GET", case_path + "/retest?job_id=" + retest["id"])
                    assert unlinked["outcome"] == "not_comparable"
                    case = request("POST", case_path + "/retest-inputs", {"expected_version": case["version"],
                        "asset_id": revised["id"], "note": "Same org.reachscope.staticfixture package rebuilt with reviewed flags and network policy."})
                    after = {row["id"]: row for row in retest["result"]["details"]["security_review"]["checks"]}
                    for check in ("android.debuggable", "android.cleartext", "android.trust_anchors"):
                        assert after[check]["status"] == "pass" and after[check]["complete"] is True
                    assessment = request("GET", case_path + "/retest?job_id=" + retest["id"])
                    assert assessment["outcome"] == "not_observed_in_scope" and assessment["input_revision"] is True
                    assert assessment["evidence"]
                    closed = request("PATCH", case_path, {"expected_version": case["version"], "status": "resolved",
                        "retest_job_id": retest["id"], "note": "Reviewed same-package corrected static evidence: debug flag no longer observed. Runtime behavior not tested."})
                    assert closed["status"] == "resolved" and closed["job_id"] == baseline["id"]
                    assert json.dumps(request("GET", "/api/jobs/" + baseline["id"]), sort_keys=True) == original_snapshot

                    full = finished(request("POST", asset_path + "/inspections", {
                        "name": "Synthetic APK full static analysis", "checks": ["manifest", "code_paths"]}))
                    full_checks = {row["id"]: row for row in full["result"]["details"]["security_review"]["checks"]}
                    assert full["result"]["details"]["artifact_id"] and full["result"]["summary"]["methods"] >= 1
                    for check in ("android.debuggable", "android.cleartext", "android.trust_anchors"):
                        assert full_checks[check]["status"] == before[check]["status"]
                    assert all(row["status"] == "completed" for row in full["result"]["details"]["execution"])
                    assert not request("GET", "/api/ai/config")["has_key"]
                    assert request("GET", "/api/jobs/" + baseline["id"] + "/advisories")["total"] == 0
                    report = {"passed": True, "origin": "synthetic_unsigned_compiled_apks", "apk_executed": False,
                        "network": "loopback workbench API only; no target or model requests", "case_status": closed["status"],
                        "baseline_execution": execution, "unlinked_retest": unlinked["outcome"],
                        "linked_retest": assessment["outcome"], "immutable_baseline": True,
                        "baseline_checks": {key: before[key]["status"] for key in before},
                        "corrected_checks": {key: after[key]["status"] for key in after},
                        "full_apk_methods": full["result"]["summary"]["methods"], "ai_reports": 0,
                        "limitations": ["Compiled synthetic APKs only; user APKs and installed Android runtime not tested.",
                                        "Manifest/resource declarations do not prove effective access or exploitable vulnerabilities."]}
                    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
                    print(json.dumps(report, ensure_ascii=True))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
