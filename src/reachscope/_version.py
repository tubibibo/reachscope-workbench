"""版本号与构建期常量。

单独成模块，避免 ``reachscope/__init__.py`` 与 ``reachscope/cli.py`` 互相导入形成环
（见 DECISIONS.md D-006）。
"""

from __future__ import annotations

#: 工具版本。`reachscope version` 直接输出该值。
__version__ = "0.4.1"

#: JSON 报告的 schema 版本（PLAN §8.1）。
SCHEMA_VERSION = "0.1"

#: 日志器名称，所有子模块用 ``logging.getLogger("reachscope.<module>")``。
LOGGER_NAME = "reachscope"
