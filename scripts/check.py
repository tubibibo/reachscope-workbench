#!/usr/bin/env python3
"""跨平台一键自检：ruff + mypy + pytest。

不依赖 bash / PowerShell / Makefile。本机是 Windows PowerShell 5.1，
编码坑太多（`Out-File`/here-string），所以脚本写在 Python 里。

用法：
    python scripts/check.py             # 全跑
    python scripts/check.py --no-cov    # 不开覆盖率
    python scripts/check.py --mypy-only # 只跑 mypy
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(label: str, cmd: list[str]) -> bool:
    print(f"\n=== {label}: {' '.join(cmd)} ===", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, check=False)
    return completed.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-cov", action="store_true", help="pytest 不开覆盖率")
    parser.add_argument("--ruff-only", action="store_true")
    parser.add_argument("--mypy-only", action="store_true")
    parser.add_argument("--pytest-only", action="store_true")
    args = parser.parse_args(argv)

    steps: list[tuple[str, list[str]]] = []
    if not (args.mypy_only or args.pytest_only):
        # 整个仓库（src/tests/scripts）；ruff 默认尊重 .gitignore
        steps.append(("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]))
    if not (args.ruff_only or args.pytest_only):
        steps.append(("mypy", [sys.executable, "-m", "mypy"]))
    if not (args.ruff_only or args.mypy_only):
        cmd = [sys.executable, "-m", "pytest", "tests", "-q"]
        if args.no_cov:
            cmd.append("--no-cov")
        if not args.no_cov:
            cmd.append("--cov=reachscope")
            cmd.append("--cov=reachscope_workbench")
            cmd.append("--cov-report=term-missing")
            cmd.append("--cov-fail-under=85")
        steps.append(("pytest", cmd))

    failed: list[str] = []
    for label, cmd in steps:
        if not _run(label, cmd):
            failed.append(label)

    if failed:
        print(f"\n[FAIL] failed: {', '.join(failed)}")
        return 1
    print("\n[OK] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
