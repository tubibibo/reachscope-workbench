"""Explicitly confirmed Linux-only collector, shipped as reviewable source.

The collector does not alter configuration, elevate privileges, reload services
or upload data. System test binaries may access resources referenced by their
configuration and produce their own diagnostic-file side effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .projection import ProjectionUnsupported, project_nginx, project_ssh
from .runner import COMMANDS, STDERR_LIMIT, STDOUT_LIMIT, TIMEOUT_SECONDS, run_component

VERSION = "0.14.0"
PROJECTION = "reachscope-minimal/1"
REASON_CODES = ("ok", "missing_executable", "execution_unavailable", "output_read_failed", "nonzero_exit",
                "command_timeout", "output_budget", "projection_unsupported", "context_unsupported")
MAX_OUTPUT_BYTES = 512 * 1024


class CollectorError(ValueError):
    """Safe fixed operator-facing failure; never includes a subprocess error."""


def _label(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128 or not value.isprintable():
        raise CollectorError("invalid_label")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise CollectorError("invalid_label") from exc
    return value


def plan(host_id: str, ssh_context: str, output: str) -> dict[str, Any]:
    """Return a deterministic plan without touching a command or destination."""
    host_id, ssh_context = _label(host_id), _label(ssh_context)
    if not isinstance(output, str) or not output or len(output) > 4096 or not output.isprintable():
        raise CollectorError("invalid_output")
    absolute_output = str(Path(output).absolute())
    value = {"collector_version": VERSION, "projection": PROJECTION, "host_id": host_id,
             "ssh_context": ssh_context, "output": absolute_output, "platform_required": "linux",
             "commands": {key: list(command) for key, command in COMMANDS.items()},
             "limits": {"command_seconds": TIMEOUT_SECONDS, "stdout_bytes": STDOUT_LIMIT, "stderr_bytes": STDERR_LIMIT},
             "actions": ["run_fixed_configuration_test_binaries", "allowlist_project_in_memory", "create_new_snapshot_0600"],
             "network_upload": False, "automatic_sudo": False, "reload_or_configuration_change": False,
             "limitations": ["系统测试程序会校验配置引用资源，可能访问私钥/诊断日志等，并可能产生其自身文件副作用。",
                             "采集器只保留受支持字段；不能投影的配置保持未知，不发送或保存原始 stdout/stderr。",
                             "Nginx 投影经过稳定别名化，仅供静态复核，不能部署为真实配置。",
                             "标识别名不是不可逆匿名；时间、来源与真实主机身份未经远程认证。"]}
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**value, "plan_sha256": digest}


def _linux() -> bool:
    return sys.platform == "linux" and os.name == "posix"


def collect_snapshot(host_id: str, ssh_context: str, plan_sha256: str) -> dict[str, Any]:
    """Collect fixed commands after the caller validates the full plan hash."""
    _label(host_id)
    _label(ssh_context)
    if not _linux():
        raise CollectorError("linux_required")
    if len(plan_sha256) != 64 or any(char not in "0123456789abcdef" for char in plan_sha256):
        raise CollectorError("invalid_plan")
    result: dict[str, Any] = {"schema_version": "reachscope-host/2", "host_id": host_id,
                              "ssh": {"effective_config": None, "connection_context": ssh_context},
                              "nginx": {"config_dump": None}, "collector": {"version": VERSION, "projection": PROJECTION,
                              "plan_sha256": plan_sha256, "components": {}}}
    for component, projector, key in (("ssh", project_ssh, "effective_config"), ("nginx", project_nginx, "config_dump")):
        if component == "ssh" and ssh_context != "global":
            metadata: dict[str, Any] = {"state": "unsupported", "complete": False, "reason_code": "context_unsupported"}
        else:
            captured = run_component(component)
            metadata = {"state": captured.state, "complete": False, "reason_code": captured.reason_code}
            if captured.exit_code is not None:
                metadata["exit_code"] = captured.exit_code
            if captured.state == "collected" and captured.stdout is not None:
                try:
                    result[component][key] = projector(captured.stdout)
                    metadata.update(state="collected", complete=True, reason_code="ok", exit_code=0)
                except ProjectionUnsupported:
                    metadata.update(state="unsupported", reason_code="projection_unsupported")
        result["collector"]["components"][component] = metadata
    result["collected_at"] = datetime.now(UTC).isoformat()
    return result


def _directory(path: Path) -> int:
    """Open each directory component without following a symbolic link."""
    if not path.is_absolute() or ".." in path.parts:
        raise CollectorError("invalid_output_directory")
    flags = os.O_RDONLY | _flag("O_DIRECTORY") | _flag("O_NOFOLLOW")
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            new = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = new
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int):
        raise CollectorError("linux_required")
    return value


def write_snapshot(output: str, snapshot: dict[str, Any]) -> None:
    """Linux anchored-dirfd, exclusive atomic publish; never overwrite a path."""
    if not _linux():
        raise CollectorError("linux_required")
    target = Path(output).absolute()
    if target.name in {"", ".", ".."}:
        raise CollectorError("invalid_output")
    encoded = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise CollectorError("snapshot_budget")
    directory = _directory(target.parent)
    temporary = ".reachscope-" + secrets.token_hex(16)
    created = False
    try:
        try:
            os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CollectorError("output_exists")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _flag("O_NOFOLLOW"), 0o600, dir_fd=directory)
        created = True
        try:
            stream = os.fdopen(descriptor, "wb")
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.fsync(directory)
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--ssh-context", default="global")
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    try:
        prepared = plan(args.host_id, args.ssh_context, args.output)
        if args.preview and args.collect:
            raise CollectorError("ambiguous_action")
        if not args.collect:
            print(json.dumps(prepared, ensure_ascii=True, indent=2))
            return 0
        if args.plan_sha256 != prepared["plan_sha256"]:
            raise CollectorError("plan_confirmation_required")
        snapshot = collect_snapshot(args.host_id, args.ssh_context, prepared["plan_sha256"])
        write_snapshot(prepared["output"], snapshot)
        print(json.dumps({"status": "exported", "schema_version": snapshot["schema_version"],
                          "components": snapshot["collector"]["components"], "network_upload": False}))
        return 0
    except KeyboardInterrupt:
        print('{"status":"cancelled","reason_code":"operator_cancelled"}', file=sys.stderr)
        return 130
    except CollectorError as exc:
        print(json.dumps({"status": "failed", "reason_code": str(exc)}), file=sys.stderr)
        return 2
    except OSError:
        print('{"status":"failed","reason_code":"output_unavailable"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
