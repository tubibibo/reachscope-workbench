"""Read-only local startup checks. No server, target or model is contacted."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from . import __version__


@dataclass(frozen=True)
class ReadinessCheck:
    id: str
    label: str
    status: Literal["ready", "blocked", "optional"]
    required: bool
    message: str


class _BundleLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.has_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag == "script" and fields.get("src"):
            self.has_script = True
            self.assets.append(str(fields["src"]))
        if tag == "link" and fields.get("rel") == "stylesheet" and fields.get("href"):
            self.assets.append(str(fields["href"]))


def _frontend_ready(directory: Path) -> bool:
    try:
        root = directory.resolve()
        parser = _BundleLinks()
        parser.feed((root / "index.html").read_text(encoding="utf-8"))
        if not parser.has_script:
            return False
        for reference in parser.assets:
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                return False
            target = (root / unquote(url.path).lstrip("/")).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return False
        return True
    except (OSError, ValueError, UnicodeError):
        return False


def _workspace_ready(directory: Path) -> bool:
    """Inspect the nearest existing ancestor without making a data directory."""
    try:
        candidate = directory.resolve()
        while not candidate.exists():
            parent = candidate.parent
            if parent == candidate:
                return False
            candidate = parent
        return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
    except (OSError, ValueError):
        return False


def inspect_readiness(data: Path, *, static_dir: Path | None = None) -> dict[str, Any]:
    """Report bounded local checks, keeping APK prerequisites optional."""
    checks: list[ReadinessCheck] = []

    def add(identifier: str, label: str, available: bool, required: bool,
            success: str, failure: str) -> None:
        checks.append(ReadinessCheck(identifier, label,
                                     "ready" if available else "blocked" if required else "optional",
                                     required, success if available else failure))

    add("python", "Python 3.11+", sys.version_info >= (3, 11), True,
        "Python 版本符合要求。", "请使用 Python 3.11 或更高版本。")
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            sqlite_ready = connection.execute("SELECT 1").fetchone() == (1,)
    except sqlite3.Error:
        sqlite_ready = False
    add("sqlite", "SQLite", sqlite_ready, True,
        "SQLite 内存查询成功；未读取或修改工作区数据库。", "当前 Python 的 SQLite 不可用。")
    add("frontend", "前端资源", _frontend_ready(static_dir or Path(__file__).parent / "static"), True,
        "页面及其本地 JS/CSS 资源完整。", "前端资源缺失或引用异常：重新安装发行包，源码开发请在 frontend 运行 npm ci 和 npm run build。")
    add("workspace", "工作区路径", _workspace_ready(data), True,
        "工作区或最近存在的父目录通过静态可写性检查；未创建文件。",
        "工作区路径不是目录或当前用户不可写；请换一个本机可写目录。")
    java = shutil.which("java") is not None
    add("java", "APK 分析 / Java", java, False,
        "已找到 Java；未执行或验证版本。", "未找到 Java。Web、云配置和样例仍可使用；真实 APK 分析需要 Java。")
    jar = os.environ.get("APKTOOL_JAR")
    try:
        decoder = (Path(jar).is_file() and Path(jar).suffix.lower() == ".jar") if jar else shutil.which("apktool") is not None
    except (OSError, ValueError):
        decoder = False
    add("apktool", "APK 分析 / Apktool", decoder, False,
        "已找到配置的 Apktool；解码兼容性在真实任务中验证。",
        "未找到 Apktool。真实 APK 分析请设置 APKTOOL_JAR 或安装 apktool 命令。")
    return {
        "version": __version__, "ready": all(item.status != "blocked" for item in checks),
        "network_contacted": False, "workspace_modified": False,
        "checks": [asdict(item) for item in checks],
        "limitations": ["自检不启动服务，不验证端口占用、工作区锁、实际写入、数据库迁移或目标网络。",
                        "AI 为可选功能；服务启动后，在 AI 设置中另行诊断端点并配置自己的服务商密钥。"],
    }
