"""JSON 报告输出（PLAN §8.1 / TASKS T4.1）。

本模块只做一件事：把 `Report` **稳定地**写成 JSON。不做分析、不补字段：

1. 顶层列表排序（§8.1），保证同一份输入两次渲染逐字节一致（§9.3）
2. 2 空格缩进、UTF-8、`ensure_ascii=False`、文件以 LF 结尾
3. `schema_version` 与 `summary` 由 `Report.to_dict()` 派生（D-009），这里不重复生成

**排序口径**（D-066）：

- `components` / `deeplinks` / `webviews` / `bridges` / `chains` → 按 `id` 升序
- `findings` → 按 §6.5 的三元组字典序降序，同分按 `chain_id` 升序
- `counter_examples` → 按 `entry_id`、`failed_judgment`、`reason` 升序（§8.2“按入口排序”）
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .._version import SCHEMA_VERSION
from ..ir.model import Finding, Report
from ..ir.serialize import IRDeserializeError

#: §8.1 要求的缩进宽度。
JSON_INDENT = 2


def _finding_key(finding: Finding) -> tuple[int, int, int, str]:
    """§6.5：`(exploitability, impact, confidence)` 字典序降序，同分按 `chain_id` 升序。"""
    return (
        -finding.exploitability.score(),
        -finding.impact.score(),
        -finding.confidence.score(),
        finding.chain_id,
    )


def normalize_report(report: Report) -> Report:
    """返回排序后的报告**副本**（不修改入参）。

    只重排顶层列表；元素本身是 frozen dataclass，原样复用。
    `chain.steps` / `chain.judgments` 的顺序有语义（步骤序号、J4 逐项加减分），
    不在这里重排。
    """
    return dataclasses.replace(
        report,
        components=sorted(report.components, key=lambda component: component.id),
        deeplinks=sorted(report.deeplinks, key=lambda deeplink: deeplink.id),
        webviews=sorted(report.webviews, key=lambda webview: webview.id),
        bridges=sorted(report.bridges, key=lambda bridge: bridge.id),
        chains=sorted(report.chains, key=lambda chain: chain.id),
        findings=sorted(report.findings, key=_finding_key),
        counter_examples=sorted(
            report.counter_examples,
            key=lambda counter_example: (
                counter_example.entry_id,
                counter_example.failed_judgment,
                counter_example.reason,
            ),
        ),
    )


def render_json(report: Report) -> str:
    """把报告渲染成稳定的 JSON 文本（末尾恰好一个换行）。"""
    data = normalize_report(report).to_dict()
    return json.dumps(data, indent=JSON_INDENT, ensure_ascii=False) + "\n"


def write_json(report: Report, path: str | Path) -> Path:
    """把报告写到 `path`（UTF-8、LF、自动创建父目录），返回写入路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_json(report), encoding="utf-8", newline="\n")
    return target


def load_json(path: str | Path) -> Report:
    """读取 `report.json` 并还原 `Report`。

    文件边界必须带受支持的 schema_version；不能把未知版本按当前结构解释。
    未版本化的手写数据应重新生成，不能静默当作完整分析结果。
    文件不是合法 JSON、顶层不是对象或版本不兼容时抛 IRDeserializeError。
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IRDeserializeError(
            f"{path}: 文件不是 UTF-8", reason="not_utf8", detail=str(exc)
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IRDeserializeError(f"{path}: 不是合法的 JSON（{exc.msg}，行 {exc.lineno}）") from exc
    if not isinstance(data, dict):
        raise IRDeserializeError(f"{path}: 顶层必须是 JSON 对象，实际是 {type(data).__name__}")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise IRDeserializeError(
            f"{path}: unsupported report schema_version {version!r}; "
            f"expected {SCHEMA_VERSION!r}. Regenerate unversioned or incompatible reports."
        )
    return Report.from_dict(data)


__all__ = [
    "JSON_INDENT",
    "load_json",
    "normalize_report",
    "render_json",
    "write_json",
]
