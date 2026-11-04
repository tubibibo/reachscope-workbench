"""Entry point for the local multi-module workbench."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import uvicorn

from . import __version__
from .api.app import create_app
from .diagnostics import inspect_readiness


def main() -> None:
    parser = argparse.ArgumentParser(prog="reachscope-workbench", description="Android / Web / Cloud / Host 安全复核工作台")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动本地前端与 API")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data", type=Path, default=Path(os.environ.get("REACHSCOPE_DATA", ".workbench")))
    doctor = sub.add_parser("doctor", help="本地只读启动自检，不联系目标或 AI 服务商")
    doctor.add_argument("--data", type=Path, default=Path(os.environ.get("REACHSCOPE_DATA", ".workbench")))
    doctor.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()
    if args.command == "doctor":
        report = inspect_readiness(args.data)
        if args.json:
            # ASCII JSON escapes survive Windows pipe encodings and automation
            # configured with an ASCII stdout; decoded JSON still has Chinese text.
            print(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            print(f"ReachScope {__version__} / 本地启动自检")
            for item in report["checks"]:
                print(f"[{item['status']}] {item['label']}: {item['message']}")
            for limitation in report["limitations"]:
                print(f"说明: {limitation}")
        raise SystemExit(0 if report["ready"] else 1)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    app = create_app(args.data)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
