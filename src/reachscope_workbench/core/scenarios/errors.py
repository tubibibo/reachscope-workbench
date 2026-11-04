"""场景包错误码与编程错误载体；坏包不抛异常，而是变成 ScenarioIssue。"""

from __future__ import annotations

from ..models import WorkbenchError

SCENARIO_INVALID = "SCENARIO_INVALID"
SCENARIO_FORMAT_UNSUPPORTED = "SCENARIO_FORMAT_UNSUPPORTED"
SCENARIO_DUPLICATE_ID = "SCENARIO_DUPLICATE_ID"
SCENARIO_PATH_ESCAPE = "SCENARIO_PATH_ESCAPE"
SCENARIO_TOO_LARGE = "SCENARIO_TOO_LARGE"
SCENARIO_ROOT_MISSING = "SCENARIO_ROOT_MISSING"


class ScenarioError(WorkbenchError):
    """编程错误的载体；坏包不抛它，而是变成 ScenarioIssue。"""
