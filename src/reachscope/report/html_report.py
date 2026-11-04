"""HTML 报告（PLAN §8.2 / TASKS T4.2）。

单文件、内嵌 CSS、无外部资源、无 JS（`<details>` 承担展开交互），离线可直接打开与截图。
九个章节的顺序由模板固定：标题/结论 → 免责声明 → 输入信息 → 保护状态 → 概览 →
链路 → 反例 → 方法说明 → 局限性。

链路章节直接消费 `Chain.judgments` / `Chain.rank` —— 这些字段由
`analyze/evidence.py::build_evidence` 写回（D-067），报告层不重算判定。
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from jinja2 import Environment, PackageLoader

from ..ir.model import Report, SourceLoc
from .json_report import normalize_report
from .methods import RULE_DESCRIPTIONS

#: 模板文件名（`templates/report.html.j2`）。
TEMPLATE_NAME = "report.html.j2"


def _format_loc(source: SourceLoc | None) -> str:
    """`SourceLoc` → `file:line`；无证据时显式写“—”，不省略这一列（§9.2）。"""
    if source is None or not source.file:
        return "—"
    return f"{source.file}:{source.line}"


@cache
def _environment() -> Environment:
    """Jinja 环境（懒创建，避免 import 期做 I/O）。

    `autoescape=True` 是硬要求：模板名以 `.j2` 结尾，`select_autoescape` 的默认
    扩展名表不会启用自动转义。
    """
    environment = Environment(
        loader=PackageLoader("reachscope.report", "templates"),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters["loc"] = _format_loc
    return environment


def _conclusion(report: Report) -> str:
    """首页的一句话结论（§8.2 第 1 章）。"""
    if not report.protection.analyzable:
        return "无法分析：检测到强加固，本报告不包含任何可利用性结论。"
    if report.findings:
        top = report.findings[0]
        return (
            f"发现 {len(report.findings)} 条可利用链；"
            f"最高可利用性 {top.exploitability.value}、影响 {top.impact.value}、"
            f"置信度 {top.confidence.value}。"
        )
    if report.counter_examples:
        return (
            f"未发现可利用链；{len(report.counter_examples)} 个入口已逐条给出反例，"
            "说明为何未纳入。"
        )
    return "未发现入口：该 APK 没有声明可被第三方触达的组件，反例列表为空。"


def render_html(report: Report) -> str:
    """把报告渲染成单文件 HTML（顶层列表与 JSON 报告同一套排序口径，D-066）。"""
    normalized = normalize_report(report)
    template = _environment().get_template(TEMPLATE_NAME)
    return template.render(
        report=normalized,
        conclusion=_conclusion(normalized),
        chains_by_id={chain.id: chain for chain in normalized.chains},
        rules=RULE_DESCRIPTIONS,
    )


def write_html(report: Report, path: str | Path) -> Path:
    """把 HTML 写到 `path`（UTF-8、LF、自动创建父目录），返回写入路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(report), encoding="utf-8", newline="\n")
    return target


__all__ = [
    "TEMPLATE_NAME",
    "render_html",
    "write_html",
]
