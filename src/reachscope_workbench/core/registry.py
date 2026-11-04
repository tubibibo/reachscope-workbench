"""Explicit module registration; implementations stay independent of transports."""

from __future__ import annotations

from .models import AnalysisModule, WorkbenchError


class ModuleRegistry:
    def __init__(self, modules: list[AnalysisModule]) -> None:
        self._modules: dict[str, AnalysisModule] = {}
        for module in modules:
            if module.spec.id in self._modules:
                raise ValueError(f"Duplicate module ID: {module.spec.id}")
            self._modules[module.spec.id] = module

    def get(self, module_id: str) -> AnalysisModule:
        if module_id not in self._modules:
            raise WorkbenchError("MODULE_NOT_FOUND", "未知的分析模块")
        return self._modules[module_id]

    def describe(self) -> list[dict[str, object]]:
        return [module.spec.to_dict() for module in self._modules.values()]
