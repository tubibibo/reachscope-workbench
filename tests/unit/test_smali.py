"""T1.3 单测：smali 行级解析、多 dex 合并、.line、注解、未知语法计数。

fixture 在 `tests/fixtures/smali/`，多 dex 场景用 tmp_path 搭目录，不依赖 apktool。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from reachscope.ingest.smali import (
    Instruction,
    SmaliIndex,
    build_index,
    index_smali_file,
    method_key,
    param_register_count,
    parse_smali_file,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "smali"


def fixture(name: str) -> Path:
    return FIXTURES / name


def index_of(name: str) -> SmaliIndex:
    """把单个 fixture 解析成索引。"""
    index = SmaliIndex()
    index_smali_file(index, fixture(name), base_dir=FIXTURES)
    return index


def build_workdir(tmp_path: Path, mapping: dict[str, list[str]]) -> Path:
    """搭一个 apktool 解码产物布局：`{dex_dir: [fixture 文件名]}`。"""
    workdir = tmp_path / "work"
    for dex_dir, names in mapping.items():
        target = workdir / dex_dir
        target.mkdir(parents=True)
        for name in names:
            shutil.copy(fixture(name), target / name)
    return workdir


# --- 单文件解析 -----------------------------------------------------------


def test_class_header_and_access_flags() -> None:
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    assert len(classes) == 1
    info = classes[0]
    assert info.descriptor == "Lcom/example/app/Sample;"
    assert info.super_name == "Ljava/lang/Object;"
    assert info.interfaces == ("Landroid/view/View$OnClickListener;",)
    assert info.access == ("public",)
    assert info.source.line == 1
    assert ".class" in info.source.snippet


def test_method_with_registers_directive() -> None:
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("onClick(Landroid/view/View;)V")
    assert method is not None
    assert method.name == "onClick"
    assert method.signature == "(Landroid/view/View;)V"
    assert method.registers == 2
    assert method.source.line > 0
    assert method.access == ("public",)


def test_locals_only_registers_are_derived() -> None:
    """.locals 掣导：locals + 参数寄存器（静态无 this）。"""
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("make(Ljava/lang/String;)Ljava/lang/String;")
    assert method is not None
    assert method.registers == 2  # .locals 1 + 1 个 String 参数（静态方法无 this）


def test_locals_derivation_counts_wide_params_and_this() -> None:
    """`concrete(J)V`：.registers 4 显式声明（this + wide 参数）；直接验证推导函数。"""
    assert param_register_count("J", is_static=False) == 3
    assert param_register_count("J", is_static=True) == 2
    assert param_register_count("Ljava/lang/String;I", is_static=False) == 3
    assert param_register_count("[J", is_static=True) == 1
    assert param_register_count("", is_static=False) == 1
    assert param_register_count("", is_static=True) == 0


def test_line_directive_binds_to_following_instructions() -> None:
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("onClick(Landroid/view/View;)V")
    assert method is not None
    lines = [instruction.line for instruction in method.instructions]
    # .line 12 → getContext；12 → move-result（继承当前行）；13 → startActivity；13 → return-void
    assert lines == [12, 12, 13, 13]


def test_instruction_index_opcode_and_operands() -> None:
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("onClick(Landroid/view/View;)V")
    assert method is not None
    first = method.instructions[0]
    assert isinstance(first, Instruction)
    assert first.index == 0
    assert first.opcode == "invoke-virtual"
    assert first.operands_raw == (
        "{p1}, Landroid/view/View;->getContext()Landroid/content/Context;"
    )
    assert first.file_line > 0


def test_hash_inside_string_is_not_a_comment() -> None:
    """`#` 前无空白不算注释，URL 里的锚点必须原样保留。"""
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("make(Ljava/lang/String;)Ljava/lang/String;")
    assert method is not None
    const = next(
        instruction
        for instruction in method.instructions
        if instruction.opcode == "const-string"
    )
    assert '"https://example.com/#/page"' in const.operands_raw


def test_trailing_comment_is_stripped() -> None:
    classes, _, _ = parse_smali_file(fixture("Sample.smali"))
    method = classes[0].method("onClick(Landroid/view/View;)V")
    assert method is not None
    move = next(
        instruction for instruction in method.instructions if instruction.opcode == "move-result-object"
    )
    assert "#" not in move.operands_raw


def test_runtime_annotation_on_method() -> None:
    classes, _, _ = parse_smali_file(fixture("JsBridge.smali"))
    method = classes[0].method("readFile(Ljava/lang/String;)Ljava/lang/String;")
    assert method is not None
    assert method.has_annotation("Landroid/webkit/JavascriptInterface;")
    annotation = method.annotations[0]
    assert annotation.visibility == "runtime"
    assert annotation.type == "Landroid/webkit/JavascriptInterface;"


def test_class_level_annotation() -> None:
    classes, _, _ = parse_smali_file(fixture("JsBridge.smali"))
    assert len(classes[0].annotations) == 1
    assert classes[0].annotations[0].type == "Ldagger/internal/GeneratedComponent;"


def test_abstract_method_has_no_instructions() -> None:
    classes, _, _ = parse_smali_file(fixture("AbstractBase.smali"))
    info = classes[0]
    assert info.is_abstract is True
    abstract_method = info.method("doWork()V")
    assert abstract_method is not None
    assert "abstract" in abstract_method.access
    assert abstract_method.instructions == ()


# --- 未知语法与健壮性 ------------------------------------------------------


def test_unknown_syntax_is_counted_not_fatal() -> None:
    index = index_of("BadSyntax.smali")
    # .bogus-directive / .weird-directive / stray-instruction 三行
    assert any("3 行未知语法" in warning for warning in index.warnings)
    assert index.class_count == 1


def test_try_catch_and_switch_blocks_are_known_syntax() -> None:
    """.catch / .catchall / .end packed-switch 都是合法 smali，计数必须 0（D-055）。"""
    classes, warnings, unknown = parse_smali_file(fixture("TryCatch.smali"))
    assert unknown == 0
    assert warnings == []
    assert len(classes) == 1
    assert [m.name for m in classes[0].methods] == ["<init>", "load", "pick", "copy"]


def test_parse_errors_are_reported_not_raised(tmp_path: Path) -> None:
    missing = tmp_path / "Missing.smali"
    classes, warnings, unknown = parse_smali_file(missing)
    assert classes == []
    assert warnings and "Missing.smali" in warnings[0]
    assert unknown == 0


# --- 索引与多 dex ----------------------------------------------------------


def test_build_index_merges_multiple_dex_dirs(tmp_path: Path) -> None:
    workdir = build_workdir(
        tmp_path,
        {"smali": ["Sample.smali", "JsBridge.smali"], "smali_classes2": ["AbstractBase.smali"]},
    )
    index = build_index(workdir)
    assert index.class_count == 3
    assert index.get_class("Lcom/example/app/Sample;") is not None
    assert index.get_class("Lcom/example/app/AbstractBase;") is not None
    assert index.method_count == 5


def test_find_method_by_full_reference(tmp_path: Path) -> None:
    workdir = build_workdir(tmp_path, {"smali": ["JsBridge.smali"]})
    index = build_index(workdir)
    method = index.find_method("Lcom/example/app/JsBridge;->readFile(Ljava/lang/String;)Ljava/lang/String;")
    assert method is not None
    assert method.registers == 4  # .locals 2 + this 1 + String 参数 1
    assert index.find_method("Lcom/example/app/JsBridge;->nope()V") is None


def test_duplicate_class_keeps_first_and_warns(tmp_path: Path) -> None:
    workdir = build_workdir(tmp_path, {"smali": ["DupA.smali"], "smali_classes2": ["DupB.smali"]})
    index = build_index(workdir)
    assert index.class_count == 1
    kept = index.get_class("Lcom/example/app/Duplicate;")
    assert kept is not None
    assert kept.method("first()V") is not None
    assert kept.method("second()V") is None
    assert any("类名冲突" in warning for warning in index.warnings)


def test_method_key_format() -> None:
    index = index_of("Sample.smali")
    sample = index.get_class("Lcom/example/app/Sample;")
    assert sample is not None
    method = sample.method("onClick(Landroid/view/View;)V")
    assert method is not None
    assert method_key("Lcom/example/app/Sample;", method) == (
        "Lcom/example/app/Sample;->onClick(Landroid/view/View;)V"
    )


# --- 性能 ------------------------------------------------------------------


def test_ten_thousand_lines_under_two_seconds(tmp_path: Path) -> None:
    """PLAN §10.1 级别的性能要求：10k 行解析 < 2s（TASKS T1.3 验收）。"""
    big = tmp_path / "Big.smali"
    lines = [".class public Lcom/example/app/Big;", ".super Ljava/lang/Object;"]
    for i in range(600):
        lines.append(f".method public m{i}()V")
        lines.append("    .registers 2")
        for j in range(15):
            lines.append(f"    const-string v0, \"value-{i}-{j}\"")
        lines.append("    return-void")
        lines.append(".end method")
    big.write_text("\n".join(lines), encoding="utf-8")
    assert len(lines) > 10000

    started = time.perf_counter()
    index = SmaliIndex()
    index_smali_file(index, big)
    elapsed = time.perf_counter() - started
    assert index.method_count == 600
    assert elapsed < 2.0
