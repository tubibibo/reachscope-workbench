"""Exercise legacy decoder control with harmless local Python, never an APK/JAR."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from reachscope.ingest import apk as apk_module
from reachscope.ingest.apk import IngestError, check_apktool_version, run_apktool


def decoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> list[str]:
    script = tmp_path / "canary_decoder.py"
    script.write_text(body, encoding="utf-8")
    base = [sys.executable, str(script)]
    monkeypatch.setattr(apk_module, "resolve_apktool", lambda _: base)
    return base


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_sec_file_05_version_output_has_an_explicit_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str) -> None:
    base = decoder(tmp_path, monkeypatch, f"import sys; sys.{channel}.write('2.11.1 '+ 'C'*1048576)")
    with pytest.raises(IngestError) as error:
        check_apktool_version(base)
    assert error.value.reason == "apktool output limit"
    assert "CCCC" not in error.value.detail


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_sec_file_05_decode_output_overflow_cannot_be_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str) -> None:
    decoder(tmp_path, monkeypatch, "import sys\nif '-version' in sys.argv: print('2.11.1')\n"
            f"else: sys.{channel}.write('C'*1048576)\n")
    with pytest.raises(IngestError) as error:
        run_apktool(tmp_path / "inert-not-an-actual-apk", tmp_path / "unused-output", timeout=5)
    assert error.value.reason == "apktool output limit"
    assert "CCCC" not in error.value.detail


def test_normal_local_python_version_and_decoder_still_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = decoder(tmp_path, monkeypatch, "import sys\nprint('2.11.1' if '-version' in sys.argv else 'canary decode complete')\n")
    assert check_apktool_version(base) == "2.11.1"
    output = tmp_path / "unused-output"
    assert run_apktool(tmp_path / "inert-input", output, timeout=5) == output


@pytest.mark.skipif(os.name != "nt", reason="this fixture verifies actual Windows Job Object ownership")
@pytest.mark.parametrize("leader_exits", [False, True])
def test_legacy_timeout_reaps_owned_windows_descendant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leader_exits: bool) -> None:
    heartbeat = tmp_path / "canary-heartbeat"
    child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
    child += "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(.03)')"
    body = "import sys,subprocess,time,os\nif '-version' in sys.argv: print('2.11.1')\nelse:\n"
    body += f" subprocess.Popen([sys.executable,'-c',{child!r}])\n time.sleep(.2)\n"
    body += " os._exit(0)\n" if leader_exits else " time.sleep(30)\n"
    decoder(tmp_path, monkeypatch, body)
    start = time.monotonic()
    with pytest.raises(IngestError) as error:
        run_apktool(tmp_path / "inert-input", tmp_path / "unused-output", timeout=1)
    assert error.value.reason == "apktool timeout" and time.monotonic() - start < 5
    assert heartbeat.exists()
    final = heartbeat.read_text()
    time.sleep(.2)
    assert heartbeat.read_text() == final
