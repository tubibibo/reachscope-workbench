"""Verify real Linux host collection in an explicitly disposable container.

The default is a read-only prerequisite report. --run needs a container marker,
REACHSCOPE_DISPOSABLE_LINUX=1 and --disposable-container. Never use a real host.
Only this harness writes fixture configuration; the collector remains read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

HOST_ID = "linux-acceptance-fixture-01"
CANARY = "reachscope-private-linux-canary"
COMPONENTS = ("ssh", "nginx")
CONFIG_PATHS = (Path("/etc/ssh/sshd_config"), Path("/etc/nginx/nginx.conf"))
SSH_RUNTIME = Path("/run/sshd")
MAX_CAPTURE = 512 * 1024
MAX_RESPONSE = 2 * 1024 * 1024


class AcceptanceError(Exception):
    """A fixed error class that never reflects raw command/API output."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceError(code)


def run_bounded(command: list[str], *, timeout: float = 20) -> bytes:
    """Bound each reviewed child command's combined output, time and memory."""
    environment = {key: value for key, value in os.environ.items()
                   if key != "PYTHONPATH" and not key.startswith("REACHSCOPE_AI_")}
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=environment, shell=False,
                               start_new_session=os.name != "nt", bufsize=0)
    chunks: list[bytes] = []
    total = 0
    exceeded = threading.Event()
    failed = threading.Event()
    lock = threading.Lock()

    def kill() -> None:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass

    def drain(stream: Any, keep: bool) -> None:
        nonlocal total
        try:
            while block := stream.read(4096):
                with lock:
                    total += len(block)
                    if total > MAX_CAPTURE:
                        exceeded.set()
                        kill()
                        return
                    if keep:
                        chunks.append(block)
        except (OSError, ValueError):
            failed.set()
        finally:
            try:
                stream.close()
            except OSError:
                failed.set()

    readers = [threading.Thread(target=drain, args=(process.stdout, True), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, False), daemon=True)]
    started = []
    timed_out = False
    try:
        for reader in readers:
            reader.start()
            started.append(reader)
        deadline = time.monotonic() + timeout
        while process.poll() is None or any(reader.is_alive() for reader in started):
            if exceeded.is_set():
                kill()
                break
            if time.monotonic() >= deadline:
                timed_out = True
                kill()
                break
            time.sleep(0.01)
    finally:
        # A dead leader does not mean its pipe-owning descendants have exited.
        if os.name != "nt" or process.poll() is None or any(reader.is_alive() for reader in started):
            kill()
        process.wait(timeout=5)
        for reader in started:
            reader.join(timeout=2)
    require(not timed_out, "command_timeout")
    require(not any(reader.is_alive() for reader in readers), "capture_reader_incomplete")
    require(not exceeded.is_set(), "command_output_budget")
    require(not failed.is_set(), "command_output_read_failed")
    require(process.returncode == 0, "command_nonzero_exit")
    return b"".join(chunks)


def prerequisite_report(bundle: Path | None, disposable_confirmed: bool) -> dict[str, Any]:
    linux = platform.system() == "Linux"
    container = linux and (Path("/.dockerenv").is_file() or Path("/run/.containerenv").is_file())
    binaries = {name: linux and os.access(path, os.X_OK)
                for name, path in (("sshd", "/usr/sbin/sshd"), ("nginx", "/usr/sbin/nginx"),
                                   ("ssh-keygen", "/usr/bin/ssh-keygen"))}
    blockers = []
    if not linux:
        blockers.append("linux_required")
    if not container:
        blockers.append("disposable_container_marker_required")
    if not disposable_confirmed or os.environ.get("REACHSCOPE_DISPOSABLE_LINUX") != "1":
        blockers.append("explicit_disposable_container_confirmation_required")
    if linux and getattr(os, "geteuid", lambda: -1)() != 0:
        blockers.append("fixture_configuration_write_permission_required")
    if not all(binaries.values()):
        blockers.append("real_linux_binaries_required")
    if bundle is None or not bundle.is_file() or bundle.is_symlink() or bundle.stat().st_size > MAX_RESPONSE:
        blockers.append("reviewed_collector_bundle_required")
    return {"status": "not_executed", "actual_linux_acceptance": False,
            "platform": platform.system(), "container_marker": bool(container),
            "binaries": binaries, "blockers": blockers, "network_scope": "loopback_only",
            "commercial_ai_requests": 0, "services_started": False,
            "configuration_written": False, "prerequisite_check_only": True}


def reject_live_or_mounted_configs() -> None:
    """Refuse named config mounts and already-running SSH/NGINX services."""
    require(all(path.parent.is_dir() and path.parent.resolve() == path.parent and not path.is_symlink()
                for path in CONFIG_PATHS), "unsafe_fixture_configuration_path")
    protected = {"/etc", "/etc/ssh", "/etc/nginx", *(str(path) for path in CONFIG_PATHS)}
    mounts = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    require(not any(len(line.split()) > 4 and line.split()[4] in protected for line in mounts),
            "host_configuration_mount_not_allowed")
    for path in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        require(name not in {"sshd", "nginx"}, "existing_service_not_allowed")


@contextmanager
def fixture_configs(root: Path) -> Iterator[Any]:
    """Replace only disposable-image config, restoring it even after failure."""
    reject_live_or_mounted_configs()
    original: dict[Path, tuple[bytes, int] | None] = {}
    for path in CONFIG_PATHS:
        require(not path.exists() or path.is_file(), "fixture_config_not_regular_file")
        if path.exists():
            require(path.stat().st_size <= MAX_CAPTURE, "existing_config_budget")
        original[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
    ssh_runtime = SSH_RUNTIME
    runtime_created = not ssh_runtime.exists()
    require(not ssh_runtime.is_symlink(), "unsafe_ssh_runtime_path")
    if runtime_created:
        ssh_runtime.mkdir(mode=0o755)
    key = root / "fixture_host_key"

    def write(hardened: bool) -> None:
        selected = "no" if hardened else "yes"
        CONFIG_PATHS[0].write_text(
            f"HostKey {key}\nUsePAM no\nPermitRootLogin {selected}\n"
            f"PasswordAuthentication {selected}\nPermitEmptyPasswords {selected}\n"
            f"MaxAuthTries {3 if hardened else 8}\nBanner {root / CANARY}\n", encoding="utf-8")
        CONFIG_PATHS[1].write_text(
            f"pid {root / 'nginx.pid'};\nerror_log stderr;\nevents {{ worker_connections 16; }}\n"
            "http { access_log off; "
            f"server_tokens {'off' if hardened else 'on'}; "
            "server { listen 127.0.0.1:18080; "
            f"server_name {CANARY}.invalid; autoindex {'off' if hardened else 'on'}; "
            f"location / {{ root {root / CANARY}; }} }} }}\n", encoding="utf-8")
        for path in CONFIG_PATHS:
            path.chmod(0o600)

    try:
        run_bounded(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        yield write
    finally:
        for path, saved in original.items():
            if saved is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(saved[0])
                path.chmod(saved[1])
        if runtime_created:
            ssh_runtime.rmdir()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class LocalAPI:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path: str, body: object | None = None, *, method: str | None = None) -> Any:
        require(path.startswith("/api/") and not path.startswith("//"), "invalid_local_api_path")
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=payload, method=method,
                                         headers={"Content-Type": "application/json",
                                                  "X-ReachScope-Client": "workbench"})
        with self.opener.open(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE + 1)
        require(len(raw) <= MAX_RESPONSE, "local_api_response_budget")
        return json.loads(raw)

    def uploaded_asset(self, raw: bytes, filename: str) -> dict[str, Any]:
        boundary = "reachscope-linux-controlled-fixture-upload"
        payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                   f"filename=\"{filename}\"\r\nContent-Type: application/json\r\n\r\n").encode()
        payload += raw + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(self.base + "/api/uploads", data=payload, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-ReachScope-Client": "workbench"})
        with self.opener.open(request, timeout=10) as response:
            data = response.read(MAX_RESPONSE + 1)
        require(len(data) <= MAX_RESPONSE, "local_api_response_budget")
        uploaded = json.loads(data)
        return self.request("/api/assets", {"kind": "host", "name": "Controlled Linux fixture",
            "source": {"profile_id": "host-baseline", "mode": "baseline", "host_id": HOST_ID,
                       "upload_id": uploaded["id"], "filename": uploaded["filename"]}})

    def completed(self, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.1)
            job = self.request("/api/jobs/" + job["id"])
        require(job["status"] == "completed", "local_inspection_not_completed")
        return job


def collect(bundle: Path, python: str, output: Path) -> tuple[bytes, dict[str, Any]]:
    args = [python, "-I", str(bundle), "--host-id", HOST_ID, "--ssh-context", "global", "--output", str(output)]
    plan = json.loads(run_bounded(args))
    require(not output.exists(), "collector_preview_created_output")
    digest = plan.get("plan_sha256")
    require(isinstance(digest, str) and len(digest) == 64, "collector_plan_digest_missing")
    run_bounded([*args, "--collect", "--plan-sha256", digest])
    require(output.is_file() and not output.is_symlink() and output.stat().st_size <= MAX_RESPONSE,
            "collector_snapshot_output_invalid")
    require(output.stat().st_mode & 0o077 == 0, "collector_snapshot_permissions_too_broad")
    raw = output.read_bytes()
    snapshot = json.loads(raw)
    require(snapshot.get("schema_version") == "reachscope-host/2", "collector_schema_mismatch")
    require(snapshot.get("host_id") == HOST_ID, "collector_host_identity_changed")
    metadata = snapshot.get("collector", {})
    require(metadata.get("plan_sha256") == digest, "collector_plan_digest_mismatch")
    require(metadata.get("projection") == "reachscope-minimal/1", "collector_projection_mismatch")
    components = metadata.get("components", {})
    require(all(components.get(name, {}).get("state") == "collected"
                and components[name].get("complete") is True for name in COMPONENTS),
            "real_component_capture_incomplete")
    require(CANARY.encode() not in raw and b"BEGIN OPENSSH PRIVATE KEY" not in raw,
            "collector_private_fixture_value_leaked")
    return raw, snapshot


def api_workflow(api: LocalAPI, before_raw: bytes, after_raw: bytes) -> dict[str, Any]:
    jobs_before = api.request("/api/jobs")["total"]
    before_asset = api.uploaded_asset(before_raw, "linux-before.json")
    before_path = f"/api/assets/{before_asset['id']}"
    preview = api.request(before_path + "/preflight", {"checks": list(COMPONENTS)})
    require(preview["ready"] and preview["network"] is False, "collector_upload_preflight_not_ready")
    require(preview["input_preview"]["analysis_executed"] is False
            and preview["input_preview"]["network_requests"] is False, "preview_executed_analysis")
    require(api.request("/api/jobs")["total"] == jobs_before, "preview_created_job")
    require("effective_config" not in json.dumps(preview), "preview_disclosed_config_body")
    before = api.completed(api.request(before_path + "/inspections", {"checks": list(COMPONENTS)}))
    before_checks = {row["id"]: row for row in before["result"]["details"]["checks"]}
    selected_rules = ("host.ssh.root_login", "host.nginx.autoindex")
    all_revised_rules = (*selected_rules, "host.ssh.password_auth", "host.ssh.empty_passwords",
                         "host.ssh.max_auth_tries", "host.nginx.server_tokens")
    execution = {row["id"]: row["status"] for row in before["result"]["details"]["execution"]}
    require(execution == {"ssh": "completed", "nginx": "completed", "web_logs": "skipped", "auth_logs": "skipped"},
            "selected_group_execution_mismatch")
    require(all(before_checks[rule]["status"] == "review" and before_checks[rule]["complete"] is True
                for rule in selected_rules), "controlled_weak_configuration_not_observed")
    immutable = json.dumps(before, sort_keys=True)
    after_asset = api.uploaded_asset(after_raw, "linux-after.json")
    after = api.completed(api.request(f"/api/assets/{after_asset['id']}/inspections",
                                     {"checks": list(COMPONENTS)}))
    after_checks = {row["id"]: row for row in after["result"]["details"]["checks"]}
    require(all(after_checks[rule]["status"] == "pass" and after_checks[rule]["complete"] is True
                for rule in all_revised_rules), "controlled_hardened_configuration_not_observed")
    engagement = api.request("/api/engagements", {"name": "Real Linux controlled acceptance",
        "asset_ids": [before_asset["id"]],
        "authorization_note": "Disposable local container and harness-owned configuration only; no deployed-service claim."})
    scope = f"/api/engagements/{engagement['id']}"
    candidates = api.request(scope + "/candidates?job_id=" + before["id"])["items"]
    outcomes = []
    for rule in selected_rules:
        candidate = next(row for row in candidates if row["category"] == rule)
        case = api.request(scope + "/cases", {"job_id": before["id"], "source_kind": candidate["source_kind"],
                                               "source_ref": candidate["source_ref"]})
        path = f"/api/cases/{case['id']}"
        require(api.request(path + "/retest?job_id=" + after["id"])["outcome"] == "not_comparable",
                "unlinked_revision_was_comparable")
        linked = api.request(path + "/retest-inputs", {"expected_version": case["version"],
            "asset_id": after_asset["id"], "note": "Same fixture host, context and collector projection; explicit association."})
        assessment = api.request(path + "/retest?job_id=" + after["id"])
        require(assessment["outcome"] == "not_observed_in_scope" and assessment["input_revision"],
                "real_collector_revision_not_comparable")
        closed = api.request(path, {"expected_version": linked["version"], "status": "resolved",
            "retest_job_id": after["id"], "note": "Human-reviewed fixture configuration only; services were never started."},
            method="PATCH")
        require(closed["status"] == "resolved" and closed["asset_id"] == before_asset["id"],
                "human_case_closure_failed")
        outcomes.append({"rule_id": rule, "retest_outcome": assessment["outcome"], "case_status": closed["status"]})
    require(json.dumps(api.request("/api/jobs/" + before["id"]), sort_keys=True) == immutable,
            "baseline_job_was_mutated")
    require(api.request(f"/api/jobs/{before['id']}/advisories")["total"] == 0, "unexpected_ai_report")
    require(CANARY not in json.dumps({"before": before, "after": after}), "private_value_in_saved_result")
    return {"preview_created_job": False, "baseline_immutable": True, "cases": outcomes,
            "selected_groups": list(COMPONENTS), "origin_authenticated": False,
            "deployed_or_loaded_service_verified": False, "commercial_ai_requests": 0}


def execute(bundle: Path, python: str, output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="reachscope-linux-fixture-") as temporary:
        root = Path(temporary)
        with fixture_configs(root) as write:
            write(False)
            # Explicit real binary preconditions precede the collector. Neither
            # -T command starts a service; their full output stays in memory.
            run_bounded(["/usr/sbin/sshd", "-T"])
            run_bounded(["/usr/sbin/nginx", "-T"])
            before_raw, before = collect(bundle, python, output / "linux-before.json")
            write(True)
            run_bounded(["/usr/sbin/sshd", "-T"])
            run_bounded(["/usr/sbin/nginx", "-T"])
            after_raw, after = collect(bundle, python, output / "linux-after.json")
            require(all(str(root).encode() not in raw and b"127.0.0.1" not in raw
                        for raw in (before_raw, after_raw)), "collector_private_path_or_address_leaked")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        environment = {key: value for key, value in os.environ.items()
                       if key != "PYTHONPATH" and not key.startswith("REACHSCOPE_AI_")}
        server = subprocess.Popen([python, "-I", "-m", "reachscope_workbench", "serve", "--port", str(port),
                                   "--data", str(output / "workspace")], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment, shell=False)
        try:
            api = LocalAPI(port)
            deadline = time.monotonic() + 15
            while True:
                require(server.poll() is None, "local_api_server_stopped")
                try:
                    api.request("/api/modules")
                    break
                except OSError:
                    require(time.monotonic() < deadline, "local_api_startup_timeout")
                    time.sleep(0.1)
            workflow = api_workflow(api, before_raw, after_raw)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
    return {"status": "passed", "actual_linux_acceptance": True, "platform": platform.system(),
            "network_scope": "loopback_only", "services_started": False, "configuration_written": True,
            "configuration_scope": "disposable_container_fixture_only", "fixture_configuration_restored": True,
            "collector_bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "collector_version": before["collector"]["version"], "snapshot_schema": before["schema_version"],
            "snapshots": {"before_sha256": hashlib.sha256(before_raw).hexdigest(),
                          "after_sha256": hashlib.sha256(after_raw).hexdigest(),
                          "before_collected_at": before["collected_at"], "after_collected_at": after["collected_at"]},
            "components": after["collector"]["components"], "host_defense_workflow": workflow}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Reviewed collector.pyz; never downloaded or built by this harness.")
    parser.add_argument("--python", default=sys.executable, help="Python with the installed workbench package.")
    parser.add_argument("--out", type=Path, help="New/empty artifact directory. Required for --run.")
    parser.add_argument("--run", action="store_true", help="Execute controlled fixtures only inside a disposable container.")
    parser.add_argument("--disposable-container", action="store_true", help="Confirm this container contains no real assets.")
    parser.add_argument("--required", action="store_true", help="Return exit 2 rather than 0 when Linux acceptance cannot run.")
    args = parser.parse_args(argv)
    bundle = args.bundle.absolute() if args.bundle else None
    report = prerequisite_report(bundle, args.disposable_container)
    code = 0
    if args.run and not report["blockers"]:
        if args.out is None:
            parser.error("--run requires --out pointing to a new or empty directory")
        output = args.out.absolute()
        if output.resolve() != output or output.exists() and (not output.is_dir() or any(output.iterdir())):
            parser.error("--out must be a new or empty non-symlink directory; existing records are never reused")
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        output.chmod(0o700)
        try:
            require(bundle is not None, "reviewed_collector_bundle_required")
            report = execute(bundle, args.python, output)
        except (AcceptanceError, OSError, ValueError, KeyError, TypeError, RuntimeError,
                StopIteration, subprocess.SubprocessError) as exc:
            report = {"status": "failed", "actual_linux_acceptance": False,
                      "error_class": str(exc) if isinstance(exc, AcceptanceError) else type(exc).__name__,
                      "commercial_ai_requests": 0, "deployed_or_loaded_service_verified": False}
            code = 1
        report_path = output / "host-linux-acceptance.json"
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
        report_path.chmod(0o600)
    elif args.required:
        code = 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
