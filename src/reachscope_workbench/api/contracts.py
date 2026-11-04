"""Bounded HTTP request contracts; transport validation stays outside the core."""

from __future__ import annotations

import math
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="after")
    def valid_json_text(self) -> Self:
        stack: list[tuple[Any, int]] = [(self.model_dump(), 0)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if depth > 40 or nodes > 10000:
                raise ValueError("请求结构超过复杂度限制")
            if isinstance(value, str):
                try:
                    value.encode("utf-8")
                except UnicodeError as exc:
                    raise ValueError("文本包含无效 Unicode 字符") from exc
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("数值必须为有限值")
            elif isinstance(value, dict):
                stack.extend((item, depth + 1) for pair in value.items() for item in pair)
            elif isinstance(value, list):
                stack.extend((item, depth + 1) for item in value)
        return self


class JobCreate(Payload):
    module: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=120)
    config: dict[str, Any]
    asset_id: str | None = Field(default=None, min_length=32, max_length=32)


class AssetCreate(Payload):
    kind: Literal["android", "website", "cloud", "host"]
    name: str = Field(min_length=1, max_length=120)
    source: dict[str, Any]


class InspectionOptions(Payload):
    timeout: float | None = Field(default=None, ge=0.2, le=15)
    concurrency: int | None = Field(default=None, ge=1, le=5)


class InspectionCreate(Payload):
    name: str = Field(default="", max_length=120)
    checks: list[str] = Field(min_length=1, max_length=10)
    options: InspectionOptions = Field(default_factory=InspectionOptions)


class EngagementCreate(Payload):
    name: str = Field(min_length=1, max_length=120)
    objective: str = Field(default="", max_length=1000)
    authorization_note: str = Field(min_length=1, max_length=2000)
    asset_ids: list[str] = Field(min_length=1, max_length=100)


class CaseCreate(Payload):
    job_id: str = Field(min_length=32, max_length=32)
    source_kind: Literal["observation", "check"]
    source_ref: str = Field(min_length=1, max_length=128)


class CasePatch(Payload):
    expected_version: int = Field(ge=1)
    status: Literal["open", "in_progress", "ready_for_retest", "resolved", "accepted_risk", "false_positive"] | None = None
    owner: str | None = Field(default=None, max_length=80)
    due_date: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=4000)
    retest_job_id: str | None = Field(default=None, min_length=32, max_length=32)


class CaseRetest(Payload):
    expected_version: int = Field(ge=1)
    job_id: str = Field(min_length=32, max_length=32)
    note: str = Field(default="", max_length=4000)


class CaseRetestInput(Payload):
    expected_version: int = Field(ge=1)
    asset_id: str = Field(min_length=32, max_length=32)
    note: str = Field(min_length=1, max_length=4000)


class AIConfiguration(Payload):
    enabled: bool
    provider_id: Literal["openai_compatible", "openai-compatible", "deepseek", "custom"] | None = None
    provider_label: str = Field(default="", max_length=100)
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(default="", max_length=120)
    reasoning_effort: str = Field(default="default", pattern=r"^(default|none|low|medium|high|xhigh|max)$")
    token_limit_field: Literal["max_tokens", "max_completion_tokens"] | None = None
    allow_local: bool = False
    api_key: str | None = Field(default=None, max_length=8192)
    clear_key: bool = False


class AIDiagnostic(Payload):
    provider_id: Literal["openai_compatible", "openai-compatible", "deepseek", "custom"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    allow_local: bool | None = None


class AIModelDiagnostic(Payload):
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    consent: bool


class AIConsultation(Payload):
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    consent: bool
    authorization_note: str = Field(min_length=1, max_length=1000)
