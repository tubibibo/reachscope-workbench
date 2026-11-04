"""Provider-neutral port and strict output grammar, with no executable actions."""
from __future__ import annotations

from typing import Any, Protocol

from .models import WorkbenchError


class AdvisoryProvider(Protocol):
    async def consult(self, settings: dict[str, Any], key: str, context: dict[str, Any],
                      controls: list[dict[str, Any]]) -> dict[str, Any]: ...


def validate_selection(value: Any, controls: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    """Accept IDs and priorities only. Never render arbitrary model instructions."""
    allowed = {row["id"]: row for row in controls}
    evidence = set(context["evidence_ids"])
    if not isinstance(value, dict) or set(value) != {"red", "blue"}:
        raise WorkbenchError("AI_INVALID_RESPONSE", "模型输出必须包含红蓝两组结构化控制项")
    output: dict[str, Any] = {}
    for perspective in ("red", "blue"):
        rows = value[perspective]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 14:
            raise WorkbenchError("AI_INVALID_RESPONSE", "模型控制项数量无效")
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"control_id", "priority", "evidence_ids"}:
                raise WorkbenchError("AI_INVALID_RESPONSE", "模型返回了未允许的内容字段")
            identifier, priority, ids = row["control_id"], row["priority"], row["evidence_ids"]
            if (not isinstance(identifier, str) or identifier not in allowed or identifier in seen
                    or not isinstance(priority, str) or priority not in {"high", "medium", "low"} or not isinstance(ids, list)
                    or len(ids) > 20 or any(not isinstance(item, str) or item not in evidence for item in ids)):
                raise WorkbenchError("AI_INVALID_RESPONSE", "模型引用了未知、重复或无效的控制项/证据")
            control = allowed[identifier]
            # Configuration advice needs at least one observed matching rule.
            # Other topics remain visibly manual, never alleged scanner findings.
            matching = {item for target in context["targets"] for check in target["checks"]
                        if check["id"] in control["signals"] for item in check["evidence_ids"]}
            if control["applicability"] == "web_config" and (not ids or not set(ids) <= matching):
                raise WorkbenchError("AI_INVALID_RESPONSE", "配置建议缺少对应已执行规则的证据引用")
            seen.add(identifier)
            items.append({"control_id": identifier, "priority": priority, "evidence_ids": list(dict.fromkeys(ids)),
                          "title": control["title"], "category": control["category"],
                          "applicability": control["applicability"], "basis": "observed_configuration" if matching else "manual_review",
                          "actions": control["red_review"] if perspective == "red" else control["blue_actions"],
                          "verification": control["verification"], "limitations": control["limitations"],
                          "references": control["references"]})
        output[perspective] = items
    return output
