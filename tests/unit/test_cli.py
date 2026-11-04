"""CLI 测试：参数解析、退出码、stdout/stderr 分流、scan 管线接线（T4.3）。

输入校验统一走 `ApkInput`（T1.1），CLI 只做 `IngestError → ExitCode` 映射。
apktool 解码被替换成 fixture 目录；apkid 不安装（走“未检测”分支，不影响判定）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from reachscope import __version__
from reachscope.cli import ExitCode, main

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"


@pytest.fixture
def decoded_case(monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 apktool 解码替换成直接返回 fixture 目录（不依赖本机 apktool）。"""
    from reachscope import cli as cli_mod

    case = CASES / "01_positive_deeplink_bridge_sink"
    monkeypatch.setattr(cli_mod, "resolve_apktool", lambda explicit=None: ["apktool"])
    monkeypatch.setattr(cli_mod, "check_apktool_version", lambda base, timeout=30: "2.11.1")

    def fake_run_apktool(
        apk: object, workdir: object, *, apktool: str | None = None, timeout: int = 300
    ) -> Path:
        return case

    monkeypatch.setattr(cli_mod, "run_apktool", fake_run_apktool)
    return case


def test_version_outputs_plain_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == ExitCode.OK
    assert capsys.readouterr().out.strip() == __version__
    assert __version__.count(".") == 2


def test_scan_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["scan", "--help"])
    assert excinfo.value.code == 0


def test_scan_missing_file_returns_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.apk"
    assert main(["scan", str(missing)]) == ExitCode.INPUT_ERROR
    assert "file not found" in capsys.readouterr().err


def test_scan_nonexistent_absolute_path_returns_input_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["scan", "/nonexistent"]) == ExitCode.INPUT_ERROR
    assert "file not found" in capsys.readouterr().err


def test_scan_empty_file_returns_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.apk"
    empty.write_bytes(b"")
    assert main(["scan", str(empty)]) == ExitCode.INPUT_ERROR
    assert "not a zip archive" in capsys.readouterr().err


def test_scan_non_zip_text_file_returns_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = tmp_path / "text.apk"
    text.write_text("not a zip at all", encoding="utf-8")
    assert main(["scan", str(text)]) == ExitCode.INPUT_ERROR
    assert "not a zip archive" in capsys.readouterr().err


def test_scan_zip_without_manifest_returns_input_error(
    make_apk: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """D-017：普通 zip 不能混过去，必须含 `AndroidManifest.xml`。"""
    plain_zip = make_apk({"classes.dex": b"dex\n035\x00", "res/values.xml": b"<resources />"})
    assert main(["scan", str(plain_zip)]) == ExitCode.INPUT_ERROR
    assert "missing AndroidManifest.xml" in capsys.readouterr().err


def test_scan_directory_returns_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["scan", str(tmp_path)]) == ExitCode.INPUT_ERROR
    assert "not a regular file" in capsys.readouterr().err


def test_scan_valid_apk_returns_ok_and_single_stdout_line(
    make_apk: Callable[..., Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decoded_case: Path,
) -> None:
    del decoded_case
    apk = make_apk()
    out_dir = tmp_path / "out"
    assert main(["scan", str(apk), "--out", str(out_dir)]) == ExitCode.OK

    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 1
    assert captured.out.startswith("scanned com.example.app: 1 findings, 0 counter-examples")
    assert str(out_dir) in captured.out

    assert (out_dir / "report.json").is_file()
    assert (out_dir / "report.html").is_file()


def test_scan_format_json_only(
    make_apk: Callable[..., Path], tmp_path: Path, decoded_case: Path
) -> None:
    del decoded_case
    out_dir = tmp_path / "out"
    assert main(["scan", str(make_apk()), "--out", str(out_dir), "--format", "json"]) == ExitCode.OK
    assert (out_dir / "report.json").is_file()
    assert not (out_dir / "report.html").exists()


def test_scan_refuses_to_mix_new_reports_with_existing_artifact_pointer(
    make_apk: Callable[..., Path], tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "previous-run"
    out_dir.mkdir()
    pointer = out_dir / "artifact.json"
    pointer.write_text('{"artifact_id":"previous-input"}', encoding="utf-8")
    assert main([
        "scan", str(make_apk()), "--out", str(out_dir), "--no-artifacts",
    ]) == ExitCode.INPUT_ERROR
    assert "new or empty" in capsys.readouterr().err
    assert pointer.read_text(encoding="utf-8") == '{"artifact_id":"previous-input"}'
    assert not (out_dir / "report.json").exists()


def test_scan_min_exploitability_filters_findings_only(
    make_apk: Callable[..., Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    decoded_case: Path,
) -> None:
    """PLAN §7：阈值只影响 findings 列表；链与反例照常输出。"""
    del decoded_case
    from reachscope import cli as cli_mod
    from reachscope.ir.model import Finding, Level, Report

    def fake_analyze(*_args: object, **_kwargs: object) -> Report:
        return Report(
            findings=[
                Finding(chain_id="a", title="medium", exploitability=Level.MEDIUM),
                Finding(chain_id="b", title="high", exploitability=Level.HIGH),
            ]
        )

    monkeypatch.setattr(cli_mod, "analyze_workdir", fake_analyze)
    out_dir = tmp_path / "out"
    assert (
        main(
            [
                "scan",
                str(make_apk()),
                "--out",
                str(out_dir),
                "--min-exploitability",
                "high",
            ]
        )
        == ExitCode.OK
    )
    assert "1 findings" in capsys.readouterr().out
    import json

    data = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert [finding["title"] for finding in data["findings"]] == ["high"]


def test_scan_rejects_unknown_format(
    make_apk: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    apk = make_apk()
    assert main(["scan", str(apk), "--format", "pdf"]) == ExitCode.INPUT_ERROR
    assert "--format 取值非法" in capsys.readouterr().err


def test_scan_short_circuits_on_unanalyzable_protection(
    make_apk: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T1.4 验收：强加固 → 主流程短路，退出码 3，不产出一行摘要冒充完成。"""
    from reachscope import cli as cli_mod
    from reachscope.ir.model import Protection

    monkeypatch.setattr(
        cli_mod,
        "detect_protection",
        lambda _path, no_apkid=False: Protection(
            detected=True, tool="apkid", labels=["packer::dexguard"], analyzable=False
        ),
    )
    assert main(["scan", str(make_apk())]) == ExitCode.UNANALYZABLE
    captured = capsys.readouterr()
    assert "无法分析" in captured.err
    assert "packer::dexguard" in captured.err
    assert captured.out == ""


def test_scan_quiet_suppresses_info_log(
    make_apk: Callable[..., Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decoded_case: Path,
) -> None:
    del decoded_case
    apk = make_apk()
    assert main(["scan", str(apk), "--quiet", "--out", str(tmp_path / "out")]) == ExitCode.OK
    assert capsys.readouterr().err == ""


def test_rules_list_prints_six_judgments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules", "list"]) == ExitCode.OK
    out = capsys.readouterr().out
    for name in ("J1", "J2", "J3", "J4", "J5", "J6"):
        assert name in out


def test_explain_missing_report_returns_input_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "report.json", "chain-1"]) == ExitCode.INPUT_ERROR
    assert "报告不存在" in capsys.readouterr().err


def test_explain_unknown_chain_returns_input_error(
    make_apk: Callable[..., Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decoded_case: Path,
) -> None:
    del decoded_case
    out_dir = tmp_path / "out"
    assert main(["scan", str(make_apk()), "--out", str(out_dir), "--quiet"]) == ExitCode.OK
    capsys.readouterr()
    report = out_dir / "report.json"
    assert main(["explain", str(report), "deadbeef"]) == ExitCode.INPUT_ERROR
    assert "报告里没有链 deadbeef" in capsys.readouterr().err


def test_explain_prints_chain_evidence(
    make_apk: Callable[..., Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decoded_case: Path,
) -> None:
    del decoded_case
    out_dir = tmp_path / "out"
    assert main(["scan", str(make_apk()), "--out", str(out_dir), "--quiet"]) == ExitCode.OK
    capsys.readouterr()

    import json

    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    chain_id = report["findings"][0]["chain_id"]

    assert main(["explain", str(out_dir / "report.json"), chain_id]) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"chain {chain_id}" in out
    assert "rank: exploitability=high" in out
    assert "steps:" in out
    assert "judgments:" in out
    assert "finding:" in out


def test_unknown_command_fails() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["nope"])
    assert excinfo.value.code == 2


def test_python_m_module_entry_point() -> None:
    """`python -m reachscope version` 与 console script 等价（README 上手路径）。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "reachscope", "version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == ExitCode.OK
    assert result.stdout.strip() == __version__
