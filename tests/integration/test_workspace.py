"""Public workflows, persisted code and honest offline demonstrations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reachscope.application import index_directory
from reachscope.artifacts import ArtifactError, ArtifactStore
from reachscope.cli import main
from reachscope.demo import build_demo
from reachscope.query import EvidenceSession

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "src" / "reachscope" / "samples"


def test_demo_exercises_real_queries_and_expected_boundaries(tmp_path: Path) -> None:
    result = build_demo(tmp_path / "demo")
    assert result["cases"] == result["passed"] == 5
    assert result["model_calls"] == 0
    html = (tmp_path / "demo/index.html").read_text(encoding="utf-8")
    assert "UNDECIDABLE" in html and "REFUTED" in html and "SUPPORTED" in html
    assert "https://cdn" not in html and "<script src=" not in html
    assert '<script id="case-data" type="application/json">' in html
    assert 'id="trace-svg"' in html and 'id="code-content"' in html
    assert "prefers-reduced-motion" in html
    trace = json.loads((tmp_path / "demo/traces/cross_component.json").read_text(encoding="utf-8"))
    method = next(call["result"] for call in trace if call["operation"] == "method")
    assert ".method" in method["data"]["code"]
    codes = [call["result"]["data"]["code"] for call in trace if call["operation"] == "method"]
    assert any("putExtra" in code for code in codes)
    assert any("getStringExtra" in code and "loadUrl" in code for code in codes)
    assert trace[-1]["operation"] == "check"
    verdict = next(call["result"] for call in trace if call["operation"] == "check")
    assert verdict["data"]["verdict"]["status"] == "SUPPORTED"
    assert verdict["scope"] == "static_analysis_report"


def test_same_input_reuses_artifact_without_redecoding(tmp_path: Path) -> None:
    first, _ = index_directory(SAMPLES / "cross_component", tmp_path / "store")
    second, _ = index_directory(SAMPLES / "cross_component", tmp_path / "store")
    assert first.id == second.id
    assert len(ArtifactStore(tmp_path / "store").list()) == 1
    reopened = EvidenceSession(ArtifactStore(tmp_path / "store").open(first.id))
    methods = reopened.methods("CrossTarget")
    code = reopened.method(methods["data"][0]["method_ref"])["data"]
    assert "getStringExtra" in code["code"] and "loadUrl" in code["code"]
    assert code["sha256"]


def test_index_rejects_nested_store_and_invalid_directory(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="Expected a decoded"):
        index_directory(tmp_path, tmp_path / "store")
    with pytest.raises(ArtifactError, match="outside"):
        index_directory(SAMPLES / "bridge", SAMPLES / "bridge" / "store")


def test_demo_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("user content", encoding="utf-8")
    with pytest.raises(ArtifactError, match="new or empty"):
        build_demo(tmp_path)
    assert page.read_text(encoding="utf-8") == "user content"


def test_demo_template_escapes_code_and_input_strings() -> None:
    from jinja2 import Environment, FileSystemLoader

    template_dir = ROOT / "src/reachscope/report/templates"
    template = Environment(loader=FileSystemLoader(template_dir), autoescape=True).get_template("demo.html.j2")
    malicious = '</script><script>alert("untrusted")</script>'
    html = template.render(summary={"tool_version": "test", "cases": 1, "passed": 1},
                           view_cases=[{"title": malicious}], rows=[{
        "title": '<script>alert("untrusted")</script>', "status": "UNDECIDABLE", "id": "test",
        "chains": [{"steps": [{"sink": "webview", "description": "test", "source": {
            "file": "example.smali", "line": 2, "snippet": "invoke-direct <init>"
        }}]}],
    }])
    assert '<script>alert("untrusted")</script>' not in html
    assert "&lt;script&gt;" in html and "&lt;init&gt;" in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003e" in html


def test_demo_embeds_data_safely_and_does_not_invent_negative_paths(tmp_path: Path) -> None:
    result = build_demo(tmp_path / "demo")
    html = Path(result["report"]).read_text(encoding="utf-8")
    start = html.index('<script id="case-data" type="application/json">')
    start = html.index(">", start) + 1
    views = json.loads(html[start:html.index("</script>", start)])
    assert len(views) == 5
    wrong_key = next(case for case in views if case["id"] == "wrong_key")
    assert wrong_key["has_path"] is False
    assert all(step["kind"] == "observation" for step in wrong_key["steps"])
    assert any('"note"' in step["code"] for step in wrong_key["steps"])
    assert any("getStringExtra" in step["code"] for step in wrong_key["steps"])
    missing = next(case for case in views if case["id"] == "missing")
    assert missing["steps"] == [] and not missing["has_path"]
    bridge = next(case for case in views if case["id"] == "bridge")
    assert bridge["has_path"] and all(step["kind"] == "candidate_step" for step in bridge["steps"])
    assert "\\u003cinit\\u003e" in html


def test_json_cli_end_to_end_and_error_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = str(tmp_path / "store")
    assert main(["index", str(SAMPLES / "cross_component"), "--store", store]) == 0
    indexed = json.loads(capsys.readouterr().out)
    artifact_id = indexed["artifact_id"]
    assert main(["query", artifact_id, "chains", "--store", store]) == 0
    assert json.loads(capsys.readouterr().out)["data"]
    assert main(["query", artifact_id, "chain", "--store", store]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "INVALID_ARGUMENT"
    assert main(["query", artifact_id, "entries", "--limit", "-1", "--store", store]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert main(["artifacts", "--store", store]) == 0
    assert len(json.loads(capsys.readouterr().out)["artifacts"]) == 1
    assert main(["doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["model_api_required"] is False


def test_cli_help_and_subprocess_stdout_are_machine_readable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "reachscope", "doctor"],
        text=True, capture_output=True, encoding="utf-8", check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["offline_demo"] is True


def test_help_is_utf8_even_with_an_ascii_console() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "reachscope", "--help"],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "代码证据" in completed.stdout.decode("utf-8")


def test_check_and_method_queries_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact, _ = index_directory(SAMPLES / "cross_component", tmp_path / "store")
    base = ["query", artifact.id]
    store = ["--store", str(tmp_path / "store")]
    session = EvidenceSession(artifact)
    ref = session.methods()["data"][0]["reference"]
    assert main([*base, "method", "--ref", ref, "--limit", "2", *store]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["truncated"]
    claim = tmp_path / "claim.json"
    claim.write_text(json.dumps({
        "schema_version": "0.2", "kind": "reachability",
        "entry": {"kind": "component", "name": "com.example.app.CrossEntry"},
        "sink": {"kind": "webview"},
    }), encoding="utf-8")
    assert main([*base, "check", "--claim", str(claim), *store]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["verdict"]["status"] == "SUPPORTED"
    claim.write_text("[]", encoding="utf-8")
    assert main([*base, "check", "--claim", str(claim), *store]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
