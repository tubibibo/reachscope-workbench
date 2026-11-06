"""ReachScope 命令行入口。

只负责四件事：参数解析、日志初始化、输入校验、退出码。**不含任何分析逻辑**，
分析能力在 M1–M4 补齐后再接入。

stdout 只写命令结果（一行摘要 / 版本号 / 规则列表），日志与警告一律走 stderr。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from ._version import LOGGER_NAME, __version__
from .analyze.pipeline import analyze_workdir
from .artifacts import ArtifactError, ArtifactStore, snapshot_decoded
from .exitcodes import ExitCode
from .ingest.apk import (
    ApkInput,
    IngestError,
    WorkDir,
    check_apktool_version,
    resolve_apktool,
    run_apktool,
)
from .ingest.protection import detect_protection
from .ir.model import Level, Report
from .ir.serialize import IRDeserializeError
from .protocol.answer import load_answers
from .protocol.claims import ClaimError, load_claim
from .protocol.questions import questions_document, render_questions
from .protocol.verdict import render_verdict, verify_claim
from .report.html_report import write_html
from .report.json_report import load_json, write_json
from .report.methods import RULE_DESCRIPTIONS
from .workspace_cli import register_commands

logger = logging.getLogger(LOGGER_NAME)

DEFAULT_OUT_DIR = "reachscope-out"
DEFAULT_FORMAT = "json,html"
VALID_FORMATS = ("json", "html")
VALID_MIN_EXPLOITABILITY = ("low", "medium", "high")

__all__ = ["main"]

#: T0.1 还没有解析 manifest，包名未知时的占位符（见 DECISIONS.md D-002）。
UNKNOWN_PACKAGE = "<unknown-package>"

#: 六条判据的一句话说明（PLAN §6.3），`reachscope rules list` 静态输出。
#: 与 HTML 报告第 8 章共用 `report/methods.py` 的同一份文本（D-068）。
RULES = RULE_DESCRIPTIONS


def build_parser() -> argparse.ArgumentParser:
    """构造顶层解析器与六个子命令。"""
    parser = argparse.ArgumentParser(
        prog="reachscope",
        description="Android 代码证据与候选路径工具（离线、不执行目标 APK）。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="分析一个 APK 并输出报告")
    scan.add_argument("apk", help="待分析的 APK 路径")
    scan.add_argument("--out", default=DEFAULT_OUT_DIR, help=f"输出目录（默认 {DEFAULT_OUT_DIR}）")
    scan.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        help=f"输出格式，逗号分隔，可选 {', '.join(VALID_FORMATS)}（默认 {DEFAULT_FORMAT}）",
    )
    scan.add_argument(
        "--min-exploitability",
        default="low",
        choices=VALID_MIN_EXPLOITABILITY,
        help="findings 列表的最低可利用性（默认 low，只影响 findings 列表）",
    )
    scan.add_argument("--keep-workdir", action="store_true", help="保留 apktool 工作目录用于调试")
    scan.add_argument("--apktool", default=None, help="apktool 可执行文件或 jar 的路径")
    scan.add_argument("--no-apkid", action="store_true", help="跳过加固检测")
    scan.add_argument("--quiet", action="store_true", help="只输出 ERROR 级日志")
    scan.add_argument("--store", default=None, help="Evidence store (default: OUT/artifacts)")
    scan.add_argument("--no-artifacts", action="store_true", help="Only write legacy reports")
    scan.set_defaults(handler=_cmd_scan)

    explain = subparsers.add_parser("explain", help="展开一条链的完整证据")
    explain.add_argument("report", help="report.json 路径")
    explain.add_argument("chain_id", help="链 ID")
    explain.set_defaults(handler=_cmd_explain)

    verify = subparsers.add_parser(
        "verify", help="核对主张与报告证据的一致性（stdout 输出纯 JSON）"
    )
    verify.add_argument("--report", required=True, help="report.json 路径")
    verify.add_argument("--claim", required=True, help="claim JSON 路径")
    verify.add_argument("--answers", default=None, help="回答 JSON 路径（可选）")
    verify.add_argument("--out", default=None, help="裁决输出路径（默认 stdout）")
    verify.add_argument("--quiet", action="store_true", help="只输出 ERROR 级日志")
    verify.set_defaults(handler=_cmd_verify)

    questions = subparsers.add_parser(
        "questions", help="从报告生成开放问题（stdout 输出纯 JSON）"
    )
    questions.add_argument("--report", required=True, help="report.json 路径")
    questions.add_argument("--out", default=None, help="问题输出路径（默认 stdout）")
    questions.add_argument("--quiet", action="store_true", help="只输出 ERROR 级日志")
    questions.set_defaults(handler=_cmd_questions)

    rules = subparsers.add_parser("rules", help="列出判据")
    rules_sub = rules.add_subparsers(dest="rules_action", required=True)
    rules_list = rules_sub.add_parser("list", help="列出 6 条判据与阈值")
    rules_list.set_defaults(handler=_cmd_rules_list)

    version = subparsers.add_parser("version", help="输出工具版本")
    version.set_defaults(handler=_cmd_version)

    register_commands(subparsers)
    return parser


def _setup_logging(quiet: bool) -> None:
    """把日志输出到**当前** stderr；`--quiet` 时只输出 ERROR。

    每调用一次就重置 handler，保证日志跟随调用时的 stderr（便于测试捕获）。
    """
    log = logging.getLogger(LOGGER_NAME)
    for handler in list(log.handlers):
        log.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.ERROR if quiet else logging.INFO)
    log.propagate = False


def _parse_formats(raw: str) -> list[str] | None:
    """解析 `--format`，非法返回 None（由调用方转成 INPUT_ERROR）。"""
    formats = [part.strip() for part in raw.split(",")]
    formats = [item for item in formats if item]
    if not formats or any(item not in VALID_FORMATS for item in formats):
        return None
    return sorted(set(formats))


def _cmd_scan(args: argparse.Namespace) -> int:
    """扫描入口：解码 → 分析 → 写 JSON/HTML 报告（PLAN §7）。"""
    try:
        apk = ApkInput.load(args.apk)
    except IngestError as exc:
        logger.error("输入错误：%s", exc.to_message())
        return int(exc.exit_code)

    formats = _parse_formats(args.format)
    if formats is None:
        logger.error(
            "输入错误：--format 取值非法 %r，可选：%s", args.format, ", ".join(VALID_FORMATS)
        )
        return int(ExitCode.INPUT_ERROR)

    out_dir = Path(args.out)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        logger.error("Output directory must be new or empty: %s", out_dir)
        return int(ExitCode.INPUT_ERROR)

    protection = detect_protection(apk.path, no_apkid=args.no_apkid)
    if not protection.analyzable:
        # PLAN §4.3：强加固不得用空结果冒充“无问题”。
        logger.error(
            "无法分析：检测到强加固（labels=%s），后续分析跳过，不产出报告", protection.labels
        )
        return int(ExitCode.UNANALYZABLE)

    logger.info(
        "参数：apk=%s sha256=%s size=%d out=%s format=%s min_exploitability=%s "
        "keep_workdir=%s apktool=%s no_apkid=%s quiet=%s protection(detected=%s labels=%s)",
        apk.path,
        apk.sha256[:16],
        apk.size,
        args.out,
        ",".join(formats),
        args.min_exploitability,
        args.keep_workdir,
        args.apktool,
        args.no_apkid,
        args.quiet,
        protection.detected,
        protection.labels,
    )

    try:
        apktool_version = check_apktool_version(resolve_apktool(args.apktool))
        with WorkDir(keep=args.keep_workdir) as workdir, tempfile.TemporaryDirectory(
            prefix="reachscope-snapshot-"
        ) as temporary:
            decoded = run_apktool(apk, workdir, apktool=args.apktool)
            decoded = snapshot_decoded(decoded, Path(temporary) / "source")
            report = analyze_workdir(
                decoded,
                protection=protection,
                apk_path=str(apk.path),
                apk_sha256=apk.sha256,
                apktool_version=apktool_version,
            )
            artifact_id = None
            if not args.no_artifacts:
                store = Path(args.store) if args.store else Path(args.out) / "artifacts"
                artifact = ArtifactStore(store).create(
                    decoded, report,
                    config={"input_mode": "apk", "call_depth": 4, "component_hops": 1},
                )
                artifact_id = artifact.id
    except IngestError as exc:
        logger.error("无法分析：%s", exc.to_message())
        return int(exc.exit_code)
    except ArtifactError as exc:
        logger.error("Evidence storage failed [%s]: %s", exc.code, exc)
        return int(ExitCode.INPUT_ERROR)

    report = _apply_min_exploitability(report, args.min_exploitability)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if "json" in formats:
        write_json(report, out_dir / "report.json")
    if "html" in formats:
        write_html(report, out_dir / "report.html")
    if artifact_id is not None:
        (out_dir / "artifact.json").write_text(
            json.dumps({"artifact_id": artifact_id, "store": str(store.resolve())}, indent=2) + "\n",
            encoding="utf-8",
        )

    # stdout 只允许一行摘要（PLAN §7）。
    print(
        f"scanned {report.meta.package or UNKNOWN_PACKAGE}: "
        f"{len(report.findings)} findings, {len(report.counter_examples)} counter-examples "
        f"-> {args.out}"
    )
    return int(ExitCode.OK)


def _apply_min_exploitability(report: Report, minimum: str) -> Report:
    """`--min-exploitability` 只过滤 findings 列表（PLAN §7），不动链与反例。"""
    threshold = {
        "low": Level.LOW,
        "medium": Level.MEDIUM,
        "high": Level.HIGH,
    }[minimum]
    kept = [
        finding
        for finding in report.findings
        if finding.exploitability.score() >= threshold.score()
    ]
    if len(kept) == len(report.findings):
        return report
    return replace(report, findings=kept)


def _load_report(path_value: str) -> Report | None:
    """读取报告；失败时写 stderr 并返回 None（由调用方转成 INPUT_ERROR）。"""
    path = Path(path_value)
    if not path.is_file():
        logger.error("输入错误：报告不存在 %s", path)
        return None
    try:
        return load_json(path)
    except (IRDeserializeError, OSError) as exc:
        logger.error("输入错误：报告无法读取（%s）", exc)
        return None


def _emit_json(text: str, out: str | None) -> int:
    """把协议 JSON 写到 stdout 或文件；返回退出码。

    stdout 强制 UTF-8 字节：Windows 控制台/重定向默认是 GBK，Agent 按 UTF-8
    解析会直接解码失败。`--out` 同样是 UTF-8。
    """
    if out is None:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(text.encode("utf-8"))
            buffer.flush()
        else:  # pragma: no cover - 仅在不带 buffer 的替换 stdout 下发生
            sys.stdout.write(text)
        return int(ExitCode.OK)
    target = Path(out)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        logger.error("输入错误：输出路径无法写入 %s（%s）", target, exc)
        return int(ExitCode.INPUT_ERROR)
    return int(ExitCode.OK)


def _cmd_verify(args: argparse.Namespace) -> int:
    """Check a claim against report evidence (protocol 0.2)."""
    report = _load_report(args.report)
    if report is None:
        return int(ExitCode.INPUT_ERROR)
    try:
        claim = load_claim(args.claim)
    except ClaimError as exc:
        logger.error("输入错误：%s", exc)
        return int(ExitCode.INPUT_ERROR)
    answers = None
    if args.answers:
        try:
            answers = load_answers(args.answers)
        except ClaimError as exc:
            logger.error("输入错误：%s", exc)
            return int(ExitCode.INPUT_ERROR)
    try:
        verdict = verify_claim(report, claim, answers)
    except ClaimError as exc:
        logger.error("输入错误：%s", exc)
        return int(ExitCode.INPUT_ERROR)
    return _emit_json(render_verdict(verdict), args.out)


def _cmd_questions(args: argparse.Namespace) -> int:
    """从报告生成开放问题，供 Agent 回答后重新裁决。"""
    report = _load_report(args.report)
    if report is None:
        return int(ExitCode.INPUT_ERROR)
    return _emit_json(render_questions(questions_document(report)), args.out)


def _cmd_explain(args: argparse.Namespace) -> int:
    """展开 `report.json` 里一条链的完整证据（PLAN §7）。"""
    report = _load_report(args.report)
    if report is None:
        return int(ExitCode.INPUT_ERROR)

    chain = next((item for item in report.chains if item.id == args.chain_id), None)
    if chain is None:
        logger.error(
            "输入错误：报告里没有链 %s（共 %d 条链）", args.chain_id, len(report.chains)
        )
        return int(ExitCode.INPUT_ERROR)

    print(f"chain {chain.id}")
    print(f"entries: {', '.join(chain.entries) or '—'}")
    rank = chain.rank
    print(
        f"rank: exploitability={rank.exploitability.value} impact={rank.impact.value} "
        f"confidence={rank.confidence.value} evidence_complete={str(chain.evidence_complete).lower()}"
    )
    print("steps:")
    for step in chain.steps:
        print(f"  {step.order}. {step.description}")
        flow = " -> ".join(part for part in (step.from_, step.to) if part)
        suffix = f" [{step.sink}]" if step.sink else ""
        print(f"     {flow}{suffix}")
        if step.source is not None:
            print(f"     at {step.source.file}:{step.source.line}")
            if step.source.snippet:
                print(f"     > {step.source.snippet}")
    print("judgments:")
    for judgment in chain.judgments:
        location = (
            f" @ {judgment.source.file}:{judgment.source.line}"
            if judgment.source is not None and judgment.source.file
            else ""
        )
        print(
            f"  {judgment.name} {judgment.result.value} ({judgment.confidence.value}) "
            f"{judgment.score_delta:+d} {judgment.reason}{location}"
        )
    finding = next((item for item in report.findings if item.chain_id == chain.id), None)
    if finding is not None:
        print(f"finding: {finding.title}")
    return int(ExitCode.OK)


def _cmd_rules_list(args: argparse.Namespace) -> int:
    """静态输出六条判据的一句话说明。"""
    del args  # 无参数
    print("ReachScope 判据（PLAN §6.3）：")
    for name, description in RULES:
        print(f"  {name}  {description}")
    return int(ExitCode.OK)


def _cmd_version(args: argparse.Namespace) -> int:
    """输出工具版本号。"""
    del args  # 无参数
    print(__version__)
    return int(ExitCode.OK)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，返回退出码；未捕获异常转成 INTERNAL_ERROR 并写 traceback 到 stderr。"""
    # Help, legacy text and logs must be readable under Windows redirection too.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _setup_logging(bool(getattr(args, "quiet", False)))
    handler: Any = args.handler
    try:
        return int(handler(args))
    except Exception:  # CLI 最外层必须把未捕获异常转为 INTERNAL_ERROR，避免 traceback 泄露给调用方。
        logger.exception("内部错误：未捕获异常")
        return int(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
