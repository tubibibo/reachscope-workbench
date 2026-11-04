"""Provider presets for OpenAI-compatible advisory endpoints.

This module is pure configuration data. It does not contain keys, HTTP clients,
model calls or provider SDK dependencies.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "openai_compatible", "label": "OpenAI 兼容接口", "base_url": "https://api.openai.com/v1",
        "models": [], "notes": "填写服务商提供的模型标识；支持 Chat Completions 的兼容接口。",
        "reasoning_efforts": ["default", "none", "low", "medium", "high", "xhigh", "max"],
        "token_limit_field": "max_completion_tokens",
    },
    {
        "id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-flash", "deepseek-v4-pro"], "notes": "2026-11-01 核对官方模型目录；具体可用性以服务商账户为准。",
        "reasoning_efforts": ["default", "none", "low", "high", "max"],
        "token_limit_field": "max_tokens",
    },
    {
        "id": "custom", "label": "自定义兼容接口", "base_url": "", "models": [],
        "notes": "用于其他提供 OpenAI-compatible Chat Completions 的服务；需要自行确认协议和模型标识。",
        "reasoning_efforts": ["default", "none", "low", "medium", "high", "xhigh", "max"],
        "token_limit_field": "max_tokens",
    },
)


def presets() -> list[dict[str, Any]]:
    """Return defensive copies suitable for a public settings page."""
    return [{**item, "models": list(item["models"]), "reasoning_efforts": list(item["reasoning_efforts"])} for item in _PRESETS]


def preset(identifier: str) -> dict[str, Any]:
    for item in _PRESETS:
        if item["id"] == identifier:
            return {**item, "models": list(item["models"]), "reasoning_efforts": list(item["reasoning_efforts"])}
    raise ValueError("unknown AI provider preset")


def infer_provider(base_url: str) -> str:
    try:
        hostname = (urlsplit(base_url).hostname or "").rstrip(".").lower()
    except ValueError:
        return "custom"
    if hostname == "api.deepseek.com":
        return "deepseek"
    if hostname == "api.openai.com":
        return "openai_compatible"
    return "custom"
