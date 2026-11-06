"""Upload consumers accept only the opened regular file, never a symlink target."""

from __future__ import annotations

from pathlib import Path

import pytest

from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.uploads import read_upload
from reachscope_workbench.modules.cloud.module import _read as read_cloud
from reachscope_workbench.modules.host.module import _input as read_host


def test_regular_upload_is_read_and_size_limit_is_kept(tmp_path: Path) -> None:
    path = tmp_path / ("a" * 32)
    path.write_bytes(b"valid")
    assert read_host(tmp_path, path.name) == b"valid"
    assert read_cloud(path) == b"valid"
    with pytest.raises(WorkbenchError) as caught:
        read_upload(path, max_bytes=2, missing_message="missing", limit_code="LIMIT", limit_message="large")
    assert caught.value.code == "LIMIT"


def test_host_and_cloud_reject_upload_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_bytes(b"{}")
    link = tmp_path / ("b" * 32)
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    for operation in (lambda: read_host(tmp_path, link.name), lambda: read_cloud(link)):
        with pytest.raises(WorkbenchError) as caught:
            operation()
        assert caught.value.code == "UPLOAD_NOT_FOUND"


def test_directory_is_not_an_upload(tmp_path: Path) -> None:
    path = tmp_path / "directory"
    path.mkdir()
    with pytest.raises(WorkbenchError) as caught:
        read_upload(path, max_bytes=100, missing_message="missing", limit_code="LIMIT", limit_message="large")
    assert caught.value.code == "UPLOAD_NOT_FOUND"
