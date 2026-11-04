"""Explicit local teaching-site lifecycle; no automatic checks or model requests."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from ..integrations.local_lab import LocalLab
from .contracts import Payload


class _Empty(Payload):
    pass


class LabConfigure(Payload):
    generation: str = Field(pattern=r"^[a-f0-9]{32}$")
    profile: Literal["baseline", "hardened"]


def lab_router(lab: LocalLab) -> APIRouter:
    router = APIRouter(prefix="/api/lab", tags=["local-teaching-site"])

    @router.get("")
    def status() -> dict[str, Any]:
        return lab.status()

    @router.post("/start")
    def start(payload: _Empty | None = None) -> dict[str, Any]:
        return lab.start()

    @router.post("/configure")
    def configure(payload: LabConfigure) -> dict[str, Any]:
        return lab.configure(payload.generation, payload.profile)

    @router.post("/stop")
    def stop(payload: _Empty | None = None) -> dict[str, Any]:
        return lab.stop()

    return router
