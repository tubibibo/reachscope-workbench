"""Reject dangerous or oversized archives before invoking an external decoder."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from reachscope.ingest import apk as module
from reachscope.ingest.apk import ApkInput, IngestError


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "dir\\escape"])
def test_archive_paths_are_rejected(tmp_path: Path, name: str) -> None:
    path = tmp_path / "bad.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", "manifest")
        entry = zipfile.ZipInfo("placeholder")
        entry.filename = name  # Preserve malicious backslashes even on Windows writers.
        archive.writestr(entry, "bad")
    with pytest.raises(IngestError, match="unsafe archive"):
        ApkInput.load(path)


def test_zip_link_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.apk"
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", "manifest")
        archive.writestr(info, "outside")
    with pytest.raises(IngestError, match="unsafe archive"):
        ApkInput.load(path)


def test_expansion_budget_precedes_decoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "large.apk"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", "x" * 4096)
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 1024)
    with pytest.raises(IngestError, match="expanded size"):
        ApkInput.load(path)


def test_file_count_and_input_budgets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "many.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", "manifest")
        archive.writestr("classes.dex", "dex")
    monkeypatch.setattr(module, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(IngestError, match="Too many"):
        ApkInput.load(path)
    monkeypatch.setattr(module, "MAX_APK_BYTES", 1)
    with pytest.raises(IngestError, match="input budget"):
        ApkInput.load(path)
