"""Collector unit boundaries; fake commands do not claim real-service acceptance."""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reachscope_workbench.collectors.host import collector, projection, runner
from reachscope_workbench.collectors.host.builder import build_zipapp
from reachscope_workbench.modules.host.baseline import assess_baseline
from reachscope_workbench.modules.host.input import parse_baseline

SSH = b"permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"
NGINX = b"http { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; server { listen 443 ssl; server_name private.example; location /private/customer { } } }"


def test_preview_is_explicit_deterministic_and_has_no_collection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(collector, "run_component", lambda _: pytest.fail("preview ran a command"))
    destination = str(tmp_path / "snapshot.json")
    first = collector.plan("host-01", "global", destination)
    assert first == collector.plan("host-01", "global", destination)
    assert Path(first["output"]).is_absolute()
    assert first["network_upload"] is first["automatic_sudo"] is False
    assert first["commands"] == {"ssh": ["/usr/sbin/sshd", "-T"], "nginx": ["/usr/sbin/nginx", "-T"]}
    assert collector.main(["--host-id", "host-01", "--output", destination]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert not Path(destination).exists()


def test_relative_plan_is_bound_to_absolute_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    original = collector.plan("host", "global", "snapshot.json")
    monkeypatch.chdir(second)
    changed = collector.plan("host", "global", "snapshot.json")
    assert original["plan_sha256"] != changed["plan_sha256"]
    assert Path(original["output"]).parent == first


@pytest.mark.parametrize(("host", "context"), [("", "global"), (" padded", "global"), ("x" * 129, "global"), ("host\nprivate", "global"), ("host", "global\0")])
def test_labels_fail_without_reflecting_input(host: str, context: str) -> None:
    with pytest.raises(collector.CollectorError, match="^invalid_label$"):
        collector.plan(host, context, "snapshot.json")


@pytest.mark.parametrize("output", ["", "x\nsecret", "x" * 4097])
def test_invalid_output_is_not_echoed(output: str) -> None:
    with pytest.raises(collector.CollectorError, match="^invalid_output$"):
        collector.plan("host", "global", output)


def test_confirmation_mismatch_never_runs_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(collector, "collect_snapshot", lambda *_: pytest.fail("unconfirmed collection"))
    assert collector.main(["--host-id", "host", "--output", str(tmp_path / "x"), "--collect", "--plan-sha256", "a" * 64]) == 2
    assert json.loads(capsys.readouterr().err)["reason_code"] == "plan_confirmation_required"


def test_collect_main_uses_confirmed_absolute_destination(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    prepared = collector.plan("host", "global", "snapshot.json")
    snapshot = {"schema_version": "reachscope-host/2", "collector": {"components": {}}}
    writes: list[tuple[str, Any]] = []
    monkeypatch.setattr(collector, "collect_snapshot", lambda *_: snapshot)
    monkeypatch.setattr(collector, "write_snapshot", lambda output, value: writes.append((output, value)))
    assert collector.main(["--host-id", "host", "--output", "snapshot.json", "--collect", "--plan-sha256", prepared["plan_sha256"]]) == 0
    assert writes == [(str(tmp_path / "snapshot.json"), snapshot)]
    assert json.loads(capsys.readouterr().out)["status"] == "exported"


@pytest.mark.parametrize(("error", "expected", "status"), [(KeyboardInterrupt(), 130, "cancelled"), (PermissionError("secret-path"), 2, "failed")])
def test_cancel_and_permission_failures_are_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], error: BaseException, expected: int, status: str) -> None:
    def fail(*_: Any) -> Any:
        raise error
    destination = str(tmp_path / "x")
    prepared = collector.plan("host", "global", destination)
    monkeypatch.setattr(collector, "collect_snapshot", fail)
    assert collector.main(["--host-id", "host", "--output", destination, "--collect", "--plan-sha256", prepared["plan_sha256"]]) == expected
    captured = capsys.readouterr()
    assert json.loads(captured.err)["status"] == status
    assert "secret-path" not in captured.err


def test_linux_guard_precedes_any_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "_linux", lambda: False)
    monkeypatch.setattr(collector, "run_component", lambda _: pytest.fail("non-Linux command"))
    with pytest.raises(collector.CollectorError, match="linux_required"):
        collector.collect_snapshot("host", "global", "a" * 64)


def captured_snapshot(monkeypatch: pytest.MonkeyPatch, *, context: str = "global", ssh: bytes = SSH, nginx: bytes = NGINX) -> dict[str, Any]:
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "run_component", lambda name: runner.CommandResult("collected", "ok", 0, {"ssh": ssh, "nginx": nginx}[name]))
    return collector.collect_snapshot("host-01", context, "a" * 64)


def test_collected_schema_round_trips_real_parser_and_static_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = captured_snapshot(monkeypatch)
    result = assess_baseline(parse_baseline(json.dumps(snapshot).encode(), "host-01"), ["ssh", "nginx"])
    assert len(result["checks"]) == 7
    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["coverage"]["runtime_state_verified"] is False
    assert all(row["complete"] and row["state"] == "collected" for row in snapshot["collector"]["components"].values())


def test_unsupported_context_never_executes_sshd(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "run_component", lambda name: calls.append(name) or runner.CommandResult("collected", "ok", 0, NGINX))
    snapshot = collector.collect_snapshot("host", "connection-specific", "a" * 64)
    assert calls == ["nginx"]
    assert snapshot["ssh"]["effective_config"] is None
    assert snapshot["collector"]["components"]["ssh"] == {"state": "unsupported", "complete": False, "reason_code": "context_unsupported"}


@pytest.mark.parametrize(("state", "reason", "code"), [("unavailable", "missing_executable", None), ("unavailable", "execution_unavailable", None), ("failed", "nonzero_exit", 1), ("failed", "output_read_failed", 0), ("timeout", "command_timeout", -9), ("budget_exceeded", "output_budget", -9)])
def test_failed_components_have_no_raw_text_and_remain_unknown(monkeypatch: pytest.MonkeyPatch, state: str, reason: str, code: int | None) -> None:
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "run_component", lambda _: runner.CommandResult(state, reason, code, b"never-export-secret"))
    snapshot = collector.collect_snapshot("host-01", "global", "a" * 64)
    assert snapshot["ssh"]["effective_config"] is snapshot["nginx"]["config_dump"] is None
    assert "never-export-secret" not in json.dumps(snapshot)
    result = assess_baseline(parse_baseline(json.dumps(snapshot).encode(), "host-01"), ["ssh", "nginx"])
    assert all(check["status"] == "unknown" for check in result["checks"])


def test_projection_failure_has_no_raw_export_in_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = captured_snapshot(monkeypatch, nginx=b"http { include /secret/missing.conf; }")
    assert snapshot["nginx"]["config_dump"] is None
    assert snapshot["collector"]["components"]["nginx"]["reason_code"] == "projection_unsupported"
    assert "/secret/" not in json.dumps(snapshot)


def test_ssh_projection_only_keeps_four_actual_fields() -> None:
    raw = SSH + b"hostkey /secret/host_private_key\nauthorizedkeyscommand /secret/password-helper\nbanner very-private-tenant\n"
    projected = projection.project_ssh(raw)
    assert len(projected.splitlines()) == 4
    assert "secret" not in projected and "tenant" not in projected


@pytest.mark.parametrize("raw", [SSH + b"permitrootlogin yes\n", SSH + b"Match User root\n", SSH + b"Include /secret\n", SSH.replace(b"maxauthtries 3", b"maxauthtries 0"), SSH.replace(b"passwordauthentication no", b"passwordauthentication maybe"), SSH.replace(b"permitrootlogin no", b'permitrootlogin "" no'), SSH.replace(b"permitrootlogin no", b'permitrootlogin "no'), SSH.replace(b"permitrootlogin no", b"permitrootlogin"), SSH + b"banner a\0b", b"\xff", b"x" * (256 * 1024 + 1)])
def test_unsupported_ssh_never_projects_a_pass(raw: bytes) -> None:
    with pytest.raises(projection.ProjectionUnsupported, match="^projection_unsupported$"):
        projection.project_ssh(raw)


def test_nginx_projection_removes_sensitive_leaves_and_hashes_context() -> None:
    raw = NGINX.replace(b"listen 443 ssl", b"listen 192.0.2.123:443 ssl").replace(b"location /private/customer {", b'proxy_set_header Authorization "Bearer password-secret"; ssl_certificate_key /secret/private.pem; location /private/customer {')
    value = projection.project_nginx(raw)
    assert value == projection.project_nginx(raw)
    for secret in ("192.0.2.123", "private.example", "/private/customer", "password-secret", "/secret/private.pem"):
        assert secret not in value
    assert "bind-" in value and "name-" in value and "route-" in value
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in value
    assert "autoindex off;" in value


def test_nginx_exported_file_includes_are_resolved_without_local_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: pytest.fail("read a local include"))
    raw = b"# configuration file /etc/nginx/nginx.conf:\nevents {}\nhttp { autoindex off; server_tokens off; ssl_protocols TLSv1.2 TLSv1.3; include /etc/nginx/conf.d/*.conf; }\n# configuration file /etc/nginx/conf.d/site.conf:\nserver { listen 443 ssl; server_name sensitive.example; location / { autoindex on; } }\n"
    value = projection.project_nginx(raw)
    assert "include" not in value and "/etc/" not in value and "sensitive.example" not in value
    assert "autoindex on;" in value


def test_nginx_context_and_shared_ssl_socket_semantics_survive_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"http { autoindex off; server_tokens off; server { listen 443 default_server; server_name weak.example; ssl_protocols TLSv1; } server { listen 443 ssl; server_name safe.example; ssl_protocols TLSv1.2 TLSv1.3; location /x { autoindex on; } } }"
    snapshot = captured_snapshot(monkeypatch, nginx=raw)
    projected = snapshot["nginx"]["config_dump"]
    assert "listen 443 default_server;" in projected and "listen 443 ssl;" in projected and "ssl_protocols TLSv1;" in projected
    result = assess_baseline(parse_baseline(json.dumps(snapshot).encode(), "host-01"), ["nginx"])
    statuses = {check["id"]: check["status"] for check in result["checks"]}
    assert statuses["host.nginx.tls_protocols"] != "pass"
    assert statuses["host.nginx.autoindex"] == "review"


@pytest.mark.parametrize("raw", [b"http { include /missing/*.conf; server {} }", b"http { include relative.conf; server {} }", b"http { include /etc/$tenant.conf; server {} }", b"http { server { if ($request_uri) { return 200; } } }", b"http { server { location $uri { autoindex off; } } }", b"http unexpected { server {} }", b"http { server unexpected {} }", b'http { autoindex "" off; server {} }', b'http { server_tokens "" off; server {} }', b"http { ssl_protocols unknown; server {} }", b'http { server_name "unterminated; server {} }', b"http { server { listen unix:/secret/socket; } }", b"http { server { listen 443 secret_flag; } }", b"http { map x y { default z; autoindex off; } server {} }", b"http { server { location / { ssl_protocols TLSv1.2; } } }", b"http { server {} }\0", b"http {}", b"http { server {}", b"\xff"])
def test_unsupported_nginx_gaps_fail_closed(raw: bytes) -> None:
    with pytest.raises(projection.ProjectionUnsupported, match="^projection_unsupported$"):
        projection.project_nginx(raw)


def test_nginx_include_cycles_and_duplicate_sections_are_unknown() -> None:
    for raw in (b"# configuration file /main:\nhttp { include /main; server {} }", b"# configuration file /main:\nhttp { server {} }\n# configuration file /main:\nserver {}"):
        with pytest.raises(projection.ProjectionUnsupported):
            projection.project_nginx(raw)


def test_nginx_bounded_contexts_and_tokens_fail_closed() -> None:
    for raw in (("http {" + "server {}" * 201 + "}").encode(), ("http { server { " + "x " * 20001 + "; } }").encode(), ("http { server { server_name " + "x" * 4097 + "; } }").encode()):
        with pytest.raises(projection.ProjectionUnsupported):
            projection.project_nginx(raw)


class FakeProcess:
    def __init__(self, stdout: bytes = SSH, stderr: bytes = b"private-diagnostic", code: int | None = 0) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = code
        self.pid = 12345

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_runner_only_uses_fixed_argv_and_minimal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[Any, dict[str, Any]]] = []
    process = FakeProcess()
    monkeypatch.setattr(runner.subprocess, "Popen", lambda command, **kwargs: called.append((command, kwargs)) or process)
    result = runner.run_component("ssh")
    assert result == runner.CommandResult("collected", "ok", 0, SSH)
    argv, options = called[0]
    assert argv == ("/usr/sbin/sshd", "-T") and options["shell"] is False and options["bufsize"] == 0
    assert set(options["env"]) == {"PATH", "LANG", "LC_ALL"}
    assert options["cwd"] == "/" and "private-diagnostic" not in repr(result)


@pytest.mark.parametrize(("error", "reason"), [(FileNotFoundError("private-path"), "missing_executable"), (PermissionError("private-path"), "execution_unavailable")])
def test_runner_spawn_failures_are_safe_unavailable(monkeypatch: pytest.MonkeyPatch, error: OSError, reason: str) -> None:
    def fail(*_: Any, **__: Any) -> Any:
        raise error
    monkeypatch.setattr(runner.subprocess, "Popen", fail)
    result = runner.run_component("nginx")
    assert result.state == "unavailable" and result.reason_code == reason
    assert "private-path" not in repr(result)


def test_runner_nonzero_discards_even_apparently_safe_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess(code=1))
    assert runner.run_component("ssh") == runner.CommandResult("failed", "nonzero_exit", 1)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_runner_output_and_diagnostic_budgets_are_enforced(monkeypatch: pytest.MonkeyPatch, channel: str) -> None:
    process = FakeProcess(stdout=b"x" * 100 if channel == "stdout" else SSH, stderr=b"x" * 100 if channel == "stderr" else b"")
    monkeypatch.setattr(runner, "STDOUT_LIMIT", 80)
    monkeypatch.setattr(runner, "STDERR_LIMIT", 80)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    stopped: list[bool] = []
    monkeypatch.setattr(runner, "_stop", lambda _: stopped.append(True))
    result = runner.run_component("ssh")
    assert result.state == "budget_exceeded" and result.stdout is None
    # Threads may finish before the owner loop; the post-loop budget still wins.
    assert process.stdout.closed and process.stderr.closed


def test_runner_timeout_stops_owned_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(code=None)
    stopped: list[bool] = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runner, "TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(runner, "_stop", lambda _: stopped.append(True))
    assert runner.run_component("ssh").reason_code == "command_timeout"
    assert stopped and process.stdout.closed


def test_runner_read_failure_never_exports_partial_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(io.BytesIO):
        def read(self, *args: Any, **kwargs: Any) -> bytes:
            raise OSError("private-error")
    process = FakeProcess()
    process.stdout = Broken()
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    assert runner.run_component("ssh") == runner.CommandResult("failed", "output_read_failed", 0)


def test_runner_cancel_and_thread_start_failure_both_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(code=None)
    stopped: list[bool] = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runner, "_stop", lambda _: stopped.append(True))
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt
    monkeypatch.setattr(runner.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run_component("ssh")
    assert stopped and process.stdout.closed and process.stderr.closed
    process = FakeProcess(code=None)
    stopped.clear()
    def fail_start(_: Any) -> None:
        raise RuntimeError("thread unavailable")
    monkeypatch.setattr(runner.threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        runner.run_component("ssh")
    assert stopped and process.stdout.closed and process.stderr.closed


def test_stop_kills_owned_group_even_when_leader_already_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix", killpg=lambda pid, sig: sent.append((pid, sig))))
    runner._stop(FakeProcess())  # type: ignore[arg-type]
    assert sent == [(12345, signal.SIGTERM), (12345, getattr(signal, "SIGKILL", 9))]


@pytest.mark.skipif(sys.platform != "linux", reason="actual POSIX process-group boundary requires Linux")
def test_linux_owned_descendant_cannot_hold_timeout_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    # This launches only test Python, never sshd/nginx or a target host.
    script = "import os,signal,time; pid=os.fork(); (os._exit(0) if pid else None); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)"
    monkeypatch.setitem(runner.COMMANDS, "ssh", (sys.executable, "-c", script))
    monkeypatch.setattr(runner, "TIMEOUT_SECONDS", .2)
    started = time.monotonic()
    result = runner.run_component("ssh")
    assert result.reason_code == "command_timeout" and time.monotonic() - started < 4


@pytest.mark.skipif(sys.platform != "linux", reason="dirfd/O_NOFOLLOW publication requires Linux")
def test_linux_writer_is_atomic_0600_and_never_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot.json"
    collector.write_snapshot(str(destination), {"safe": True})
    assert json.loads(destination.read_text()) == {"safe": True}
    assert destination.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [destination]
    with pytest.raises(collector.CollectorError, match="output_exists"):
        collector.write_snapshot(str(destination), {"safe": False})
    assert json.loads(destination.read_text()) == {"safe": True}


@pytest.mark.skipif(sys.platform != "linux", reason="real symbolic-link boundary requires Linux")
def test_linux_writer_rejects_target_and_parent_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    target = tmp_path / "target.json"
    target.symlink_to(real / "private.json")
    with pytest.raises(collector.CollectorError, match="output_exists"):
        collector.write_snapshot(str(target), {})
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        collector.write_snapshot(str(alias / "snapshot.json"), {})
    assert not list(real.iterdir())


def test_writer_failure_always_closes_anchored_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    closed: list[int] = []
    def missing(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError
    def denied(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("private-directory")
    fake = SimpleNamespace(O_WRONLY=1, O_CREAT=2, O_EXCL=4, O_NOFOLLOW=8, stat=missing, open=denied, close=closed.append)
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "_directory", lambda _: 99)
    monkeypatch.setattr(collector, "os", fake)
    with pytest.raises(PermissionError):
        collector.write_snapshot(str(tmp_path / "snapshot.json"), {})
    assert closed == [99]


def test_writer_refuses_oversized_snapshot_before_destination_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "_directory", lambda _: pytest.fail("oversized write touched directory"))
    with pytest.raises(collector.CollectorError, match="snapshot_budget"):
        collector.write_snapshot("/tmp/snapshot.json", {"x": "x" * (512 * 1024)})


def test_fdopen_failure_closes_raw_file_and_directory_and_removes_temporary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    closed: list[int] = []
    removed: list[str] = []
    def missing(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError
    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fdopen unavailable")
    fake = SimpleNamespace(O_WRONLY=1, O_CREAT=2, O_EXCL=4, O_NOFOLLOW=8, stat=missing,
                           open=lambda *_args, **_kwargs: 77, fdopen=unavailable, close=closed.append,
                           unlink=lambda name, **_kwargs: removed.append(name))
    monkeypatch.setattr(collector, "_linux", lambda: True)
    monkeypatch.setattr(collector, "_directory", lambda _: 99)
    monkeypatch.setattr(collector, "os", fake)
    with pytest.raises(OSError, match="fdopen unavailable"):
        collector.write_snapshot(str(tmp_path / "snapshot.json"), {})
    assert closed == [77, 99]
    assert len(removed) == 1 and removed[0].startswith(".reachscope-")


def test_zipapp_is_reviewable_deterministic_and_runs_preview_outside_checkout(tmp_path: Path) -> None:
    archive = build_zipapp()
    assert archive == build_zipapp()
    with zipfile.ZipFile(io.BytesIO(archive)) as packed:
        assert len(packed.namelist()) == 7
        assert set(packed.namelist()) == {"__main__.py", *{"reachscope_host_collector/" + name for name in ("__init__.py", "collector.py", "runner.py", "projection.py", "builder.py", "LICENSE")}}
        assert all(name.endswith((".py", "/LICENSE")) for name in packed.namelist())
        assert b"MIT License" in packed.read("reachscope_host_collector/LICENSE")
    executable = tmp_path / "collector.pyz"
    executable.write_bytes(archive)
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"} and not any(part in key.upper() for part in ("API_KEY", "TOKEN", "SECRET"))}
    result = subprocess.run([sys.executable, "-I", str(executable), "--host-id", "host", "--ssh-context", "global", "--output", str(tmp_path / "snapshot.json"), "--preview"], cwd=tmp_path, env=environment, check=False, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout)["collector_version"] == "0.14.0"
    assert not (tmp_path / "snapshot.json").exists()
