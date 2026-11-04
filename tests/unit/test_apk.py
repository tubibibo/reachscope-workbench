"""T1.1 单测：ApkInput 校验、apktool 解析/调用/超时、工作目录。

全部用 monkeypatch 打桩，**不真实调用 apktool**。
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reachscope import exitcodes
from reachscope.exitcodes import ExitCode
from reachscope.ingest import apk as apk_mod
from reachscope.ingest.apk import (
    APKTOOL_JAR_ENV,
    DEFAULT_TIMEOUT,
    ApkInput,
    IngestError,
    WorkDir,
    check_apktool_version,
    manifest_path,
    resolve_apktool,
    run_apktool,
    smali_dirs,
)
from reachscope.ingest.bounded_process import CommandLimitError


class FakeProcess:
    """有界执行端口背后的有限假进程；不会调用真实解码器。"""

    def __init__(
        self,
        cmd: list[str] | None = None,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        timeout_once: bool = False,
    ) -> None:
        self.cmd = cmd or []
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._timeout_once = timeout_once
        self.killed = False
        self.communicate_calls = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_calls += 1
        if self._timeout_once and self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="apktool", timeout=timeout or 0)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class FakeCompleted:
    """替换有界执行端口的返回值。"""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def install_popen(
    monkeypatch: pytest.MonkeyPatch, sink: list[FakeProcess], **behavior: Any
) -> None:
    """给解码执行端口打桩，保留单独的版本检查响应。"""
    version_runner = apk_mod.run_bounded

    def _factory(cmd: list[str], *, timeout: float) -> Any:
        if cmd[-1] == "-version":
            return version_runner(cmd, timeout=timeout)
        process = FakeProcess(cmd=list(cmd), **behavior)
        sink.append(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise CommandLimitError("timeout") from None
        return FakeCompleted(stdout=stdout, stderr=stderr, returncode=process.returncode)

    monkeypatch.setattr(apk_mod, "run_bounded", _factory)


def install_run_ok(monkeypatch: pytest.MonkeyPatch, version: str = "2.9.3") -> None:
    """有界执行端口返回指定版本；不启动本机 apktool。"""
    monkeypatch.setattr(apk_mod, "run_bounded", lambda *a, **k: FakeCompleted(stdout=f"{version}\n"))


@pytest.fixture
def no_apktool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉环境变量，避免本机配置影响用例。"""
    monkeypatch.delenv(APKTOOL_JAR_ENV, raising=False)


# --- ApkInput -------------------------------------------------------------


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(tmp_path / "nope.apk")
    assert excinfo.value.reason == "file not found"
    assert excinfo.value.exit_code == ExitCode.INPUT_ERROR


def test_load_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(tmp_path)
    assert excinfo.value.reason == "not a regular file"
    assert excinfo.value.exit_code == ExitCode.INPUT_ERROR


def test_load_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.apk"
    empty.write_bytes(b"")
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(empty)
    assert excinfo.value.reason == "not a zip archive"


def test_load_rejects_non_zip(tmp_path: Path) -> None:
    text = tmp_path / "notes.apk"
    text.write_text("hello", encoding="utf-8")
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(text)
    assert excinfo.value.reason == "not a zip archive"


def test_load_rejects_zip_without_android_manifest(make_apk: Callable[..., Path]) -> None:
    """D-017：只有 zip 形态还不够，必须含顶层 AndroidManifest.xml。"""
    apk = make_apk({"classes.dex": b"dex\n035\x00", "res/x.xml": b"<x />"})
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(apk)
    assert excinfo.value.reason == "missing AndroidManifest.xml in archive"
    assert excinfo.value.exit_code == ExitCode.INPUT_ERROR


def test_load_rejects_manifest_in_subdirectory(make_apk: Callable[..., Path]) -> None:
    """只认顶层条目，子目录同名不算。"""
    apk = make_apk({"app/AndroidManifest.xml": b"<manifest />"})
    with pytest.raises(IngestError) as excinfo:
        ApkInput.load(apk)
    assert excinfo.value.reason == "missing AndroidManifest.xml in archive"


def test_load_rejects_truncated_archive(tmp_path: Path) -> None:
    """损坏的 zip 必须转成 IngestError，不能抛出其他异常。"""
    broken = tmp_path / "broken.apk"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(IngestError):
        ApkInput.load(broken)


def test_load_accepts_minimal_apk(make_apk: Callable[..., Path]) -> None:
    apk_path = make_apk()
    apk = ApkInput.load(apk_path)
    assert apk.path == apk_path
    assert apk.size == apk_path.stat().st_size
    assert apk.sha256 == hashlib.sha256(apk_path.read_bytes()).hexdigest()
    assert len(apk.sha256) == 64
    assert apk.name == apk_path.name


def test_sha256_is_stable_across_loads(make_apk: Callable[..., Path]) -> None:
    apk_path = make_apk()
    assert ApkInput.load(apk_path).sha256 == ApkInput.load(apk_path).sha256


# --- resolve_apktool ------------------------------------------------------


def test_resolve_apktool_prefers_explicit_executable() -> None:
    assert resolve_apktool("C:/tools/apktool.bat") == ["C:/tools/apktool.bat"]


def test_resolve_apktool_wraps_jar_with_java() -> None:
    assert resolve_apktool("C:/tools/apktool.jar") == ["java", "-jar", "C:/tools/apktool.jar"]


def test_resolve_apktool_falls_back_to_env_jar(
    monkeypatch: pytest.MonkeyPatch, no_apktool_env: None
) -> None:
    monkeypatch.setenv(APKTOOL_JAR_ENV, "C:/tools/apktool.jar")
    assert resolve_apktool() == ["java", "-jar", "C:/tools/apktool.jar"]


def test_resolve_apktool_falls_back_to_path(
    monkeypatch: pytest.MonkeyPatch, no_apktool_env: None
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/apktool")
    assert resolve_apktool() == ["/usr/local/bin/apktool"]


def test_resolve_apktool_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, no_apktool_env: None
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(IngestError) as excinfo:
        resolve_apktool()
    assert excinfo.value.reason == "apktool not found"
    assert "--apktool" in excinfo.value.detail
    assert excinfo.value.exit_code == ExitCode.INPUT_ERROR


def test_explicit_apktool_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APKTOOL_JAR_ENV, "C:/env/apktool.jar")
    assert resolve_apktool("C:/cli/apktool") == ["C:/cli/apktool"]


# --- check_apktool_version ------------------------------------------------


def test_version_check_accepts_minimum(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install_run_ok(monkeypatch, "2.9.0")
    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.apk"):
        assert check_apktool_version(["apktool"]) == "2.9.0"
    assert caplog.records == []


def test_version_check_warns_on_older_version(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install_run_ok(monkeypatch, "2.7.0")
    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.apk"):
        assert check_apktool_version(["apktool"]) == "2.7.0"
    assert any("低于要求" in record.message for record in caplog.records)


def test_version_check_warns_when_unparsable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(apk_mod, "run_bounded", lambda *a, **k: FakeCompleted(stdout="???\n"))
    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.apk"):
        assert check_apktool_version(["apktool"]) is None
    assert any("无法解析" in record.message for record in caplog.records)


def test_version_check_warns_when_command_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> FakeCompleted:
        raise CommandLimitError("timeout")

    monkeypatch.setattr(apk_mod, "run_bounded", _raise)
    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.apk"):
        assert check_apktool_version(["apktool"]) is None
    assert any("无法获取" in record.message for record in caplog.records)


# --- run_apktool ----------------------------------------------------------


def test_run_apktool_returns_workdir_on_success(
    make_apk: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    install_run_ok(monkeypatch)
    install_popen(monkeypatch, processes)
    workdir = tmp_path / "work"
    assert run_apktool(make_apk(), workdir, apktool="apktool") == workdir
    assert len(processes) == 1


def test_run_apktool_passes_decode_arguments(
    make_apk: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    install_run_ok(monkeypatch)
    install_popen(monkeypatch, processes)
    workdir = tmp_path / "work"
    apk = make_apk()
    run_apktool(apk, workdir, apktool="apktool")
    assert processes[0].cmd == ["apktool", "d", "-f", "-o", str(workdir), str(apk)]


def test_run_apktool_raises_on_nonzero_exit(
    make_apk: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    install_run_ok(monkeypatch)
    install_popen(monkeypatch, processes, returncode=1, stderr="boom")
    with pytest.raises(IngestError) as excinfo:
        run_apktool(make_apk(), tmp_path / "work", apktool="apktool")
    assert excinfo.value.reason == "apktool failed"
    assert "boom" in excinfo.value.detail


def test_run_apktool_kills_process_on_timeout(
    make_apk: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    install_run_ok(monkeypatch)
    install_popen(monkeypatch, processes, timeout_once=True, stdout="partial")
    with pytest.raises(IngestError) as excinfo:
        run_apktool(make_apk(), tmp_path / "work", apktool="apktool", timeout=1)
    assert excinfo.value.reason == "apktool timeout"
    assert processes[0].killed is True


def test_run_apktool_raises_when_apktool_missing(
    make_apk: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(APKTOOL_JAR_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(IngestError) as excinfo:
        run_apktool(make_apk(), tmp_path / "work")
    assert excinfo.value.reason == "apktool not found"


# --- WorkDir --------------------------------------------------------------


def test_workdir_is_cleaned_up() -> None:
    with WorkDir() as path:
        assert path.is_dir()
        (path / "marker.txt").write_text("x", encoding="utf-8")
    assert not path.exists()


def test_workdir_is_kept_when_requested(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="reachscope.ingest.apk"), WorkDir(keep=True) as path:
        kept = path
        assert kept.is_dir()
    assert kept.exists()
    assert any("保留工作目录" in record.message for record in caplog.records)
    shutil.rmtree(kept, ignore_errors=True)


def test_workdir_path_before_enter_raises() -> None:
    with pytest.raises(RuntimeError):
        _ = WorkDir().path


# --- 产物路径约定 ---------------------------------------------------------


def test_manifest_path(tmp_path: Path) -> None:
    assert manifest_path(tmp_path) == tmp_path / "AndroidManifest.xml"


def test_smali_dirs_are_sorted_and_multidex(tmp_path: Path) -> None:
    for name in ("smali_classes3", "smali", "smali_classes2"):
        (tmp_path / name).mkdir()
    (tmp_path / "res").mkdir()
    assert [path.name for path in smali_dirs(tmp_path)] == [
        "smali",
        "smali_classes2",
        "smali_classes3",
    ]


def test_smali_dirs_empty_when_absent(tmp_path: Path) -> None:
    assert smali_dirs(tmp_path) == []


# --- 其他 -----------------------------------------------------------------


def test_ingest_error_message_without_detail() -> None:
    assert IngestError("boom").to_message() == "boom"
    assert IngestError("boom", "detail").to_message() == "boom — detail"


def test_default_timeout_matches_spec() -> None:
    """PLAN §9.2：apktool 默认超时 300s。"""
    assert DEFAULT_TIMEOUT == 300


def test_minimal_apk_fixture_really_is_a_zip(make_apk: Callable[..., Path]) -> None:
    with zipfile.ZipFile(make_apk()) as archive:
        assert "AndroidManifest.xml" in archive.namelist()


def test_ingest_uses_shared_exit_codes() -> None:
    """D-018：ExitCode 来自 exitcodes 模块，ingest 不依赖 cli。"""
    assert apk_mod.ExitCode is exitcodes.ExitCode
