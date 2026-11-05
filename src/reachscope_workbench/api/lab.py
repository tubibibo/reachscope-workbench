"""Explicit local teaching-site lifecycle; no automatic checks or model requests."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..integrations.local_lab import LocalLab
from .contracts import Payload


class _Empty(Payload):
    pass


class LabConfigure(Payload):
    generation: str = Field(pattern=r"^[a-f0-9]{32}$")
    profile: Literal["baseline", "hardened"]


class ScenarioPackView(BaseModel):
    """一个已加载场景包的公开视图；OpenAPI 契约由此生成，前端引用生成类型。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: dict[str, str]
    summary: dict[str, str]
    difficulty: Literal["intro", "intermediate", "advanced"]
    limits: list[str] = []


class ScenarioIssueView(BaseModel):
    """一个坏包的诊断；source 是包声明的 id 或目录名，绝不携带文件内容。"""

    model_config = ConfigDict(extra="forbid")

    source: str
    code: str
    message: str


class ScenarioListView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packs: list[ScenarioPackView]
    issues: list[ScenarioIssueView]


class LabStart(Payload):
    """请求体可整体省略或传 {}：两者都走内置默认场景；带 id 则启动指定场景包。"""

    scenario_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")


def lab_router(lab: LocalLab) -> APIRouter:
    router = APIRouter(prefix="/api/lab", tags=["local-teaching-site"])

    @router.get("")
    def status() -> dict[str, Any]:
        return lab.status()

    @router.get("/scenarios", response_model=ScenarioListView)
    def scenarios() -> dict[str, Any]:
        return lab.scenarios()

    @router.post("/start")
    def start(payload: LabStart | None = None) -> dict[str, Any]:
        return lab.start(payload.scenario_id if payload is not None else None)

    @router.post("/configure")
    def configure(payload: LabConfigure) -> dict[str, Any]:
        return lab.configure(payload.generation, payload.profile)

    @router.post("/stop")
    def stop(payload: _Empty | None = None) -> dict[str, Any]:
        return lab.stop()

    return router
