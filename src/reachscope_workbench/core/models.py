"""Shared domain contracts. No HTTP, database or module implementation imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class WorkbenchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    name: str
    description: str
    capabilities: list[str]
    input_modes: list[str]
    version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    title: str
    source: str
    data: dict[str, Any]
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    id: str
    title: str
    severity: str
    category: str
    description: str
    evidence_ids: list[str]
    confidence: str = "observed"
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleResult:
    module: str
    target: str
    summary: dict[str, Any]
    evidence: list[Evidence] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Progress(Protocol):
    def __call__(self, percent: int, message: str) -> None: ...


@dataclass
class RunContext:
    job_id: str
    workspace: Path
    uploads: Path
    progress: Progress


class AnalysisModule(Protocol):
    spec: ModuleSpec

    def validate(self, config: dict[str, Any]) -> dict[str, Any]: ...

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult: ...


@runtime_checkable
class LocalInputPreview(Protocol):
    """Optional local-only parsing capability; must not run checks or create jobs."""

    def preview(self, config: dict[str, Any], uploads: Path) -> dict[str, Any]: ...
