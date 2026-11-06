"""场景包资源随 wheel/sdist 分发的打包契约（FIX-01）。

`package-data` 使用递归 glob；sdist 由 MANIFEST.in 递归兜底。
"""

from __future__ import annotations

import glob
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 四类代表性路径：目录说明、包声明、包根文档、三层深的页面。
_REPRESENTATIVE_PATHS = (
    "scenarios/README.md",
    "scenarios/example-pack/scenario.yaml",
    "scenarios/example-pack/walkthrough.md",
    "scenarios/example-pack/pages/index.html",
    "scenarios/example-pack/pages/sub/page.html",
    "scenarios/example-pack/pages/a/b/c.html",
)


def test_package_data_patterns_cover_pack_paths(tmp_path: Path) -> None:
    """pyproject 的 package-data 模式集合必须覆盖全部代表性路径。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["reachscope_workbench"]
    assert "scenarios/**" in patterns, "包内任意深度资源必须递归打包"
    for relative in _REPRESENTATIVE_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("probe", encoding="utf-8")
    matched = {Path(path).relative_to(tmp_path).as_posix()
               for pattern in patterns for path in glob.glob(str(tmp_path / pattern), recursive=True)}
    for relative in _REPRESENTATIVE_PATHS:
        assert relative in matched, relative


def test_manifest_recursively_includes_scenario_tree() -> None:
    """sdist 打包走 MANIFEST.in：必须递归包含整个 scenarios 目录。"""
    text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include src/reachscope_workbench/scenarios" in text


def test_gitattributes_pins_build_artifacts_to_lf() -> None:
    """构建产物 .js 必须钉死 LF，防止 autocrlf 在 checkout 时把工作树改成 CRLF。"""
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert any(" ".join(line.split()) == "*.js text eol=lf" for line in lines)


def test_builtin_packs_load_clean() -> None:
    """随仓库分发的三个内置包必须被真实 loader 全量加载：0 issue、id 与目录一致。"""
    from reachscope_workbench.api.app import BUILTIN_SCENARIOS
    from reachscope_workbench.core.scenarios.loader import ScenarioLoader

    catalog = ScenarioLoader([BUILTIN_SCENARIOS]).discover()
    assert catalog.issues == ()
    assert set(catalog.packs) == {"missing-headers", "cookie-flags", "csrf-token"}
    for pack_id, loaded in catalog.packs.items():
        assert loaded.root.name == pack_id, "目录名必须与包 id 一致"
        assert loaded.pack.limits, "每个内置包都应自带边界自述"
        assert (loaded.root / "walkthrough.md").is_file()
