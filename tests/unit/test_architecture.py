"""工程规范化：分层依赖 + 库代码无副作用。

用 AST 静态扫描 `src/reachscope/**/*.py`，断言：
1. 每一层（`ir` / `ingest` / `extract` / `graph` / `analyze` / `report` / `cli`）只允许依赖
   规划里允许的下层，禁止反向 import（**ingest 与 extract 互不引用**，extract → ingest 是单向）。
2. 库模块（`cli` 以外）模块顶层**不调用** `print` / `open` / `Path.read_*`，避免 import 时的副作用。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path("src/reachscope")

#: 每一层允许直接依赖的其它层（不含自身包内互相引用）。
#: `graph` 是 `extract` 的**下层**：M2 的单步回溯在 T3.1 已并入 `graph/regflow.py`（D-056），
#: 所以 `extract` 可以 import `graph`，反过来不行（`graph` 不许 import `extract`）。
LAYER_DEPS: dict[str, frozenset[str]] = {
    # 叶子
    "ir": frozenset({"_version"}),
    "exitcodes": frozenset(),
    "_version": frozenset(),
    # 图原语：只用 IR 与 smali 索引
    "graph": frozenset({"ir", "ingest"}),
    # ingest 仅依赖叶子
    "ingest": frozenset({"ir", "exitcodes", "_version"}),
    # extract 依赖 ingest 与图原语
    "extract": frozenset({"ir", "ingest", "graph"}),
    # 未来层（M3 / M4 落地时使用）
    "analyze": frozenset({"ir", "ingest", "extract", "graph", "_version"}),
    "report": frozenset({"ir", "_version"}),
    # 协议层只读报告 IR：不得反向依赖 extract / analyze / ingest
    "protocol": frozenset({"ir"}),
    "artifacts": frozenset({"ir", "ingest", "report", "_version"}),
    "query": frozenset({"ir", "artifacts", "protocol"}),
    "application": frozenset({"analyze", "artifacts", "ir"}),
    "demo": frozenset({"application", "query", "artifacts", "_version"}),
    "workspace_cli": frozenset({"application", "artifacts", "demo", "query", "protocol"}),
    # CLI 是顶层
    "cli": frozenset({
        "ir", "ingest", "extract", "graph", "analyze", "report", "protocol",
        "exitcodes", "_version", "artifacts", "workspace_cli",
    }),
    # `python -m reachscope` 只是 cli.main 的薄入口
    "__main__": frozenset({"cli"}),
}

#: 顶层禁止的“副作用”调用（库代码 import 时不能跑）。
FORBIDDEN_TOP_LEVEL_CALLS = {
    "print",
    "exit",
    "quit",
}


def _layer_of(path: Path) -> str:
    """文件所在的层（顶层模块自身是层名）。"""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return ""
    return rel.parts[0] if len(rel.parts) > 1 else path.stem


def _reachscope_layers(path: Path) -> set[str]:
    """从 `import x from reachscope.<layer>...` 中提取所有**跨层**依赖。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    layers: set[str] = set()
    relative = path.relative_to(ROOT.parent).with_suffix("")
    package = ".".join(relative.parts[:-1])
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = importlib.util.resolve_name("." * node.level + module, package)
            modules.append(module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for module in modules:
            parts = module.split(".")
            if len(parts) >= 2 and parts[0] == "reachscope":
                layers.add(parts[1])
    return layers


def test_layer_dependencies_are_one_way() -> None:
    """每一层只依赖其下层与同层（层内互引不校验）。"""
    for py in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in py.parts or py.name == "__init__.py":
            continue
        layer = _layer_of(py)
        if layer not in LAYER_DEPS:
            continue
        for target in _reachscope_layers(py):
            if target == layer:
                continue
            if target not in LAYER_DEPS[layer]:
                pytest.fail(
                    f"{py.relative_to(ROOT.parent)} 反向依赖：{layer} → {target}"
                )


def test_ingest_and_extract_do_not_import_each_other() -> None:
    """`ingest` 不允许 import `extract`（单向：extract → ingest）。"""
    for py in sorted((ROOT / "ingest").rglob("*.py")):
        if py.name == "__init__.py":
            continue
        for target in _reachscope_layers(py):
            assert target != "extract", f"{py} 不允许 import extract：违反分层 {target}"


def test_library_modules_have_no_top_level_print() -> None:
    """库代码 import 时不能跑 `print` —— stdout 只属于 CLI。"""
    for py in sorted(ROOT.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        # 顶层模块里只有 cli.py 允许 print
        if py.parent == ROOT and py.name == "cli.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in tree.body:
            if not isinstance(node, ast.Expr):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Name) and call.func.id in FORBIDDEN_TOP_LEVEL_CALLS:
                pytest.fail(f"{py} 顶层调用 {call.func.id}()：库模块禁止 import 期副作用")


def test_library_modules_have_no_top_level_io() -> None:
    """库代码 import 时不能打开文件 —— `apk.py` 的 `ApkInput.load` 是函数，按调用时机执行。"""
    forbidden_attrs = {
        ("open",): None,
        ("Path", "read_text"): None,
        ("Path", "read_bytes"): None,
    }
    for py in sorted(ROOT.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        if py.parent == ROOT and py.name == "cli.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in tree.body:
            if not isinstance(node, ast.Expr):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            parts: list[str] = []
            current: ast.expr | None = call.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            parts = list(reversed(parts))
            if tuple(parts) in forbidden_attrs:
                pytest.fail(f"{py} 顶层做 I/O：{'.'.join(parts)}()")


def test_layers_dict_covers_all_known_layers() -> None:
    """新增包/顶层模块时必须在这里显式登记；忘了就 fail。"""
    expected = {
        "ir", "ingest", "extract", "graph", "analyze", "report", "protocol", "cli",
        "__main__", "exitcodes", "_version",
        "artifacts", "query", "application", "demo", "workspace_cli",
    }
    actual: set[str] = set()
    for path in ROOT.iterdir():
        if path.is_dir() and (path / "__init__.py").exists():
            actual.add(path.name)
        elif path.suffix == ".py" and path.stem != "__init__":
            actual.add(path.stem)
    missing = actual - expected
    assert not missing, f"新增包/顶层模块没在 LAYER_DEPS 里登记：{sorted(missing)}"


def test_cli_declares_its_public_entry_point() -> None:
    from reachscope.cli import __all__

    assert __all__ == ["main"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
