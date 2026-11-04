"""T2.1 单测：类名规范化、实现存在性（含 activity-alias）、SourceLoc 相对路径。

不依赖 apktool：manifest 用 `tests/fixtures/manifests/`，
smali 用 `tests/fixtures/cases/03_missing_impl` 的真实产物，抽象链在 tmp_path 里生成。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reachscope.extract.components import (
    REASON_NO_CONCRETE,
    REASON_NOT_FOUND,
    class_name_of,
    descriptor_of,
    has_concrete_implementation,
    normalize_class_name,
    resolve_components,
)
from reachscope.ingest.manifest import ManifestInfo, parse_manifest
from reachscope.ingest.smali import build_index
from reachscope.ir.model import Component, ComponentType

CASES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"
MANIFESTS = Path(__file__).resolve().parent.parent / "fixtures" / "manifests"
PACKAGE = "com.example.app"


def write_smali(root: Path, rel: str, text: str) -> None:
    """在解码目录里写一个 smali 文件（一个文件只能有一个 `.class`，见 smali.py）。"""
    path = root / "smali" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def class_smali(descriptor: str, super_name: str, flags: str = "public", extra: str = "") -> str:
    """生成最小类声明（够 `impl_present` 判定用，不参与编译）。"""
    head = f".class {flags} {descriptor}\n.super {super_name}\n"
    if extra:
        head += f"{extra}\n"
    return head


@pytest.fixture
def abstract_workdir(tmp_path: Path) -> Path:
    """抽象基类/接口/具体子类/隔层继承/孤儿接口 齐全的解码目录。"""
    root = tmp_path / "work"
    write_smali(
        root,
        "com/example/app/AbstractBaseActivity.smali",
        class_smali("Lcom/example/app/AbstractBaseActivity;", "Landroid/app/Activity;",
                    flags="public abstract"),
    )
    write_smali(
        root,
        "com/example/app/ConcreteActivity.smali",
        class_smali("Lcom/example/app/ConcreteActivity;",
                    "Lcom/example/app/AbstractBaseActivity;"),
    )
    write_smali(
        root,
        "com/example/app/MiddleActivity.smali",
        class_smali("Lcom/example/app/MiddleActivity;", "Lcom/example/app/AbstractBaseActivity;",
                    flags="public abstract"),
    )
    write_smali(
        root,
        "com/example/app/DeepActivity.smali",
        class_smali("Lcom/example/app/DeepActivity;", "Lcom/example/app/MiddleActivity;"),
    )
    write_smali(
        root,
        "com/example/app/OnPage.smali",
        class_smali("Lcom/example/app/OnPage;", "Ljava/lang/Object;",
                    flags="public abstract interface"),
    )
    write_smali(
        root,
        "com/example/app/PageImpl.smali",
        class_smali("Lcom/example/app/PageImpl;", "Ljava/lang/Object;",
                    extra=".implements Lcom/example/app/OnPage;"),
    )
    write_smali(
        root,
        "com/example/app/Orphan.smali",
        class_smali("Lcom/example/app/Orphan;", "Ljava/lang/Object;",
                    flags="public abstract interface"),
    )
    write_smali(
        root,
        "com/example/app/AbstractOnlyActivity.smali",
        class_smali("Lcom/example/app/AbstractOnlyActivity;", "Landroid/app/Activity;",
                    flags="public abstract"),
    )
    write_smali(
        root,
        "com/example/app/AbstractMiddleActivity.smali",
        class_smali("Lcom/example/app/AbstractMiddleActivity;",
                    "Lcom/example/app/AbstractOnlyActivity;", flags="public abstract"),
    )
    return root


# --- 类名规范化（D-034） ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".MainActivity", "com.example.app.MainActivity"),
        ("MainActivity", "com.example.app.MainActivity"),
        ("com.other.Foo", "com.other.Foo"),
        (".Outer$Inner", "com.example.app.Outer$Inner"),
        ("Outer$Inner", "com.example.app.Outer$Inner"),
    ],
)
def test_normalize_class_name_forms(raw: str, expected: str) -> None:
    assert normalize_class_name(raw, PACKAGE) == expected


def test_normalize_class_name_without_package_keeps_original() -> None:
    """package 为空时无法规范化，原样返回（不猜）。"""
    assert normalize_class_name(".MainActivity", "") == ".MainActivity"
    assert normalize_class_name("MainActivity", "") == "MainActivity"


def test_descriptor_round_trip() -> None:
    assert descriptor_of("com.example.app.MainActivity") == "Lcom/example/app/MainActivity;"
    assert class_name_of("Lcom/example/app/MainActivity;") == "com.example.app.MainActivity"
    assert class_name_of(descriptor_of("a.b.C$D")) == "a.b.C$D"


# --- 实现存在性：真实 fixture（03） ---------------------------------------


def test_missing_implementation_is_flagged() -> None:
    """03 fixture：manifest 声明 exported，实现类不在包里（J2 的输入）。"""
    manifest = parse_manifest(CASES / "03_missing_impl" / "AndroidManifest.xml")
    index = build_index(CASES / "03_missing_impl")
    components = resolve_components(manifest, index)

    by_name = {component.name: component for component in components}
    assert by_name["com.example.app.HiddenActivity"].impl_present is False
    assert by_name["com.example.app.HiddenActivity"].impl_reason == REASON_NOT_FOUND
    assert by_name["com.example.app.MainActivity"].impl_present is True
    assert by_name["com.example.app.MainActivity"].impl_reason is None


def test_empty_index_flags_everything() -> None:
    """没有 smali 时全部标记不存在，而不是静默 True。"""
    manifest = parse_manifest(CASES / "03_missing_impl" / "AndroidManifest.xml")
    components = resolve_components(manifest, build_index(MANIFESTS.parent / "smali"))
    assert components
    assert all(component.impl_present is False for component in components)
    assert all(component.impl_reason == REASON_NOT_FOUND for component in components)


# --- 抽象链与接口（D-033） ------------------------------------------------


def test_concrete_class_is_present(abstract_workdir: Path) -> None:
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.ConcreteActivity", index) is True


def test_abstract_with_direct_subclass_is_present(abstract_workdir: Path) -> None:
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.AbstractBaseActivity", index) is True


def test_abstract_with_transitive_subclass_is_present(abstract_workdir: Path) -> None:
    """隔一层继承（abstract → abstract → concrete）也算有实现。"""
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.MiddleActivity", index) is True


def test_interface_with_implementation_is_present(abstract_workdir: Path) -> None:
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.OnPage", index) is True


def test_abstract_without_concrete_subclass_is_flagged(abstract_workdir: Path) -> None:
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.AbstractOnlyActivity", index) is False


def test_orphan_interface_is_flagged(abstract_workdir: Path) -> None:
    index = build_index(abstract_workdir)
    assert has_concrete_implementation("com.example.app.Orphan", index) is False


def test_reason_for_abstract_without_subclass(abstract_workdir: Path) -> None:
    manifest = parse_manifest(MANIFESTS / "activity_alias.xml")
    index = build_index(abstract_workdir)
    components = resolve_components(manifest, index)
    orphan = next(c for c in components if c.name == "com.example.app.MainActivity")
    # MainActivity 在 abstract_workdir 里不存在 → 类未找到
    assert orphan.impl_present is False
    assert orphan.impl_reason == REASON_NOT_FOUND


def test_no_concrete_reason_when_only_abstract_chain_exists(tmp_path: Path) -> None:
    """只有抽象链（无具体子类）→ REASON_NO_CONCRETE，不是 NOT_FOUND（D-032）。"""
    root = tmp_path / "work"
    write_smali(
        root,
        "com/example/app/AbstractOnlyActivity.smali",
        class_smali("Lcom/example/app/AbstractOnlyActivity;", "Landroid/app/Activity;",
                    flags="public abstract"),
    )
    write_smali(
        root,
        "com/example/app/Sub.smali",
        class_smali("Lcom/example/app/Sub;", "Lcom/example/app/AbstractOnlyActivity;",
                    flags="public abstract"),
    )
    info = ManifestInfo(
        package=PACKAGE,
        components=[
            Component(name="AbstractOnlyActivity", type=ComponentType.ACTIVITY),
        ],
    )
    resolved = resolve_components(info, build_index(root))
    assert resolved[0].impl_present is False
    assert resolved[0].impl_reason == REASON_NO_CONCRETE


# --- activity-alias（D-032b） ---------------------------------------------


def test_alias_uses_target_activity() -> None:
    """alias 自身名在 APK 里没有类，必须用 targetActivity 判定。"""
    manifest = parse_manifest(MANIFESTS / "activity_alias.xml")
    index = build_index(CASES / "01_positive_deeplink_bridge_sink")
    components = resolve_components(manifest, index)

    alias = next(c for c in components if c.name == "com.example.app.LauncherAlias")
    assert alias.type.value == "activity-alias"
    assert alias.target_activity == "com.example.app.MainActivity"
    assert alias.impl_present is True  # 不再是“每条 alias 都悬空”的假阳性
    assert alias.impl_reason is None


def test_alias_without_target_activity_falls_back_and_warns() -> None:
    manifest = parse_manifest(MANIFESTS / "activity_alias.xml")
    index = build_index(CASES / "01_positive_deeplink_bridge_sink")
    before = len(manifest.warnings)
    components = resolve_components(manifest, index)

    orphan = next(c for c in components if c.name == "com.example.app.OrphanAlias")
    assert orphan.target_activity is None
    assert orphan.impl_present is False
    assert orphan.impl_reason == REASON_NOT_FOUND
    assert len(manifest.warnings) == before + 1
    assert any("未声明 android:targetActivity" in w for w in manifest.warnings)


def test_target_activity_only_on_alias() -> None:
    """非 alias 组件不持有 `target_activity`（D-032b）。"""
    manifest = parse_manifest(MANIFESTS / "all_component_types.xml")
    for component in manifest.components:
        if component.type is ComponentType.ACTIVITY_ALIAS:
            assert component.target_activity == "com.example.app.MainActivity"
        else:
            assert component.target_activity is None


# --- SourceLoc 相对路径（D-036） ------------------------------------------


def test_smali_source_loc_is_relative_posix() -> None:
    index = build_index(CASES / "01_positive_deeplink_bridge_sink")
    sources = {c.source.file for c in index.class_by_descriptor.values()}
    assert sources
    for path in sources:
        assert path.startswith("smali/"), path
        assert "\\" not in path, path
        assert not Path(path).is_absolute(), path


def test_manifest_source_loc_is_relative_filename() -> None:
    manifest = parse_manifest(CASES / "03_missing_impl" / "AndroidManifest.xml")
    assert manifest.components
    assert all(c.source is not None and c.source.file == "AndroidManifest.xml"
               for c in manifest.components)
