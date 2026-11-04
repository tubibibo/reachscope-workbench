"""特征提取（M2）。

只做“从 ingest 产物里提取 IR 事实”，不做判定（判定在 M3 的 `analyze/`）。
"""

from __future__ import annotations

from .components import (
    REASON_NO_CONCRETE,
    REASON_NOT_FOUND,
    class_name_of,
    descriptor_of,
    normalize_class_name,
    resolve_components,
)

__all__ = [
    "REASON_NOT_FOUND",
    "REASON_NO_CONCRETE",
    "class_name_of",
    "descriptor_of",
    "normalize_class_name",
    "resolve_components",
]
