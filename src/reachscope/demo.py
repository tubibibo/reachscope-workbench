"""A reproducible source-only walkthrough. It makes no model or accuracy claims."""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ._version import __version__
from .application import index_directory
from .artifacts import ArtifactError
from .query import EvidenceSession


def _save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_demo(output: Path) -> dict[str, Any]:
    """Analyze bundled snippets and save a browseable report plus actual call results."""
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ArtifactError("OUTPUT_NOT_EMPTY", "Demo output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    sample_root = files("reachscope").joinpath("samples")
    catalog = json.loads(sample_root.joinpath("catalog.json").read_text(encoding="utf-8"))
    with as_file(sample_root) as samples:
        for item in catalog:
            artifact, timings = index_directory(samples / item["id"], output / "artifacts")
            session = EvidenceSession(artifact)
            claim = {
                "schema_version": "0.2",
                "kind": "reachability",
                "entry": {"kind": "component", "name": item["entry"]},
                "sink": {"kind": item["sink"]},
            }
            trace = [
                {"operation": "overview", "arguments": {}, "result": session.overview()},
                {"operation": "entries", "arguments": {}, "result": session.entries()},
                {"operation": "chains", "arguments": {"entry": item["entry"]},
                 "result": session.chains(item["entry"])},
            ]
            relevant = [chain for chain in artifact.report.chains if item["entry"] in chain.entries]
            if relevant:
                trace.append({"operation": "chain", "arguments": {"chain_id": relevant[0].id},
                              "result": session.chain(relevant[0].id)})
            # Enumerate and read the methods containing the actual step locations.
            method_result = session.methods(limit=100)
            trace.append({"operation": "methods", "arguments": {"limit": 100}, "result": method_result})
            read: set[str] = set()
            for chain in relevant:
                for step in chain.steps:
                    if step.source is None:
                        continue
                    for method in method_result["data"]:
                        if (
                            method["file"] == step.source.file
                            and method["start_line"] <= step.source.line <= method["end_line"]
                            and method["method_ref"] not in read
                        ):
                            method_ref = method["method_ref"]
                            read.add(method_ref)
                            trace.append({"operation": "method", "arguments": {"ref": method_ref, "limit": 100},
                                          "result": session.method(method_ref, limit=100)})
            if not relevant and item["id"] == "wrong_key":
                for method in method_result["data"]:
                    ref = method["method_ref"]
                    if "<init>" not in ref:
                        trace.append({"operation": "method", "arguments": {"ref": ref, "limit": 100},
                                      "result": session.method(ref, limit=100)})
            verdict = session.check(claim)
            trace.append({"operation": "check", "arguments": claim, "result": verdict})
            result = verdict["data"]
            # The public check result may wrap a verdict together with its scope note.
            status = result.get("status") or result.get("verdict", {}).get("status")
            row = {
                **item,
                "artifact_id": artifact.id,
                "chain_count": len(artifact.report.chains),
                "finding_count": len(artifact.report.findings),
                "status": status,
                "passed": status == item["expected_status"] and bool(artifact.report.chains) == item["expected_chain"],
                "timings": timings,
                "trace": trace,
                "chains": [chain.to_dict() for chain in artifact.report.chains],
            }
            _save(output / "traces" / f"{item['id']}.json", trace)
            _save(output / "claims" / f"{item['id']}.json", claim)
            rows.append(row)
    summary: dict[str, Any] = {
        "tool_version": __version__,
        "kind": "offline_regression_walkthrough",
        "model_calls": 0,
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "note": "Synthetic source-only regression cases; not a model evaluation or real-world detection rate.",
        "results": [{k: v for k, v in row.items() if k not in {"trace", "chains"}} for row in rows],
    }
    _save(output / "summary.json", summary)
    template_resource = files("reachscope.report").joinpath("templates")
    with as_file(template_resource) as template_dir:
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
        html = env.get_template("demo.html.j2").render(
            rows=rows, summary=summary, view_cases=_view_cases(rows)
        )
    (output / "index.html").write_text(html, encoding="utf-8")
    return {**summary, "report": str(output / "index.html")}


def _view_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Presentation-only views; never invent an edge for an absent analysis path."""
    labels = {"webview": "WebView", "bridge_method": "JS bridge", "file": "File access",
              "file_ownership": "File scope", "cross_component": "Intent transfer", "call": "Method call"}
    short_titles = {"bridge": "从深链到文件", "cross_component": "越过组件边界",
                    "wrong_key": "没有对上的参数", "permission": "被权限挡住的入口", "missing": "找不到的实现"}
    cases: list[dict[str, Any]] = []
    for row in rows:
        methods = [call["result"]["data"] for call in row["trace"] if call["operation"] == "method"]
        steps: list[dict[str, Any]] = []
        if row["chains"]:
            for step in row["chains"][0]["steps"]:
                source = step.get("source") or {}
                method = next((m for m in methods if m["file"] == source.get("file")
                               and m["method_start_line"] <= source.get("line", 0) <= m["method_end_line"]), None)
                steps.append({
                    "label": labels.get(step["sink"], step["sink"]),
                    "description": step["description"], "file": source.get("file", ""),
                    "line": source.get("line", 0), "code": method["code"] if method else source.get("snippet", ""),
                    "start_line": method["start_line"] if method else source.get("line", 0),
                    "truncated": method.get("truncated", False) if method else True,
                    "kind": "candidate_step",
                })
        else:
            for method in methods:
                steps.append({
                    "label": method["method_ref"].split(";")[0].split("/")[-1],
                    "description": "独立源码观察点；分析未建立这些方法之间的候选路径。",
                    "file": method["file"], "line": method["start_line"],
                    "code": method["code"], "start_line": method["start_line"],
                    "truncated": method["truncated"], "kind": "observation",
                })
        cases.append({
            "id": row["id"], "title": short_titles.get(row["id"], row["title"]),
            "full_title": row["title"], "status": row["status"], "note": row["note"],
            "entry": row["entry"], "artifact_id": row["artifact_id"], "steps": steps,
            "has_path": bool(row["chains"]), "chain_count": row["chain_count"],
            "finding_count": row["finding_count"],
            "verdict": next(call["result"]["data"]["verdict"] for call in row["trace"] if call["operation"] == "check"),
        })
    return cases
