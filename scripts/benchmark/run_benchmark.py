#!/usr/bin/env python3
"""在带 ground truth 的语料上评测 ReachScope（检出率 / 部分命中 / 未解释 findings）。

APK 不入库：清单只记文件名与 sha256，语料目录由 `--corpus-dir` 指定。
每条 expectation 描述一个「入口 + 期望 sink」；判定按链的 sink 子序列匹配。

用法：
    python scripts/benchmark/run_benchmark.py \
        --corpus-dir ../local-corpus \
        --out ../local-runs/reachscope-bench \
        --apktool ../local-tools/apktool.jar

只看已有报告（不重新扫描）：
    python scripts/benchmark/run_benchmark.py ... --skip-scan
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "benchmark" / "ground_truth.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(package: str, name: str) -> str:
    """把 `.MainActivity` / `MainActivity` 补成 `package.MainActivity`。"""
    value = (name or "").strip()
    if not value:
        return ""
    if value.startswith("."):
        return f"{package}{value}" if package else value
    if "." not in value and package:
        return f"{package}.{value}"
    return value


def split_uri(uri: str) -> tuple[str, str, str]:
    """`scheme://host/path` → 三段；不做严格 URL 解析，够用即可。"""
    if "://" not in uri:
        return "", "", ""
    scheme, rest = uri.split("://", 1)
    path = ""
    if "/" in rest:
        rest, tail = rest.split("/", 1)
        path = "/" + tail
    return scheme, rest, path


def entry_components(report: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    """把 expectation 的入口解析成报告里的组件名列表。"""
    package = str(report.get("meta", {}).get("package") or "")
    if entry.get("kind") == "deeplink":
        scheme, host, path = split_uri(str(entry.get("uri") or ""))
        exact = [
            item
            for item in report.get("deeplinks", [])
            if item.get("scheme") == scheme
            and item.get("host") == host
            and (not path or item.get("path") == path)
        ]
        # intent-filter 只声明 host/scheme 时，报告里的 path 为空；退化为 scheme+host。
        loose = [
            item
            for item in report.get("deeplinks", [])
            if item.get("scheme") == scheme and item.get("host") == host
        ]
        return sorted({str(item.get("component") or "") for item in (exact or loose)})
    wanted = str(entry.get("name") or entry.get("id") or "")
    return [
        str(component.get("name") or "")
        for component in report.get("components", [])
        if wanted
        and canonical(package, str(component.get("name") or ""))
        == canonical(package, wanted)
    ]


def chain_sinks(chain: dict[str, Any]) -> list[str]:
    return [str(step.get("sink") or "") for step in chain.get("steps", []) if step.get("sink")]


def is_subsequence(wanted: list[str], actual: list[str]) -> bool:
    index = 0
    for sink in actual:
        if index < len(wanted) and sink == wanted[index]:
            index += 1
    return index == len(wanted)


def chains_at(report: dict[str, Any], components: list[str]) -> list[dict[str, Any]]:
    package = str(report.get("meta", {}).get("package") or "")
    wanted = {canonical(package, name) for name in components}
    return [
        chain
        for chain in report.get("chains", [])
        if chain.get("entries")
        and canonical(package, str(chain["entries"][0])) in wanted
    ]


def best_chain(chains: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not chains:
        return None
    return min(chains, key=lambda item: (not item.get("evidence_complete", False), str(item.get("id"))))


def evaluate_expectation(
    report: dict[str, Any], expectation: dict[str, Any]
) -> dict[str, Any]:
    """返回 detected / partial / miss / out_of_vocabulary。"""
    result: dict[str, Any] = {
        "id": expectation.get("id"),
        "ground_truth": expectation.get("ground_truth", ""),
        "sinks": list(expectation.get("sinks") or []),
    }
    if expectation.get("out_of_vocabulary"):
        result["status"] = "out_of_vocabulary"
        return result

    components = entry_components(report, expectation.get("entry") or {})
    result["entry_components"] = components

    # 阴性 expectation（M1）：该入口**不应**有任何链。用于验证新边/新 key 匹配
    # 没有引入假阳性；单独计数，不混进检出率。
    if expectation.get("expect_no_chain"):
        candidates = chains_at(report, components) if components else []
        result["chain_sinks"] = sorted(
            {sink for chain in candidates for sink in chain_sinks(chain)}
        )
        if candidates:
            result["status"] = "unexpected_chain"
            result["matched_chain"] = candidates[0].get("id")
            result["detail"] = "阴性入口出现了链（假阳性风险），需人工复核"
        else:
            result["status"] = "no_chain_ok"
            result["detail"] = (
                "阴性入口 0 链" if components else "入口不在报告里，视为 0 链"
            )
        return result

    if not components:
        result["status"] = "miss"
        result["detail"] = "入口不在报告里（未被提取或匹配不上）"
        return result

    candidates = chains_at(report, components)
    wanted = [str(sink) for sink in (expectation.get("sinks") or [])]
    matched = [chain for chain in candidates if is_subsequence(wanted, chain_sinks(chain))]
    if matched:
        chain = best_chain(matched) or matched[0]
        result["status"] = "detected"
        result["matched_chain"] = chain.get("id")
        result["chain_sinks"] = chain_sinks(chain)
        result["evidence_complete"] = chain.get("evidence_complete", False)
        return result

    partial_kinds = {str(sink) for sink in (expectation.get("accept_partial") or [])}
    partial = [
        chain
        for chain in candidates
        if partial_kinds.intersection(chain_sinks(chain))
    ]
    if partial:
        chain = best_chain(partial) or partial[0]
        result["status"] = "partial"
        result["matched_chain"] = chain.get("id")
        result["chain_sinks"] = chain_sinks(chain)
        result["detail"] = "只走到第一跳，期望 sink 未连通"
        return result

    result["status"] = "miss"
    result["chain_sinks"] = sorted({sink for chain in candidates for sink in chain_sinks(chain)})
    result["detail"] = "入口有链，但没有一条连通期望 sink" if candidates else "该入口没有链"
    return result


def evaluate_findings(
    report: dict[str, Any], expectations: list[dict[str, Any]]
) -> dict[str, Any]:
    """把 findings 映射回 expectation；解释不了的单列，供人工复核。"""
    package = str(report.get("meta", {}).get("package") or "")
    chains = {str(chain.get("id")): chain for chain in report.get("chains", [])}
    explained = 0
    unreviewed: list[dict[str, Any]] = []
    for finding in report.get("findings", []):
        chain = chains.get(str(finding.get("chain_id")))
        if chain is None:
            unreviewed.append({"chain_id": finding.get("chain_id"), "reason": "chain 缺失"})
            continue
        entry = str(chain["entries"][0]) if chain.get("entries") else ""
        sinks = set(chain_sinks(chain))
        hit = False
        for expectation in expectations:
            if expectation.get("out_of_vocabulary"):
                continue
            components = {
                canonical(package, name)
                for name in entry_components(report, expectation.get("entry") or {})
            }
            if canonical(package, entry) not in components:
                continue
            expected = {str(sink) for sink in (expectation.get("sinks") or [])}
            partial = {str(sink) for sink in (expectation.get("accept_partial") or [])}
            if sinks & (expected | partial):
                hit = True
                break
        if hit:
            explained += 1
        else:
            unreviewed.append(
                {
                    "chain_id": finding.get("chain_id"),
                    "title": finding.get("title"),
                    "entry": entry,
                    "sinks": sorted(sinks),
                    "reason": "不在 ground truth 内，需人工判定真/假",
                }
            )
    return {"findings": len(report.get("findings", [])), "explained": explained, "unreviewed": unreviewed}


def run_scan(
    apk: Path, out_dir: Path, apktool: str | None, timeout: int
) -> tuple[int | None, str]:
    cmd = [sys.executable, "-m", "reachscope", "scan", str(apk), "--out", str(out_dir)]
    if apktool:
        cmd.extend(["--apktool", apktool])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"超过 {timeout}s 未完成"
    return completed.returncode, (completed.stderr or "")[-2000:]


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise SystemExit(f"清单格式错误：{path} 缺少 cases 数组")
    return payload


def evaluate_case(
    case: dict[str, Any],
    corpus_dir: Path,
    out_root: Path,
    apktool: str | None,
    skip_scan: bool,
    timeout: int,
) -> dict[str, Any]:
    case_id = str(case.get("id") or "")
    result: dict[str, Any] = {"id": case_id, "role": case.get("role", ""), "notes": case.get("notes", "")}
    if case.get("skip"):
        result["status"] = "skipped"
        result["detail"] = case.get("skip_reason", "")
        return result

    apk = corpus_dir / str(case.get("apk") or "")
    if not apk.is_file():
        result["status"] = "error"
        result["detail"] = f"APK 不存在：{apk}"
        return result
    expected_hash = case.get("sha256")
    if expected_hash and sha256_file(apk) != expected_hash:
        result["status"] = "error"
        result["detail"] = "sha256 与清单不符"
        return result

    out_dir = out_root / case_id
    report_path = out_dir / "report.json"
    if not skip_scan and not report_path.is_file():
        started = time.monotonic()
        code, tail = run_scan(apk, out_dir, apktool, timeout)
        result["scan_seconds"] = round(time.monotonic() - started, 1)
        if code is None:
            result["status"] = "timeout"
            result["detail"] = tail
            return result
        if code != 0:
            result["status"] = "error"
            result["detail"] = f"scan 退出码 {code}：{tail}"
            return result
    if not report_path.is_file():
        result["status"] = "error"
        result["detail"] = f"报告不存在：{report_path}"
        return result

    report = json.loads(report_path.read_text(encoding="utf-8"))
    result["status"] = "ok"
    result["report"] = str(report_path)
    result["counts"] = {
        "components": len(report.get("components", [])),
        "deeplinks": len(report.get("deeplinks", [])),
        "chains": len(report.get("chains", [])),
        "findings": len(report.get("findings", [])),
        "counter_examples": len(report.get("counter_examples", [])),
    }
    expectations = list(case.get("expectations") or [])
    result["expectations"] = [evaluate_expectation(report, item) for item in expectations]
    result["findings"] = evaluate_findings(report, expectations)
    return result


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    expected = detected = partial = miss = out_of_vocabulary = 0
    no_chain_checks = no_chain_violations = 0
    findings = explained = 0
    for case in cases:
        if case.get("status") != "ok":
            continue
        for item in case.get("expectations", []):
            status = item.get("status")
            if status == "out_of_vocabulary":
                out_of_vocabulary += 1
                continue
            if status in ("no_chain_ok", "unexpected_chain"):
                no_chain_checks += 1
                if status == "unexpected_chain":
                    no_chain_violations += 1
                continue
            expected += 1
            if status == "detected":
                detected += 1
            elif status == "partial":
                partial += 1
            else:
                miss += 1
        findings += case.get("findings", {}).get("findings", 0)
        explained += case.get("findings", {}).get("explained", 0)
    return {
        "cases_run": sum(1 for case in cases if case.get("status") == "ok"),
        "cases_timeout": sum(1 for case in cases if case.get("status") == "timeout"),
        "cases_error": sum(1 for case in cases if case.get("status") == "error"),
        "expectations_in_scope": expected,
        "detected": detected,
        "partial": partial,
        "miss": miss,
        "out_of_vocabulary": out_of_vocabulary,
        "expect_no_chain_checks": no_chain_checks,
        "expect_no_chain_violations": no_chain_violations,
        "detection_rate": round(detected / expected, 3) if expected else None,
        "any_signal_rate": round((detected + partial) / expected, 3) if expected else None,
        "findings": findings,
        "findings_explained": explained,
        "findings_unreviewed": findings - explained,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# ReachScope benchmark", "", f"生成时间：{payload['generated_at']}", ""]
    lines.append("| case | 角色 | 组件 | 深链 | 链 | findings | 反例 |")
    lines.append("|---|---|---|---|---|---|---|")
    for case in payload["cases"]:
        counts = case.get("counts") or {}
        lines.append(
            f"| {case['id']} | {case.get('role', '')} | {counts.get('components', '—')} | "
            f"{counts.get('deeplinks', '—')} | {counts.get('chains', '—')} | "
            f"{counts.get('findings', '—')} | {counts.get('counter_examples', '—')} |"
        )
    lines.extend(["", "## expectations", "", "| case | expectation | status | chain sinks | 说明 |"])
    lines.append("|---|---|---|---|---|")
    for case in payload["cases"]:
        for item in case.get("expectations", []):
            lines.append(
                f"| {case['id']} | {item.get('id')} | {item.get('status')} | "
                f"{', '.join(item.get('chain_sinks') or []) or '—'} | {item.get('detail', '')} |"
            )
    summary = payload["summary"]
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            f"- 在范围内 expectation：{summary['expectations_in_scope']}",
            f"- 超时 / 报错 case：{summary['cases_timeout']} / {summary['cases_error']}",
            f"- detected / partial / miss：{summary['detected']} / {summary['partial']} / {summary['miss']}",
            f"- 检出率：{summary['detection_rate']}；含部分命中：{summary['any_signal_rate']}",
            (
                f"- 阴性检查（expect_no_chain）：{summary['expect_no_chain_checks']} 条，"
                f"违规 {summary['expect_no_chain_violations']} 条"
            ),
            (
                f"- findings：{summary['findings']}（可解释 {summary['findings_explained']}，"
                f"待人工复核 {summary['findings_unreviewed']}）"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp936；结果里有中文，按 UTF-8 输出避免乱码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", required=True, help="APK 目录（仓库外）")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="ground truth 清单")
    parser.add_argument("--out", required=True, help="报告与结果输出目录")
    parser.add_argument("--apktool", default=None, help="apktool jar/可执行文件")
    parser.add_argument("--only", action="append", default=None, help="只跑指定 case id（可重复）")
    parser.add_argument("--skip-scan", action="store_true", help="只读已有 report.json")
    parser.add_argument(
        "--timeout", type=int, default=1800, help="单个 scan 的超时秒数（默认 1800）"
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))
    corpus_dir = Path(args.corpus_dir)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    selected = set(args.only or [])
    cases: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        if selected and str(case.get("id")) not in selected:
            continue
        case_id = str(case.get("id") or "?")
        print(f"[..] {case_id}", flush=True)
        result = evaluate_case(
            case, corpus_dir, out_root, args.apktool, args.skip_scan, args.timeout
        )
        cases.append(result)
        print(f"[{result['status']}] {case_id} {result.get('detail', '')}", flush=True)

    payload = {
        "schema_version": "0.1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "manifest": str(Path(args.manifest).resolve()),
        "corpus_dir": str(corpus_dir.resolve()),
        "cases": cases,
        "summary": summarize(cases),
    }
    result_path = out_root / "benchmark-result.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = out_root / "benchmark-report.md"
    markdown_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    print(render_markdown(payload))
    print(f"-> {result_path}")
    print(f"-> {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
