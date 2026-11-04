"""测试辅助：构造最小 APK（只含 AndroidManifest.xml 的 zip），并隔离日志状态。

不依赖 apktool，也不使用 tests/fixtures 下的验收基线。
"""

from __future__ import annotations

import itertools
import logging
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

MANIFEST_BYTES = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
    b'    package="com.example.app" android:versionCode="1" android:versionName="1.0">\n'
    b"</manifest>\n"
)


def write_apk(path: Path, entries: dict[str, bytes] | None = None) -> Path:
    """写一个 zip；默认包含一个顶层 `AndroidManifest.xml`。"""
    payload = entries if entries is not None else {"AndroidManifest.xml": MANIFEST_BYTES}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    return path


@pytest.fixture
def make_apk(tmp_path: Path) -> Callable[..., Path]:
    """返回一个工厂：`make_apk()` 是合法最小 APK，`make_apk({...})` 自定义条目。"""
    counter = itertools.count()

    def _make(entries: dict[str, bytes] | None = None, name: str | None = None) -> Path:
        filename = name or f"sample{next(counter)}.apk"
        return write_apk(tmp_path / filename, entries)

    return _make


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """每个用例后恢复日志传播并清空 handler。

    CLI 的 `_setup_logging` 会把 `reachscope` logger 设成 propagate=False，
    若不复位，后续用例用 caplog 捕获日志会失效。
    """
    yield
    log = logging.getLogger("reachscope")
    log.propagate = True
    log.setLevel(logging.NOTSET)
    for handler in list(log.handlers):
        log.removeHandler(handler)
