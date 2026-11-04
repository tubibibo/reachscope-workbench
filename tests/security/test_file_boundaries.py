"""Harmless file-boundary regressions: no target APK execution or real accounts."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from reachscope.ingest import apk as apk_module
from reachscope.ingest.apk import ApkInput, IngestError
from reachscope.ingest.manifest import parse_manifest
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.modules.android import code_worker, manifest_worker
from reachscope_workbench.modules.android.manifest_worker import inspect_manifest
from reachscope_workbench.modules.android.posture import inspect_security_review
from reachscope_workbench.modules.cloud.input import parse_input

NS = "http://schemas.android.com/apk/res/android"


def ambiguous_plan(marker: dict[str, Any]) -> dict[str, Any]:
    return {"format_version": "1.2", "planned_values": {"root_module": {"resources": [
        {"address": "aws_iam_policy.fixture", "type": "aws_iam_policy", "name": "fixture", "values": {
            "policy": {"Statement": [{"Effect": "Allow", "Action": "FILE_REVIEW_CANARY_ACTION", "Resource": "*"}]}}}]}},
        "resource_changes": [{"address": "aws_iam_policy.fixture", "change": marker},
                             {"address": "aws_iam_policy.fixture", "change": {}}]}


@pytest.mark.parametrize("marker", [{"after_sensitive": {"policy": True}}, {"after_unknown": {"policy": True}}])
def test_sec_file_01_duplicate_change_identity_cannot_erase_markers(marker: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError) as error:
        parse_input(json.dumps(ambiguous_plan(marker)).encode())
    assert error.value.code == "INVALID_CLOUD_INPUT"
    assert "FILE_REVIEW_CANARY_ACTION" not in str(error.value)


@pytest.mark.parametrize("singleton", ["application", "uses-sdk"])
@pytest.mark.parametrize("parser", [parse_manifest, inspect_manifest, inspect_security_review])
def test_sec_file_02_ambiguous_manifest_singletons_are_rejected(tmp_path: Path, singleton: str, parser: Any) -> None:
    content = ("<application android:debuggable=\"false\"/><application android:debuggable=\"true\"/>" if singleton == "application" else
               '<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="30"/>'
               '<uses-sdk android:minSdkVersion="16" android:targetSdkVersion="22"/><application/>')
    path = tmp_path / "AndroidManifest.xml"
    path.write_text(f'<manifest xmlns:android="{NS}" package="canary.fixture">{content}</manifest>', encoding="utf-8")
    with pytest.raises(IngestError):
        parser(path)


@pytest.mark.parametrize("names", [
    ("AndroidManifest.xml", "androidmanifest.xml"),
    ("res/xml/config.xml", "RES/xml/config.xml"),
    ("res/xml/config.xml", "res/xml/config.xml."),
    ("assets/CON",), ("assets/NUL.txt",), ("assets/COM1.txt",),
    ("assets/a/first.txt", "assets/A/second.txt"),
    ("assets/file", "assets/file/child"),
    ("assets/./file",), ("assets//file",), ("assets/file ",),
    ("/absolute",), ("../outside",), ("assets/../outside",),
    ("assets/LPT¹.txt",), ("assets/CONOUT$",),
    ("assets/a\x01b",), ("assets/a:b",),
    ("assets/" + "x" * 4097,), ("assets/" + "nested/" * 65 + "file",),
])
def test_sec_file_03_platform_aliased_archive_names_never_reach_decoder(tmp_path: Path, names: tuple[str, ...]) -> None:
    path = tmp_path / "synthetic.apk"
    with zipfile.ZipFile(path, "w") as archive:
        if "AndroidManifest.xml" not in names:
            archive.writestr("AndroidManifest.xml", b"<manifest/>")
        for index, name in enumerate(names):
            archive.writestr(name, "canary-" + str(index))
    with pytest.raises(IngestError):
        ApkInput.load(path)


def test_zip_portable_names_preserve_regular_directory_entries(tmp_path: Path) -> None:
    path = tmp_path / "regular.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest/>")
        archive.writestr("res/", b"")
        archive.writestr("res/xml/", b"")
        archive.writestr("res/xml/safe.xml", "<network-security-config/>")
        archive.writestr("res/xml/other.xml", "<network-security-config/>")
        archive.writestr("assets/合法名称.txt", "canary")
    assert ApkInput.load(path).size == path.stat().st_size


def test_archive_path_tree_has_a_node_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "bounded.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest/>")
        archive.writestr("a/b/c/d/e", "canary")
    monkeypatch.setattr(apk_module, "MAX_ARCHIVE_PATH_NODES", 3)
    with pytest.raises(IngestError) as error:
        ApkInput.load(path)
    assert error.value.reason == "input limit"


@pytest.mark.parametrize("worker", [manifest_worker, code_worker])
def test_sec_file_04_unused_decoder_output_cannot_fill_a_worker_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], worker: Any) -> None:
    apk = tmp_path / "input.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest/>")
    output = tmp_path / "output"
    argv = ["canary-worker", "--apk", str(apk), "--output", str(output)] if worker is manifest_worker else [
        "canary-worker", str(apk), "--out", str(output), "--store", str(tmp_path / "store"), "--no-apkid"]
    monkeypatch.setattr(worker.sys, "argv", argv)
    monkeypatch.setattr(worker, "resolve_apktool", lambda _: ["CANARY_DECODER_NOT_EXECUTED"])
    if worker is code_worker:
        monkeypatch.setattr(worker, "check_apktool_version", lambda _: None)
    destinations: list[Any] = []
    def fake_run(command: list[str], **kwargs: Any) -> Any:
        destinations.append(kwargs["stdout"])
        assert command[0] == "CANARY_DECODER_NOT_EXECUTED"
        return type("Failure", (), {"returncode": 1})()
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker.main() == 2
    assert destinations == [worker.subprocess.DEVNULL]
    assert "CANARY_DECODER_NOT_EXECUTED" not in capsys.readouterr().err
