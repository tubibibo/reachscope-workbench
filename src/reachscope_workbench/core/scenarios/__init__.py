"""场景包机制：只读 YAML 的加载器与数据文法，零代码执行、零出网。"""

from __future__ import annotations

from .errors import (
    SCENARIO_DUPLICATE_ID,
    SCENARIO_FORMAT_UNSUPPORTED,
    SCENARIO_INVALID,
    SCENARIO_PATH_ESCAPE,
    SCENARIO_ROOT_MISSING,
    SCENARIO_TOO_LARGE,
)
from .loader import LoadedScenario, ScenarioCatalog, ScenarioIssue, ScenarioLoader
from .model import PACK_FORMAT, ScenarioPack

__all__ = [
    "PACK_FORMAT",
    "SCENARIO_DUPLICATE_ID",
    "SCENARIO_FORMAT_UNSUPPORTED",
    "SCENARIO_INVALID",
    "SCENARIO_PATH_ESCAPE",
    "SCENARIO_ROOT_MISSING",
    "SCENARIO_TOO_LARGE",
    "LoadedScenario",
    "ScenarioCatalog",
    "ScenarioIssue",
    "ScenarioLoader",
    "ScenarioPack",
]
