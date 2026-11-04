"""Harness safety tests; these do not claim real Linux binary acceptance."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import stat
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke" / "check_host_linux.py"
SPEC = importlib.util.spec_from_file_location("host_linux_acceptance_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def windows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness.platform, "system", lambda: "Windows")


def test_prerequisite_report_does_not_execute_or_infer_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    windows_only(monkeypatch)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not run a process"))
    report = harness.prerequisite_report(None, False)
    assert report["status"] == "not_executed"
    assert report["actual_linux_acceptance"] is False
    assert report["configuration_written"] is False
    assert report["services_started"] is False
    assert "linux_required" in report["blockers"]


@pytest.mark.parametrize("required,exit_code", [(False, 0), (True, 2)])
def test_unavailable_run_never_touches_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str], required: bool, exit_code: int) -> None:
    windows_only(monkeypatch)
    output = tmp_path / "no-output"
    monkeypatch.setattr(harness, "execute", lambda *args: pytest.fail("must not execute fixtures"))
    args = ["--run", "--disposable-container", "--out", str(output)]
    assert harness.main([*args, *(["--required"] if required else [])]) == exit_code
    assert not output.exists()
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_executed" and not report["actual_linux_acceptance"]


def test_available_prerequisites_without_run_are_still_not_execution(monkeypatch: pytest.MonkeyPatch,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(harness, "prerequisite_report", lambda *args: {
        "status": "not_executed", "actual_linux_acceptance": False, "blockers": []})
    monkeypatch.setattr(harness, "execute", lambda *args: pytest.fail("no --run was supplied"))
    assert harness.main([]) == 0
    assert json.loads(capsys.readouterr().out)["actual_linux_acceptance"] is False


def test_existing_workspace_never_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(harness, "prerequisite_report", lambda *args: {"blockers": []})
    monkeypatch.setattr(harness, "execute", lambda *args: pytest.fail("must not reuse output"))
    sentinel = tmp_path / "existing-operator-record"
    sentinel.write_text("unchanged", encoding="utf-8")
    with pytest.raises(SystemExit) as captured:
        harness.main(["--run", "--out", str(tmp_path)])
    assert captured.value.code == 2
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_failure_report_redacts_exception_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(harness, "prerequisite_report", lambda *args: {"blockers": []})

    def fail(*args: Any) -> None:
        raise OSError(harness.CANARY + " raw private command output")

    monkeypatch.setattr(harness, "execute", fail)
    bundle = tmp_path / "reviewed.pyz"
    bundle.write_bytes(b"not executed by this mocked safety test")
    out = tmp_path / "artifacts"
    assert harness.main(["--run", "--bundle", str(bundle), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    report = json.loads(printed)
    assert report["status"] == "failed" and report["actual_linux_acceptance"] is False
    assert report["error_class"] == "OSError"
    assert harness.CANARY not in printed
    assert json.loads((out / "host-linux-acceptance.json").read_text()) == report


def fixture_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[tuple[Path, ...], Path]:
    configs = (tmp_path / "ssh" / "sshd_config", tmp_path / "nginx" / "nginx.conf")
    for path in configs:
        path.parent.mkdir()
        path.write_bytes(b"original fixture configuration\n")
        path.chmod(0o644)
    runtime = tmp_path / "sshd-runtime"
    monkeypatch.setattr(harness, "CONFIG_PATHS", configs)
    monkeypatch.setattr(harness, "SSH_RUNTIME", runtime)
    monkeypatch.setattr(harness, "reject_live_or_mounted_configs", lambda: None)
    return configs, runtime


def test_fixture_configuration_and_permissions_restored_after_failure(monkeypatch: pytest.MonkeyPatch,
                                                                     tmp_path: Path) -> None:
    configs, runtime = fixture_paths(monkeypatch, tmp_path)
    original = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in configs}
    monkeypatch.setattr(harness, "run_bounded", lambda *args: b"")
    with pytest.raises(harness.AcceptanceError, match="controlled_failure"), harness.fixture_configs(tmp_path) as write:
        write(False)
        assert b"PermitRootLogin yes" in configs[0].read_bytes()
        assert b"autoindex on" in configs[1].read_bytes()
        raise harness.AcceptanceError("controlled_failure")
    assert not runtime.exists()
    assert {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in configs} == original


def test_key_generation_failure_also_removes_created_runtime(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    configs, runtime = fixture_paths(monkeypatch, tmp_path)

    def fail(*args: Any) -> None:
        raise harness.AcceptanceError("command_nonzero_exit")

    monkeypatch.setattr(harness, "run_bounded", fail)
    with pytest.raises(harness.AcceptanceError, match="command_nonzero_exit"), harness.fixture_configs(tmp_path):
        pytest.fail("failed key generation must never yield fixture writer")
    assert not runtime.exists()
    assert all(path.read_bytes() == b"original fixture configuration\n" for path in configs)


def test_bounded_process_separates_stderr_and_preserves_json() -> None:
    raw = harness.run_bounded([sys.executable, "-c",
                              "import sys;sys.stderr.write('private diagnostic');print('{\"ok\":true}')"])
    assert json.loads(raw) == {"ok": True}
    assert b"private diagnostic" not in raw


def test_failed_process_does_not_reflect_private_error() -> None:
    with pytest.raises(harness.AcceptanceError) as captured:
        harness.run_bounded([sys.executable, "-c", "import sys;sys.stderr.write('PRIVATE_SECRET');sys.exit(7)"])
    assert str(captured.value) == "command_nonzero_exit"
    assert "PRIVATE_SECRET" not in str(captured.value)


def test_process_timeout_is_failure() -> None:
    with pytest.raises(harness.AcceptanceError, match="command_timeout"):
        harness.run_bounded([sys.executable, "-c", "import time;time.sleep(5)"], timeout=0.1)


def test_process_budget_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "MAX_CAPTURE", 4096)
    with pytest.raises(harness.AcceptanceError, match="command_output_budget"):
        harness.run_bounded([sys.executable, "-c", "import sys;sys.stdout.write('x'*16384)"])


def test_dead_leader_still_causes_owned_pipe_group_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    killed = threading.Event()

    class Pipe:
        def read(self, size: int) -> bytes:
            assert killed.wait(timeout=2), "a dead leader's pipe owner was not stopped"
            return b""

        def close(self) -> None:
            pass

    class DeadLeader:
        pid = 314159265
        stdout, stderr = Pipe(), Pipe()
        returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            killed.set()

        def wait(self, timeout: float) -> int:
            return 0

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: DeadLeader())
    monkeypatch.setattr(harness.os, "killpg", lambda *args: killed.set(), raising=False)
    with pytest.raises(harness.AcceptanceError, match="command_timeout"):
        harness.run_bounded(["controlled-test-only"], timeout=0.03)
    assert killed.is_set()


@pytest.mark.skipif(sys.platform != "linux", reason="real POSIX session/pipe-owner cleanup needs Linux")
def test_real_linux_dead_leader_descendant_is_stopped(tmp_path: Path) -> None:
    pid_file = tmp_path / "owned-child-pid"
    code = ("import os,signal,time; pid=os.fork(); "
            f"open({str(pid_file)!r},'w').write(str(pid)) if pid else None; "
            "os._exit(0) if pid else None; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)")
    start = time.monotonic()
    try:
        with pytest.raises(harness.AcceptanceError, match="command_timeout"):
            harness.run_bounded([sys.executable, "-c", code], timeout=0.3)
        assert time.monotonic() - start < 3
        require_pid = int(pid_file.read_text(encoding="ascii"))
        status = Path(f"/proc/{require_pid}/status")
        assert not status.exists() or "State:\tZ" in status.read_text(encoding="ascii")
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text(encoding="ascii")), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_local_api_rejects_non_api_path_before_network() -> None:
    with pytest.raises(harness.AcceptanceError, match="invalid_local_api_path"):
        harness.LocalAPI(1).request("//example.invalid/")


@pytest.mark.parametrize("kind", ["redirect", "over_budget"])
def test_local_api_cannot_redirect_or_capture_unbounded_response(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            if kind == "redirect":
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/private")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"x" * 1024)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(harness, "MAX_RESPONSE", 64)
    try:
        error = urllib.error.HTTPError if kind == "redirect" else harness.AcceptanceError
        with pytest.raises(error):
            harness.LocalAPI(server.server_port).request("/api/probe")
        assert requests == ["/api/probe"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
