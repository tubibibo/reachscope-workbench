"""ReachScope — Android APK 静态分析工具（WebView 桥 / 深链可利用性）。

v0.1 M0：只导出版本与退出码，分析能力在后续里程碑补齐。
"""

from __future__ import annotations

from ._version import SCHEMA_VERSION, __version__
from .exitcodes import ExitCode

__all__ = ["SCHEMA_VERSION", "ExitCode", "__version__"]
