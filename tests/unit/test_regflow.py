"""T3.1 单测：§6.1 的 6 类标签、move-object 传播、跨方法一层、超限 → unknown。

另外两条是本卡的**工程验收**（用户硬要求）：
- `extract/regtrace.py` 已经不存在（不存在两份寄存器回溯实现，D-056）
- `extract/` 的四张卡（webview / bridge / origin / sinks）确实走到 `graph/regflow.py`
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from reachscope.extract.bridge import extract_bridges
from reachscope.extract.origin import collect_origin_checks
from reachscope.extract.sinks import scan_method_sinks
from reachscope.extract.webview import extract_webviews
from reachscope.graph import regflow
from reachscope.graph.regflow import Tag, TagKind
from reachscope.ingest.smali import MethodInfo, SmaliIndex, index_smali_file, parse_smali_file

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"

TAGS = "Lcom/example/app/RegflowTags;"
MOVE = "Lcom/example/app/RegflowMove;"
CALLEE = "Lcom/example/app/RegflowCallee;"


def index_of(*names: str) -> SmaliIndex:
    """把若干 fixture 组装成一个索引。"""
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def method_of(index: SmaliIndex, descriptor: str, name_with_signature: str) -> MethodInfo:
    class_info = index.get_class(descriptor)
    assert class_info is not None, descriptor
    method = class_info.method(name_with_signature)
    assert method is not None, name_with_signature
    return method


def returned_tag(index: SmaliIndex, descriptor: str, name_with_signature: str) -> Tag:
    """方法返回值的标签（跨方法跟进开启）。"""
    method = method_of(index, descriptor, name_with_signature)
    return regflow.return_tag(method, regflow.propagate(method, smali=index).tags)


# --- 6 类标签各一条 -------------------------------------------------------


@pytest.mark.parametrize(
    ("method_name", "signature", "expected_kind", "expected_value"),
    [
        ("fromConst", "()Ljava/lang/String;", TagKind.CONST, "https://example.com"),
        (
            "fromIntentData",
            "(Landroid/content/Intent;)Ljava/lang/String;",
            TagKind.INTENT_DATA,
            "",
        ),
        (
            "fromIntentExtra",
            "(Landroid/content/Intent;)Ljava/lang/String;",
            TagKind.INTENT_EXTRA,
            "url",
        ),
        (
            "fromDeeplinkParam",
            "(Landroid/net/Uri;)Ljava/lang/String;",
            TagKind.DEEPLINK_PARAM,
            "next",
        ),
        ("fromField", "()Ljava/lang/String;", TagKind.FIELD, "url"),
        ("fromCallResult", "()Ljava/lang/String;", TagKind.CONST, "built"),
        ("fromUnknown", "(Ljava/lang/String;)Ljava/lang/String;", TagKind.UNKNOWN, ""),
    ],
)
def test_tag_kinds(
    method_name: str,
    signature: str,
    expected_kind: TagKind,
    expected_value: str,
) -> None:
    index = index_of("RegflowTags.smali")
    tag = returned_tag(index, TAGS, f"{method_name}{signature}")
    assert tag.kind is expected_kind
    assert tag.value == expected_value
    assert tag.incomplete is False


def test_call_result_without_index_is_call_result() -> None:
    """不给 `smali` 索引就不做跨方法跟进 → §6.1 规则 3 的 `call_result`（不是未知）。"""
    index = index_of("RegflowTags.smali")
    method = method_of(index, TAGS, "fromCallResult()Ljava/lang/String;")
    result = regflow.propagate(method)
    assert result.tag_of("v0").kind is TagKind.CALL_RESULT
    assert result.tag_of("v0").value == f"{TAGS}->build()Ljava/lang/String;"


def test_framework_call_stays_call_result() -> None:
    """框架方法（不在 APK 里）→ `call_result`，且**不算**证据不完整。"""
    index = index_of("RegflowTags.smali")
    method = method_of(index, TAGS, "fromCallResult()Ljava/lang/String;")
    without = regflow.propagate(method, smali=SmaliIndex())
    assert without.tag_of("v0").kind is TagKind.CALL_RESULT
    assert without.incomplete is False


def test_attacker_controlled_property() -> None:
    """`attacker_controlled` 只认 intent / 深链参数三类（T3.4 的 J4-4b 用）。"""
    assert Tag(TagKind.INTENT_DATA).attacker_controlled is True
    assert Tag(TagKind.INTENT_EXTRA).attacker_controlled is True
    assert Tag(TagKind.DEEPLINK_PARAM).attacker_controlled is True
    assert Tag(TagKind.CONST).attacker_controlled is False
    assert Tag(TagKind.UNKNOWN).attacker_controlled is False


# --- 规则 2：move-object 传播 ---------------------------------------------


def test_move_object_copies_tag() -> None:
    index = index_of("RegflowMove.smali")
    method = method_of(index, MOVE, "move(Landroid/content/Intent;)Ljava/lang/String;")
    result = regflow.propagate(method, smali=index)
    assert result.tag_of("v1").kind is TagKind.INTENT_DATA
    assert result.tag_of("v0").kind is TagKind.INTENT_DATA


def test_tag_of_missing_register_is_unknown() -> None:
    """从没赋过值的寄存器 → `unknown`，不用空标签冒充。"""
    result = regflow.FlowResult(tags={})
    assert result.tag_of("v9").kind is TagKind.UNKNOWN
    assert result.tag_of(None).kind is TagKind.UNKNOWN


# --- 跨方法：只跟进一层 ---------------------------------------------------


def test_cross_method_one_level() -> None:
    """host 调 `make()`（≤80 指令）→ 进入一层，把 `const("callee")` 带回。"""
    index = index_of("RegflowCallee.smali")
    tag = returned_tag(index, CALLEE, "host()Ljava/lang/String;")
    # host → viaMake 是一层，viaMake → make 是第二层
    assert tag.kind is TagKind.UNKNOWN
    assert tag.incomplete is True  # 超过一层


def test_cross_method_direct_small_callee() -> None:
    """直接调 `make()` → 一层之内，拿到 `const("callee")`。"""
    index = index_of("RegflowCallee.smali")
    method = method_of(index, CALLEE, "viaMake()Ljava/lang/String;")
    result = regflow.propagate(method, smali=index)
    assert result.tag_of("v0").kind is TagKind.CONST
    assert result.tag_of("v0").value == "callee"
    assert result.incomplete is False


def test_cross_method_limit_is_eighty_instructions(tmp_path: Path) -> None:
    """目标方法体 > 80 条指令 → `unknown` + `incomplete`（§6.1 原文）。"""
    assert regflow.MAX_CROSS_METHOD_INSTRUCTIONS == 80
    assert regflow.MAX_CROSS_METHOD_DEPTH == 1

    body = "\n".join(f"    const-string v{index % 8}, \"x\"" for index in range(90))
    source = (
        ".class public Lcom/example/app/BigCallee;\n"
        ".super Ljava/lang/Object;\n\n"
        ".method public static make()Ljava/lang/String;\n"
        "    .locals 8\n\n"
        f"{body}\n"
        "    const-string v0, \"big\"\n"
        "    return-object v0\n"
        ".end method\n\n"
        ".method public static host()Ljava/lang/String;\n"
        "    .locals 1\n\n"
        "    invoke-static {}, Lcom/example/app/BigCallee;->make()Ljava/lang/String;\n"
        "    move-result-object v0\n"
        "    return-object v0\n"
        ".end method\n"
    )
    path = tmp_path / "BigCallee.smali"
    path.write_text(source, encoding="utf-8")

    index = SmaliIndex()
    index_smali_file(index, path, base_dir=tmp_path)
    callee = index.get_class("Lcom/example/app/BigCallee;")
    assert callee is not None
    big = callee.method("make()Ljava/lang/String;")
    assert big is not None
    assert len(big.instructions) > regflow.MAX_CROSS_METHOD_INSTRUCTIONS

    host = callee.method("host()Ljava/lang/String;")
    assert host is not None
    result = regflow.propagate(host, smali=index)
    assert result.tag_of("v0").kind is TagKind.UNKNOWN
    assert result.tag_of("v0").incomplete is True
    assert result.incomplete is True


def test_tag_at_and_stop_index() -> None:
    """`tag_at` 只看到 `index` 之前的指令（T3.4/T3.5 按位置查标签用）。"""
    index = index_of("RegflowTags.smali")
    method = method_of(index, TAGS, "fromConst()Ljava/lang/String;")
    assert regflow.tag_at(method, 0, "v0", smali=index).kind is TagKind.UNKNOWN
    assert regflow.tag_at(method, 1, "v0", smali=index).kind is TagKind.CONST


# --- 工程验收：不存在两份实现 ---------------------------------------------


def test_regtrace_module_is_deleted() -> None:
    """M2 的 `extract/regtrace.py` 必须已经不存在（D-056）。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("reachscope.extract.regtrace")


def test_extract_callers_go_through_regflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch `regflow.parse_invoke`，断言 extract 四张卡确实走到它。

    调用方一律用 `regflow.xxx(...)` 的**模块属性访问**（不是 `from ... import xxx`），
    所以 monkeypatch 能拦到；拦不到就说明有人绕过了 regflow 自己实现了一份。
    """
    original = regflow.parse_invoke
    counter = {"n": 0}

    def counting(instruction: object) -> object:
        counter["n"] += 1
        return original(instruction)  # type: ignore[arg-type]

    monkeypatch.setattr(regflow, "parse_invoke", counting)

    index = index_of("SinksAll.smali", "JsBridge.smali", "WebViewCallsites.smali")
    method = method_of(index, "Lcom/example/app/SinkHostActivity;", "sinkAll()V")

    counter["n"] = 0
    extract_webviews(index)
    assert counter["n"] > 0, "extract_webviews 没走 regflow.parse_invoke"

    counter["n"] = 0
    extract_bridges(index, [])
    assert counter["n"] > 0, "extract_bridges 没走 regflow.parse_invoke"

    counter["n"] = 0
    collect_origin_checks(index)
    assert counter["n"] > 0, "collect_origin_checks 没走 regflow.parse_invoke"

    counter["n"] = 0
    scan_method_sinks(method, package="com.example.app")
    assert counter["n"] > 0, "scan_method_sinks 没走 regflow.parse_invoke"


def test_regflow_has_no_reference_to_extract() -> None:
    """`graph` 是 `extract` 的下层：regflow 里不许出现对 extract 的引用。"""
    source = (Path(regflow.__file__).parent / "regflow.py").read_text(encoding="utf-8")
    assert "extract" not in source.replace("extract/", "").replace("extract/", "")


def test_parse_smali_file_still_counts_zero_unknown_for_fixtures() -> None:
    """新增 fixture 本身不能有未知语法（否则会污染 §9.2 的 warnings）。"""
    for name in ("RegflowTags.smali", "RegflowMove.smali", "RegflowCallee.smali"):
        _, warnings, unknown = parse_smali_file(SMALI / name)
        assert unknown == 0, f"{name} 有 {unknown} 行未知语法"
        assert warnings == []


# --- M1：跨分支复用寄存器时按到达定义取 key -------------------------------


def test_dominating_constant_ignores_other_branch_definition() -> None:
    index = SmaliIndex()
    index_smali_file(
        index,
        SMALI / "com" / "example" / "app" / "M1BranchKey.smali",
        base_dir=FIXTURES,
    )
    class_info = index.get_class("Lcom/example/app/M1BranchKey;")
    assert class_info is not None
    method = class_info.methods[0]
    site = next(
        invoke
        for instruction in method.instructions
        if (invoke := regflow.parse_invoke(instruction)) is not None
        and invoke.method == "putExtra"
    )
    # 另一个分支把 v2 改成 "grant" 并跳走，到不了这里；线性扫描会误取 "grant"。
    assert regflow.dominating_constant(method, site.index, "v2") == "url"


def test_dominating_constant_returns_none_when_no_definition() -> None:
    index = SmaliIndex()
    index_smali_file(
        index,
        SMALI / "com" / "example" / "app" / "M1BranchKey.smali",
        base_dir=FIXTURES,
    )
    class_info = index.get_class("Lcom/example/app/M1BranchKey;")
    assert class_info is not None
    method = class_info.methods[0]
    site = next(
        invoke
        for instruction in method.instructions
        if (invoke := regflow.parse_invoke(instruction)) is not None
        and invoke.method == "putExtra"
    )
    assert regflow.dominating_constant(method, site.index, "v9") is None
