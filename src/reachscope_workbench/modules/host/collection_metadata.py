"""Validate untrusted collector assertions independently of capture and rules."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from ...core.models import WorkbenchError

COLLECTOR_SCHEMA = "reachscope-host/2"
PROJECTION = "reachscope-minimal/1"
_STATES = {"collected", "unavailable", "failed", "timeout", "budget_exceeded", "unsupported"}
_REASONS = {"ok", "missing_executable", "nonzero_exit", "command_timeout", "output_budget",
            "projection_unsupported", "context_unsupported", "execution_unavailable", "output_read_failed"}
_REASON_STATES = {"ok": "collected", "missing_executable": "unavailable", "execution_unavailable": "unavailable",
                  "output_read_failed": "failed", "nonzero_exit": "failed", "command_timeout": "timeout",
                  "output_budget": "budget_exceeded", "projection_unsupported": "unsupported", "context_unsupported": "unsupported"}


class ComponentCapture(TypedDict):
    state: str
    complete: bool
    exit_code: int | None
    reason_code: str


class CollectionMetadata(TypedDict):
    format_version: int
    version: str
    projection: str
    plan_sha256: str
    components: dict[str, ComponentCapture]


def _reject() -> None:
    raise WorkbenchError("INVALID_HOST_COLLECTION", "采集元数据格式不受支持或状态不一致，请使用当前采集器重新导出；未解释为安全。")


def parse_collection(value: Any) -> CollectionMetadata:
    """Return only bounded known metadata; never trust a producer's safety claim."""
    if not isinstance(value, dict) or set(value) != {"version", "projection", "plan_sha256", "components"}:
        _reject()
    if value.get("version") != "0.14.0" or value.get("projection") != PROJECTION:
        _reject()
    digest = value.get("plan_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        _reject()
    components = value.get("components")
    if not isinstance(components, dict) or set(components) != {"ssh", "nginx"}:
        _reject()
    clean: dict[str, ComponentCapture] = {}
    for component in ("ssh", "nginx"):
        item = components[component]
        if not isinstance(item, dict) or set(item) - {"state", "complete", "exit_code", "reason_code"}:
            _reject()
        state, complete, code, reason = (item.get(key) for key in ("state", "complete", "exit_code", "reason_code"))
        if (not isinstance(state, str) or state not in _STATES or type(complete) is not bool
                or code is not None and (type(code) is not int or not -255 <= code <= 255)
                or not isinstance(reason, str) or reason not in _REASONS):
            _reject()
        if (state == "collected") != (complete is True and code == 0 and reason == "ok"):
            _reject()
        if state != "collected" and (complete or reason == "ok"):
            _reject()
        if (_REASON_STATES[reason] != state or reason == "nonzero_exit" and (code is None or code == 0)
                or state == "unavailable" and code is not None or reason == "context_unsupported" and code is not None):
            _reject()
        clean[component] = {"state": state, "complete": complete, "exit_code": code, "reason_code": reason}
    return {"format_version": 2, "version": "0.14.0", "projection": PROJECTION,
            "plan_sha256": digest, "components": clean}
