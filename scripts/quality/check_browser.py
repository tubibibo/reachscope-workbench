"""Portable browser release gate using isolated workspaces and local fixtures.

No real workspace/configuration or paid provider is used. Install the ui extra,
then Playwright Chromium, or pass --browser for an installed Chromium/Edge.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/validation/browser")
    parser.add_argument("--browser", type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("REACHSCOPE_AI_")}
    environment["PYTHONIOENCODING"] = "utf-8"
    browser = ["--browser", str(args.browser.resolve())] if args.browser else []
    checks: list[dict[str, object]] = []

    def run(name: str, script: str, extra: list[str] | None = None) -> None:
        print("Browser gate: " + name, flush=True)
        target = output / name
        target.mkdir(exist_ok=True)
        with (target / "runner.log").open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run([sys.executable, str(ROOT / script), "--out", str(target),
                                         *browser, *(extra or [])], cwd=ROOT, env=environment,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=240, check=False)
                passed = result.returncode == 0
            except subprocess.TimeoutExpired:
                passed = False
                log.write("\nBrowser group exceeded its 240-second deadline.\n")
        checks.append({"name": name, "passed": passed, "log": str(target / "runner.log")})

    run("onboarding", "tests/browser/check_onboarding.py")
    run("lab", "tests/browser/check_local_lab.py")
    run("android", "tests/browser/check_android.py")
    run("web-cloud", "tests/browser/check_web_cloud.py")
    run("blue", "tests/browser/check_blue_team.py")
    run("host-journey", "tests/browser/check_host_journey.py")
    run("frontend-security", "tests/browser/check_frontend_security.py", ["--phase", "after"])
    # The older protocol acceptance accepts a base URL. Supply only this newly
    # created temporary server; never fall back to the user's default port.
    with tempfile.TemporaryDirectory(prefix="reachscope-browser-protocol-") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with (output / "protocol-server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", "reachscope_workbench", "serve", "--port", str(port),
                                        "--data", directory], cwd=ROOT, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                ready = False
                deadline = time.monotonic() + 20
                with httpx.Client(trust_env=False, timeout=2) as client:
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            response = client.get(base + "/api/health")
                            if response.status_code == 200 and response.json().get("ready") is True:
                                ready = True
                                break
                        except (httpx.HTTPError, ValueError):
                            pass
                        time.sleep(.1)
                if ready:
                    run("ai-protocol", "tests/browser/check_ai_protocol.py", ["--base-url", base])
                else:
                    checks.append({"name": "ai-protocol", "passed": False, "error": "isolated server not ready"})
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    passed = all(item["passed"] is True for item in checks)
    (output / "browser-gate.json").write_text(json.dumps({"passed": passed, "scope": "isolated local fixtures only",
                                                        "commercial_inference": False, "groups": checks},
                                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Browser release gate: " + ("passed" if passed else "failed; inspect group logs"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
