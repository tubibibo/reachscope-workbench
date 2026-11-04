"""评测脚本的匹配逻辑：不联网、不跑 APK，只喂合成的报告 JSON。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "benchmark" / "run_benchmark.py"
    spec = importlib.util.spec_from_file_location("reachscope_benchmark_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


benchmark = _load_script()


def _report() -> dict[str, object]:
    return {
        "meta": {"package": "com.example"},
        "components": [
            {"name": "com.example.MainActivity"},
            {"name": "com.example.OtherActivity"},
            {"name": "com.example.NoChainActivity"},
        ],
        "deeplinks": [
            {
                "scheme": "myapp",
                "host": "open.example.com",
                "path": "",
                "component": "com.example.MainActivity",
            }
        ],
        "chains": [
            {
                "id": "c1",
                "entries": ["com.example.MainActivity"],
                "evidence_complete": True,
                "steps": [{"sink": "cross_component"}, {"sink": "webview"}],
            },
            {
                "id": "c2",
                "entries": ["com.example.OtherActivity"],
                "evidence_complete": True,
                "steps": [{"sink": "file"}],
            },
        ],
        "findings": [
            {"chain_id": "c1", "title": "deeplink -> webview"},
            {"chain_id": "c2", "title": "file sink"},
        ],
    }


def test_canonical_component_names() -> None:
    assert benchmark.canonical("com.example", ".Main") == "com.example.Main"
    assert benchmark.canonical("com.example", "Main") == "com.example.Main"
    assert benchmark.canonical("com.example", "a.b.Main") == "a.b.Main"
    assert benchmark.canonical("com.example", "") == ""


def test_split_uri() -> None:
    assert benchmark.split_uri("myapp://host/path") == ("myapp", "host", "/path")
    assert benchmark.split_uri("myapp://host") == ("myapp", "host", "")
    assert benchmark.split_uri("not-a-uri") == ("", "", "")


def test_entry_components_match_deeplink_by_host() -> None:
    entry = {"kind": "deeplink", "uri": "myapp://open.example.com/webview"}
    assert benchmark.entry_components(_report(), entry) == ["com.example.MainActivity"]


def test_entry_components_match_short_component_name() -> None:
    entry = {"kind": "component", "name": ".OtherActivity"}
    assert benchmark.entry_components(_report(), entry) == ["com.example.OtherActivity"]


def test_is_subsequence() -> None:
    assert benchmark.is_subsequence(["webview"], ["cross_component", "webview"])
    assert benchmark.is_subsequence(["cross_component", "webview"], ["a", "cross_component", "webview"])
    assert not benchmark.is_subsequence(["webview", "file"], ["webview"])
    assert benchmark.is_subsequence([], ["anything"])


def test_evaluate_expectation_detected() -> None:
    expectation = {
        "id": "e1",
        "entry": {"kind": "deeplink", "uri": "myapp://open.example.com/webview"},
        "sinks": ["webview"],
    }
    result = benchmark.evaluate_expectation(_report(), expectation)
    assert result["status"] == "detected"
    assert result["matched_chain"] == "c1"


def test_evaluate_expectation_partial() -> None:
    expectation = {
        "id": "e2",
        "entry": {"kind": "deeplink", "uri": "myapp://open.example.com/webview"},
        "sinks": ["file"],
        "accept_partial": ["cross_component"],
    }
    result = benchmark.evaluate_expectation(_report(), expectation)
    assert result["status"] == "partial"
    assert result["matched_chain"] == "c1"


def test_evaluate_expectation_miss_when_entry_absent() -> None:
    expectation = {
        "id": "e3",
        "entry": {"kind": "deeplink", "uri": "other://missing/path"},
        "sinks": ["webview"],
    }
    result = benchmark.evaluate_expectation(_report(), expectation)
    assert result["status"] == "miss"
    assert "入口不在报告里" in result["detail"]


def test_evaluate_expectation_out_of_vocabulary() -> None:
    result = benchmark.evaluate_expectation(
        _report(), {"id": "e4", "sinks": ["network"], "out_of_vocabulary": True}
    )
    assert result["status"] == "out_of_vocabulary"


def test_evaluate_expectation_no_chain_ok() -> None:
    result = benchmark.evaluate_expectation(
        _report(),
        {
            "id": "n1",
            "entry": {"kind": "component", "name": ".NoChainActivity"},
            "expect_no_chain": True,
        },
    )
    assert result["status"] == "no_chain_ok"
    assert result["chain_sinks"] == []


def test_evaluate_expectation_no_chain_violation() -> None:
    result = benchmark.evaluate_expectation(
        _report(),
        {
            "id": "n2",
            "entry": {"kind": "component", "name": ".OtherActivity"},
            "expect_no_chain": True,
        },
    )
    assert result["status"] == "unexpected_chain"
    assert result["matched_chain"] == "c2"


def test_evaluate_findings_explained_and_unreviewed() -> None:
    expectations = [
        {
            "id": "e1",
            "entry": {"kind": "deeplink", "uri": "myapp://open.example.com/webview"},
            "sinks": ["webview"],
        }
    ]
    result = benchmark.evaluate_findings(_report(), expectations)
    assert result["findings"] == 2
    assert result["explained"] == 1
    assert len(result["unreviewed"]) == 1
    assert result["unreviewed"][0]["chain_id"] == "c2"


def test_summarize_counts() -> None:
    cases = [
        {
            "status": "ok",
            "expectations": [
                {"status": "detected"},
                {"status": "partial"},
                {"status": "miss"},
                {"status": "out_of_vocabulary"},
                {"status": "no_chain_ok"},
                {"status": "unexpected_chain"},
            ],
            "findings": {"findings": 3, "explained": 2},
        },
        {"status": "skipped"},
    ]
    summary = benchmark.summarize(cases)
    assert summary["cases_run"] == 1
    assert summary["expectations_in_scope"] == 3
    assert summary["detected"] == 1
    assert summary["partial"] == 1
    assert summary["miss"] == 1
    assert summary["out_of_vocabulary"] == 1
    assert summary["expect_no_chain_checks"] == 2
    assert summary["expect_no_chain_violations"] == 1
    assert summary["detection_rate"] == pytest.approx(0.333)
    assert summary["any_signal_rate"] == pytest.approx(0.667)
    assert summary["findings_unreviewed"] == 1
