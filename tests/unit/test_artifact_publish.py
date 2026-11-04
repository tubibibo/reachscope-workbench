"""Publication tolerates bounded Win32 handle races without weakening integrity."""

from __future__ import annotations

import errno
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reachscope.artifacts import ArtifactError, ArtifactStore
from reachscope.artifacts import store as storage
from reachscope.ir.model import Meta, Report


def _winerror(code: int) -> PermissionError:
    error = PermissionError(errno.EACCES, "simulated Windows publish denial")
    error.winerror = code  # type: ignore[attr-defined]
    return error


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Report]:
    decoded = tmp_path / "decoded"
    source = decoded / "smali" / "example" / "Entry.smali"
    source.parent.mkdir(parents=True)
    source.write_text(""".class public Lexample/Entry;
.super Ljava/lang/Object;
.method public open()V
    .locals 0
    return-void
.end method
""", encoding="utf-8")
    (decoded / "AndroidManifest.xml").write_text(
        '<manifest package="example"><application/></manifest>', encoding="utf-8",
    )
    return decoded, Report(meta=Meta(package="example", tool_version="test"))


def _assert_clean(store: ArtifactStore) -> None:
    assert not list(store.root.glob(".staging-*"))


@pytest.mark.parametrize("code", [5, 32, 33])
def test_windows_transient_permission_race_retries_atomic_publish_once(
    tmp_path: Path, inputs: tuple[Path, Report], monkeypatch: pytest.MonkeyPatch, code: int,
) -> None:
    original = Path.rename
    attempts: list[Path] = []
    delays: list[float] = []

    def rename(stage: Path, target: Any) -> Path:
        attempts.append(stage)
        if len(attempts) == 1:
            raise _winerror(code)
        return original(stage, target)

    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(storage.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "rename", rename)
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(*inputs)
    assert len(attempts) == 2 and delays == [0.05]
    assert store.open(artifact.id).read_method("Lexample/Entry;->open()V")["code"].endswith(".end method")
    assert len(store.list()) == 1
    _assert_clean(store)


def test_persistent_windows_publish_denial_is_bounded_and_cleans_stage(
    tmp_path: Path, inputs: tuple[Path, Report], monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[Path] = []
    delays: list[float] = []

    def denied(stage: Path, _target: Any) -> Path:
        attempts.append(stage)
        raise _winerror(5)

    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(storage.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "rename", denied)
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactError) as failure:
        store.create(*inputs)
    assert failure.value.code == "IO_ERROR"
    assert len(attempts) == 4 and delays == [0.05, 0.1, 0.2]
    assert not store.list()
    _assert_clean(store)


@pytest.mark.parametrize(("platform", "error"), [
    ("linux", _winerror(5)),
    ("win32", PermissionError(errno.EACCES, "ordinary denial")),
    ("win32", _winerror(1314)),
    ("win32", OSError(errno.ENOSPC, "disk full")),
])
def test_nontransient_or_nonwindows_errors_do_not_retry(
    tmp_path: Path, inputs: tuple[Path, Report], monkeypatch: pytest.MonkeyPatch,
    platform: str, error: OSError,
) -> None:
    attempts: list[Path] = []
    delays: list[float] = []

    def denied(stage: Path, _target: Any) -> Path:
        attempts.append(stage)
        raise error

    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(storage.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "rename", denied)
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactError) as failure:
        store.create(*inputs)
    assert failure.value.code == "IO_ERROR" and len(attempts) == 1 and delays == []
    _assert_clean(store)


def test_concurrent_publisher_winner_is_verified_without_retry_or_replacement(
    tmp_path: Path, inputs: tuple[Path, Report], monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    attempts: list[Path] = []

    def concurrent_winner(stage: Path, destination: Any) -> Path:
        attempts.append(stage)
        # Simulate a second process atomically publishing complete identical data
        # before this process receives its access-denied response.
        shutil.copytree(stage, destination)
        raise _winerror(5)

    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(storage.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "rename", concurrent_winner)
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(*inputs)
    assert len(attempts) == 1 and delays == []
    assert store.open(artifact.id).id == artifact.id and len(store.list()) == 1
    _assert_clean(store)


def test_concurrent_corrupt_destination_is_never_accepted_by_retry(
    tmp_path: Path, inputs: tuple[Path, Report], monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    def corrupt_winner(_stage: Path, destination: Any) -> Path:
        Path(destination).mkdir()
        raise _winerror(32)

    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(storage.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "rename", corrupt_winner)
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactError) as failure:
        store.create(*inputs)
    assert failure.value.code == "CORRUPT_ARTIFACT" and delays == []
    _assert_clean(store)
