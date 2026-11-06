"""协议 CLI：`verify` / `questions` 的输入输出与退出码。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reachscope.cli import ExitCode, main

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples" / "protocol"


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_questions_prints_pure_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["questions", "--report", str(GOLDEN / "09_origin_check_before_load.json")]
    )
    captured = capsys.readouterr()
    assert code == ExitCode.OK
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "0.2"
    assert payload["questions"][0]["code"] == "NEGATIVE_NOT_DEFINITIVE"


def test_verify_stdout_is_utf8_bytes(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    """Windows 重定向默认 GBK；协议输出必须按 UTF-8 编码，Agent 才能解析。"""
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "01_positive_deeplink_bridge_sink.json"),
            "--claim",
            str(EXAMPLES / "claims" / "supported.json"),
        ]
    )
    raw = capsysbinary.readouterr().out
    assert code == ExitCode.OK
    payload = json.loads(raw.decode("utf-8"))
    assert payload["status"] == "SUPPORTED"
    assert any(item["description"] for item in payload["evidence"])


def test_verify_supported_is_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "01_positive_deeplink_bridge_sink.json"),
            "--claim",
            str(EXAMPLES / "claims" / "supported.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == ExitCode.OK
    assert json.loads(captured.out)["status"] == "SUPPORTED"


def test_verify_refuted_is_still_exit_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "02_signature_permission.json"),
            "--claim",
            str(EXAMPLES / "claims" / "refuted_permission.json"),
        ]
    )
    assert code == ExitCode.OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "REFUTED"
    assert payload["reason_code"] == "NOT_ZERO_PERMISSION"


@pytest.mark.parametrize("target", ["report", "claim", "answers"])
def test_verify_non_utf8_files_are_input_errors(
    target: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.json"
    claim = tmp_path / "claim.json"
    answers = tmp_path / "answers.json"
    report.write_bytes((GOLDEN / "01_positive_deeplink_bridge_sink.json").read_bytes())
    claim.write_bytes((EXAMPLES / "claims" / "supported.json").read_bytes())
    answers.write_bytes(b'{"schema_version":"0.1","answers":[]}')
    {"report": report, "claim": claim, "answers": answers}[target].write_bytes(
        '{"note":"中文"}'.encode("gbk")
    )
    code = main([
        "verify", "--report", str(report), "--claim", str(claim), "--answers", str(answers),
    ])
    captured = capsys.readouterr()
    assert code == ExitCode.INPUT_ERROR
    assert "不是 UTF-8" in captured.err
    assert "INTERNAL_ERROR" not in captured.err


def test_verify_with_answers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    answers = _write(
        tmp_path / "answers.json",
        {
            "schema_version": "0.1",
            "answers": [{"question_id": "858db094", "value": "false"}],
        },
    )
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "09_origin_check_before_load.json"),
            "--claim",
            str(EXAMPLES / "claims" / "blocked_deeplink.json"),
            "--answers",
            str(answers),
        ]
    )
    assert code == ExitCode.OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["assumptions_used"] == ["answer:858db094"]


def test_verify_unknown_answer_question_is_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = _write(
        tmp_path / "answers.json",
        {"answers": [{"question_id": "00000000", "value": "false"}]},
    )
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "01_positive_deeplink_bridge_sink.json"),
            "--claim",
            str(EXAMPLES / "claims" / "supported.json"),
            "--answers",
            str(answers),
        ]
    )
    assert code == ExitCode.INPUT_ERROR
    assert "不存在的问题" in capsys.readouterr().err


def test_verify_invalid_claim_is_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claim = _write(tmp_path / "claim.json", {"kind": "reachability"})
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "01_positive_deeplink_bridge_sink.json"),
            "--claim",
            str(claim),
        ]
    )
    assert code == ExitCode.INPUT_ERROR
    assert "输入错误" in capsys.readouterr().err


def test_verify_bad_answers_json_is_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text("{", encoding="utf-8")
    code = main(
        [
            "verify",
            "--report",
            str(GOLDEN / "01_positive_deeplink_bridge_sink.json"),
            "--claim",
            str(EXAMPLES / "claims" / "supported.json"),
            "--answers",
            str(answers),
        ]
    )
    assert code == ExitCode.INPUT_ERROR
    assert "合法 JSON" in capsys.readouterr().err


def test_verify_missing_report_is_input_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "verify",
            "--report",
            "does-not-exist.json",
            "--claim",
            str(EXAMPLES / "claims" / "supported.json"),
        ]
    )
    assert code == ExitCode.INPUT_ERROR
    assert "报告不存在" in capsys.readouterr().err


def test_questions_out_writes_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / "questions.json"
    code = main(
        [
            "questions",
            "--report",
            str(GOLDEN / "09_origin_check_before_load.json"),
            "--out",
            str(target),
        ]
    )
    captured = capsys.readouterr()
    assert code == ExitCode.OK
    assert captured.out == ""
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["questions"]


def test_protocol_subcommands_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--help"])
    assert excinfo.value.code == 0
    with pytest.raises(SystemExit) as excinfo:
        main(["questions", "--help"])
    assert excinfo.value.code == 0
