"""Version negotiation at persisted report boundaries must fail explicitly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reachscope.ir.model import Meta, Report
from reachscope.ir.serialize import IRDeserializeError
from reachscope.report.json_report import load_json, write_json


def test_supported_old_report_schema_remains_readable(tmp_path: Path) -> None:
    report = Report(meta=Meta(package="com.example.app", tool_version="0.1.0"))
    path = write_json(report, tmp_path / "report.json")
    assert load_json(path) == report


@pytest.mark.parametrize("version", ["0.2", "1.0", "future", 0.1, None, {}, True])
def test_unknown_report_version_is_rejected(tmp_path: Path, version: object) -> None:
    payload = Report().to_dict()
    payload["schema_version"] = version
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IRDeserializeError, match="schema_version"):
        load_json(path)


def test_unversioned_report_is_not_silently_interpreted(tmp_path: Path) -> None:
    payload = Report().to_dict()
    del payload["schema_version"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IRDeserializeError, match="Regenerate unversioned"):
        load_json(path)
