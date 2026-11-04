"""Layer contracts for the multi-module workbench, including relative imports."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path("src/reachscope_workbench")


def imports(path: Path) -> list[str]:
    package = ".".join(path.relative_to(Path("src")).parts[:-1])
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = importlib.util.resolve_name("." * node.level + name, package)
            found.append(name)
        elif isinstance(node, ast.Import):
            found.extend(item.name for item in node.names)
    return found


def test_domain_and_modules_do_not_depend_on_api_or_frontend() -> None:
    for path in (ROOT / "core").rglob("*.py"):
        for name in imports(path):
            assert not name.startswith(("fastapi", "starlette", "reachscope_workbench.api",
                                        "reachscope_workbench.modules", "reachscope_workbench.integrations")), (path, name)
    for module in ("android", "web", "cloud", "host"):
        for path in (ROOT / "modules" / module).rglob("*.py"):
            for name in imports(path):
                assert not name.startswith(("fastapi", "reachscope_workbench.api")), (path, name)
                for other in {"android", "web", "cloud", "host"} - {module}:
                    assert not name.startswith(f"reachscope_workbench.modules.{other}"), (path, name)


def test_core_model_is_stdlib_only() -> None:
    names = imports(ROOT / "core/models.py")
    assert all(name.split(".")[0] in {"__future__", "dataclasses", "pathlib", "typing"} for name in names)


def test_host_collector_stays_independent_of_rules_domain_and_http() -> None:
    paths = list((ROOT / "collectors" / "host").glob("*.py"))
    assert paths, "The downloadable collector must have reviewable source files"
    for path in paths:
        for name in imports(path):
            assert name.startswith("reachscope_workbench.collectors.") or name.split(".")[0] in sys.stdlib_module_names, (path, name)
