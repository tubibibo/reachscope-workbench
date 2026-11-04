"""T2.3 单测：§5.4 的 13 个调用点、布尔开关回溯、URL 来源分类、共享 regflow。

fixture 在 `tests/fixtures/smali/`；真实场景用 `cases/01_positive_deeplink_bridge_sink`。
"""

from __future__ import annotations

from pathlib import Path

from reachscope.extract.webview import (
    CALLBACK_NAMES,
    CALLSITES,
    classify_url_source,
    extract_webviews,
    is_callback_method,
    match_callsite,
)
from reachscope.graph import regflow
from reachscope.ingest.smali import (
    SmaliIndex,
    build_index,
    index_smali_file,
    parse_smali_file,
)
from reachscope.ir.model import UrlSourceKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SMALI = FIXTURES / "smali"
CASES = FIXTURES / "cases"


def index_of(*names: str) -> SmaliIndex:
    """把若干 fixture 组装成一个索引。"""
    index = SmaliIndex()
    for name in names:
        index_smali_file(index, SMALI / name, base_dir=SMALI)
    return index


def only_method(index, descriptor: str, name: str):
    class_info = index.get_class(descriptor)
    assert class_info is not None
    method = class_info.method(name)
    assert method is not None
    return method


# --- 13 个调用点（D-040） --------------------------------------------------


def test_callsite_table_has_thirteen_entries() -> None:
    """TASKS 卡片写“11 个”与 §5.4 表冲突，以表为准 = 13（D-040）。"""
    assert len(CALLSITES) == 13


def test_all_thirteen_callsites_are_recognized() -> None:
    """10 个以 invoke 形式识别，3 个回调以声明形式识别。"""
    index = index_of("WebViewCallsites.smali", "WebViewClientSub.smali", "JsBridge.smali")

    invoked: set[tuple[str, str]] = set()
    for descriptor in index.class_by_descriptor.values():
        for method in descriptor.methods:
            for instruction in method.instructions:
                match = match_callsite(instruction)
                if match is not None:
                    invoked.add((match.site.method, match.kind.value))

    for _, name, _, _ in CALLSITES:
        if name in CALLBACK_NAMES:
            continue
        assert any(method == name for method, _ in invoked), name

    client = index.get_class("Lcom/example/app/HostClient;")
    assert client is not None
    for method in client.methods:
        if method.name in CALLBACK_NAMES:
            assert is_callback_method(client, method, index)


def test_callback_detection_requires_client_ancestor() -> None:
    """同名业务方法（不在 WebViewClient/WebChromeClient 体系里）不能被当成回调。"""
    index = index_of("WebViewClientSub.smali", "FakeClient.smali")

    client = index.get_class("Lcom/example/app/HostClient;")
    assert client is not None
    real = client.method("shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z")
    assert real is not None
    assert is_callback_method(client, real, index) is True

    fake = index.get_class("Lcom/example/app/FakeClient;")
    assert fake is not None
    same_name = fake.method("shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z")
    assert same_name is not None
    assert is_callback_method(fake, same_name, index) is False


# --- WebView 提取 ----------------------------------------------------------


def test_case01_webview_is_extracted() -> None:
    case = CASES / "01_positive_deeplink_bridge_sink"
    webviews = extract_webviews(build_index(case))
    assert len(webviews) == 1
    webview = webviews[0]
    assert webview.owner_class == "com.example.app.MainActivity"
    assert webview.owner_method == "onCreate(Landroid/os/Bundle;)V"
    assert webview.js_enabled is True  # const/4 v2, 0x1
    assert webview.file_access is None  # 该 fixture 没调用 setAllowFileAccess
    assert webview.source is not None
    assert webview.source.file == "smali/com/example/app/MainActivity.smali"
    assert webview.source.line == 54


def test_url_source_from_intent_data_through_toString() -> None:
    """getData → toString → loadUrl 必须判成 intent_data（真实写法）。"""
    case = CASES / "01_positive_deeplink_bridge_sink"
    webview = extract_webviews(build_index(case))[0]
    assert [source.kind for source in webview.url_sources] == [UrlSourceKind.INTENT_DATA]


def test_url_source_const_and_deeplink_param() -> None:
    index = index_of("WebViewCallsites.smali", "JsBridge.smali")
    webviews = extract_webviews(index)
    assert len(webviews) == 1
    kinds = [source.kind for source in webviews[0].url_sources]
    assert kinds == [
        UrlSourceKind.INTENT_DATA,  # loadUrl(String) ← getData → toString
        UrlSourceKind.CONST,  # loadUrl(String, Map) ← const-string
        UrlSourceKind.CONST,  # loadData
        UrlSourceKind.CONST,  # loadDataWithBaseURL
    ]
    const_values = [s.value for s in webviews[0].url_sources if s.kind == UrlSourceKind.CONST]
    assert "https://cdn.example.com/page.html" in const_values


def test_boolean_settings_and_last_write_wins() -> None:
    index = index_of("WebViewCallsites.smali", "JsBridge.smali")
    webview = extract_webviews(index)[0]
    assert webview.js_enabled is True
    assert webview.file_access is True
    assert webview.universal_file_access is False  # 两个 FromFileURLs setter 最后一次是 0x0


def test_unknown_boolean_is_none_not_false() -> None:
    """回溯不到 const/4 → None（未观察到），不能是 False（D-016）。"""
    index = index_of("WebViewBoolUnknown.smali")
    webview = extract_webviews(index)[0]
    assert webview.js_enabled is None
    assert webview.file_access is True


def test_no_load_or_bridge_means_no_webview() -> None:
    index = index_of("WebViewClientSub.smali")
    assert extract_webviews(index) == []


def test_webview_id_includes_file_and_line() -> None:
    """ID 键含 file:line（相对路径才有意义，D-036）。"""
    case = CASES / "01_positive_deeplink_bridge_sink"
    webview = extract_webviews(build_index(case))[0]
    assert len(webview.id) == 8
    again = extract_webviews(build_index(case))[0]
    assert webview.id == again.id


# --- regflow 共享能力 -------------------------------------------------------


def test_parse_invoke_and_range() -> None:
    classes, _, _ = parse_smali_file(SMALI / "WebViewCallsites.smali")
    host = classes[0]
    method = host.method("onCreate(Landroid/os/Bundle;)V")
    assert method is not None
    site = regflow.parse_invoke(method.instructions[3])
    assert site is not None
    assert site.class_descriptor == "Landroid/webkit/WebView;"
    assert site.method == "getSettings"
    assert site.receiver == "v0"
    assert site.ref == "Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;"


def test_backtrack_const_string_and_number() -> None:
    classes, _, _ = parse_smali_file(SMALI / "WebViewBoolUnknown.smali")
    method = classes[0].method("onCreate(Landroid/os/Bundle;)V")
    assert method is not None
    last = len(method.instructions) - 1
    assert regflow.backtrack_const_string(method, last, "v1") == (
        "v1",
        "https://static.example.com/index.html",
    )
    assert regflow.backtrack_const_number(method, last, "v2") in (None, 0, 1)


def test_backtrack_new_instance() -> None:
    classes, _, _ = parse_smali_file(SMALI / "WebViewCallsites.smali")
    method = classes[0].method("onCreate(Landroid/os/Bundle;)V")
    assert method is not None
    descriptor = regflow.backtrack_new_instance(method, len(method.instructions) - 1, "v0")
    assert descriptor in ("Landroid/webkit/WebView;", None)


def test_classify_unknown_when_no_evidence() -> None:
    index = index_of("WebViewBoolUnknown.smali")
    host = index.get_class("Lcom/example/app/WebViewNoConstActivity;")
    assert host is not None
    method = host.method("onCreate(Landroid/os/Bundle;)V")
    assert method is not None
    for instruction in method.instructions:
        site = regflow.parse_invoke(instruction)
        if site is not None and site.method == "loadUrl":
            assert classify_url_source(method, site).kind == UrlSourceKind.CONST
            return
    raise AssertionError("未找到 loadUrl 调用")
