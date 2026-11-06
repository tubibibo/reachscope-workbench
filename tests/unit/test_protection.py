"""T1.4 单测：保护状态检测三分支（--no-apkid / apkid 不可用 / 强加固）。

用 monkeypatch 打桩 `_run_apkid`，**不真实调用 apkid**。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reachscope.ingest import protection as protection_mod
from reachscope.ingest.protection import detect_protection, is_strong_protection


@pytest.fixture
def stub_apkid(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """把 `_run_apkid` 换成可控桩。

    用法：`stub_apkid(["packer::dexguard"])` 或 `stub_apkid(None)`。
    """

    def _install(labels: list[str] | None) -> None:
        monkeypatch.setattr(protection_mod, "_run_apkid", lambda _path: labels)

    return _install


def test_no_apkid_returns_explicit_skip(
    make_apk: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _must_not_run(_path: Path) -> list[str]:
        raise AssertionError("no-apkid 时不应调用 apkid")

    monkeypatch.setattr(protection_mod, "_run_apkid", _must_not_run)
    protection = detect_protection(make_apk(), no_apkid=True)
    assert protection.detected is False
    assert protection.analyzable is True
    assert protection.labels == []


# --- 分支 2：apkid 不可用 --------------------------------------------------


def test_missing_apkid_is_detected_none_and_warns(
    make_apk: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.protection"):
        protection = detect_protection(make_apk())
    assert protection.detected is None  # “未检测”，不是 False
    assert protection.analyzable is True
    assert protection.labels == []
    assert any("apkid 未安装" in record.message for record in caplog.records)


def test_run_apkid_handles_import_error(
    make_apk: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """apkid 缺失时 `_run_apkid` 返回 None，不抛异常。

    `sys.modules["apkid"] = None` 可稳定触发 `from apkid import apkid` 的 ImportError，
    不依赖本机是否真实安装。
    """
    import sys

    monkeypatch.setitem(sys.modules, "apkid", None)
    result = protection_mod._run_apkid(make_apk())
    assert result is None


def test_run_apkid_failure_is_treated_as_unavailable(
    make_apk: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """apkid 调用抛异常 → 警告 + 按“不可用”处理，不炸主流程。"""

    class _ExplodingApkid:
        def __init__(self, _handle: Any) -> None:
            pass

        def scan(self) -> dict[str, Any]:
            raise RuntimeError("boom")

    import sys

    fake_module = type(sys)("apkid")
    fake_module.APKID = _ExplodingApkid
    monkeypatch.setitem(sys.modules, "apkid", fake_module)
    monkeypatch.setitem(sys.modules, "apkid.apkid", fake_module)

    with caplog.at_level(logging.WARNING, logger="reachscope.ingest.protection"):
        protection = detect_protection(make_apk())
    assert protection.detected is None
    assert protection.analyzable is True
    assert any("apkid 调用失败" in record.message for record in caplog.records)


# --- 分支 3：强加固 --------------------------------------------------------


def test_strong_packer_makes_app_unanalyzable(
    make_apk: Callable[..., Path], stub_apkid: Callable[..., None]
) -> None:
    stub_apkid(["compiler::dexlib", "packer::dexguard"])
    protection = detect_protection(make_apk())
    assert protection.detected is True
    assert protection.tool == "apkid"
    assert protection.labels == ["compiler::dexlib", "packer::dexguard"]
    assert protection.analyzable is False


def test_known_packer_names_are_strong_without_category() -> None:
    """不带 `packer::` 前缀的已知加固名也算强加固（容忍 apkid 输出格式差异）。"""
    assert is_strong_protection(["bangcle"]) is True
    assert is_strong_protection(["Bangcle"]) is True
    assert is_strong_protection(["packer"]) is True
    assert is_strong_protection(["packer::qihoo"]) is True


def test_benign_labels_keep_app_analyzable(
    make_apk: Callable[..., Path], stub_apkid: Callable[..., None]
) -> None:
    stub_apkid(["compiler::dexlib", "anti_vm::yes"])
    protection = detect_protection(make_apk())
    assert protection.detected is True
    assert protection.analyzable is True


def test_no_hits_means_not_detected(
    make_apk: Callable[..., Path], stub_apkid: Callable[..., None]
) -> None:
    stub_apkid([])
    protection = detect_protection(make_apk())
    assert protection.detected is False
    assert protection.analyzable is True
    assert protection.tool is None


def test_is_strong_protection_rejects_empty_and_normal() -> None:
    assert is_strong_protection([]) is False
    assert is_strong_protection(["compiler::dexlib"]) is False
    assert is_strong_protection(["obfuscator::proguard"]) is False


def test_run_apkid_composes_category_labels(
    make_apk: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """APKiD 的 matches 结构 → `category::value` 标签（与 fixture 08 的格式一致）。"""

    class _FakeApkid:
        def __init__(self, _handle: Any) -> None:
            pass

        def scan(self) -> dict[str, Any]:
            return {
                "files": [
                    {"filename": "x", "matches": {"packer": ["dexguard"], "compiler": ["dexlib"]}}
                ]
            }

    import sys

    fake_module = type(sys)("apkid")
    fake_module.APKID = _FakeApkid
    monkeypatch.setitem(sys.modules, "apkid", fake_module)
    monkeypatch.setitem(sys.modules, "apkid.apkid", fake_module)

    labels = protection_mod._run_apkid(make_apk())
    assert labels == ["compiler::dexlib", "packer::dexguard"]


def test_run_apkid_returns_on_deadline(
    make_apk: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import sys
    import time

    class SlowApkid:
        def __init__(self, _handle: Any) -> None:
            pass

        def scan(self) -> dict[str, Any]:
            time.sleep(0.2)
            return {}

    fake_module = type(sys)("apkid")
    fake_module.APKID = SlowApkid
    monkeypatch.setitem(sys.modules, "apkid", fake_module)
    monkeypatch.setitem(sys.modules, "apkid.apkid", fake_module)
    with caplog.at_level(logging.WARNING):
        started = time.monotonic()
        result = protection_mod._run_apkid(make_apk(), timeout=0.02)
    assert result is None and time.monotonic() - started < 0.15
    assert "超时" in caplog.text
