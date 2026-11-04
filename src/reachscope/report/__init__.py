"""报告层：JSON（T4.1）与 HTML（T4.2）。

报告层只依赖 IR（见 `tests/unit/test_architecture.py` 的分层表），
不回头读 smali / manifest，也不做任何判定。
"""

from __future__ import annotations

from .html_report import render_html, write_html
from .json_report import load_json, normalize_report, render_json, write_json
from .methods import RULE_DESCRIPTIONS

__all__ = [
    "RULE_DESCRIPTIONS",
    "load_json",
    "normalize_report",
    "render_html",
    "render_json",
    "write_html",
    "write_json",
]
