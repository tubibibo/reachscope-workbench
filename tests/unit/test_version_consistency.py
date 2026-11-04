"""The four published version declarations must always state the same value."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import reachscope_workbench

ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    """Read one local JSON document without touching the network."""
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def test_published_versions_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declarations: dict[str, Any] = {
        "pyproject.toml [project].version": pyproject["project"]["version"],
        "src/reachscope_workbench/__init__.py __version__": reachscope_workbench.__version__,
        "frontend/package.json version": _read_json(ROOT / "frontend/package.json")["version"],
        "frontend/contracts/openapi.json info.version": _read_json(
            ROOT / "frontend/contracts/openapi.json"
        )["info"]["version"],
    }
    canonical = declarations["pyproject.toml [project].version"]
    mismatches = [
        f"{name} is {value!r}" for name, value in declarations.items() if value != canonical
    ]
    assert not mismatches, (
        f"pyproject.toml [project].version is {canonical!r}, "
        "but these declarations disagree: " + "; ".join(mismatches)
    )
