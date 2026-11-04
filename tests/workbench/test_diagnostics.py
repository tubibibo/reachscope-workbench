"""Startup diagnostics must remain local, truthful and side-effect free."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from reachscope_workbench.diagnostics import _frontend_ready, inspect_readiness


def bundle(root: Path, html: str = '<script src="/assets/app.js"></script>') -> Path:
    static = root / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(html, encoding="utf-8")
    (static / "assets/app.js").write_text("export {};", encoding="utf-8")
    return static


def test_missing_optional_apk_tools_do_not_block_first_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    static = bundle(tmp_path)
    monkeypatch.delenv("APKTOOL_JAR", raising=False)
    monkeypatch.setenv("REACHSCOPE_AI_API_KEY", "must-not-be-read-or-returned")
    with patch("reachscope_workbench.diagnostics.shutil.which", return_value=None):
        report = inspect_readiness(tmp_path / "new/workspace", static_dir=static)
    assert report["ready"] and not report["network_contacted"] and not report["workspace_modified"]
    assert [item["id"] for item in report["checks"] if item["status"] == "optional"] == ["java", "apktool"]
    assert "must-not-be-read-or-returned" not in json.dumps(report)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("reference", ["/assets/missing.js", "../outside.js", "https://cdn.example/app.js", "//cdn.example/app.js", "/%2e%2e/outside.js"])
def test_missing_remote_or_escaping_bundle_is_not_ready(tmp_path: Path, reference: str) -> None:
    static = bundle(tmp_path, f'<script src="{reference}"></script>')
    (tmp_path / "outside.js").write_text("export {};", encoding="utf-8")
    assert not _frontend_ready(static)
    report = inspect_readiness(tmp_path / "workspace", static_dir=static)
    assert not report["ready"]
    assert next(item for item in report["checks"] if item["id"] == "frontend")["status"] == "blocked"


def test_workspace_file_and_invalid_optional_jar_are_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    static = bundle(tmp_path)
    occupied = tmp_path / "occupied"
    occupied.write_bytes(b"do not modify")
    monkeypatch.setenv("APKTOOL_JAR", str(occupied))
    report = inspect_readiness(occupied / "nested", static_dir=static)
    assert not report["ready"]
    assert next(item for item in report["checks"] if item["id"] == "workspace")["status"] == "blocked"
    assert next(item for item in report["checks"] if item["id"] == "apktool")["status"] == "optional"
    assert occupied.read_bytes() == b"do not modify"


def test_stylesheet_without_application_entry_does_not_report_ready(tmp_path: Path) -> None:
    static = bundle(tmp_path, '<link rel="stylesheet" href="/assets/app.css">')
    (static / "assets/app.css").write_text("body { margin: 0; }", encoding="utf-8")
    assert not inspect_readiness(tmp_path / "workspace", static_dir=static)["ready"]


@pytest.mark.parametrize("encoding", ["utf-8", "ascii"])
def test_doctor_cli_json_does_not_start_server_or_create_workspace(tmp_path: Path, encoding: str) -> None:
    data = tmp_path / "untouched"
    result = subprocess.run([sys.executable, "-m", "reachscope_workbench", "doctor", "--json", "--data", str(data)],
                            capture_output=True, text=True, encoding=encoding, env={**os.environ, "PYTHONIOENCODING": encoding}, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ready"] and not payload["network_contacted"] and not payload["workspace_modified"]
    assert not data.exists()
