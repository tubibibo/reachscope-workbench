"""Machine-readable evidence commands. All business logic lives below the CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .application import index_directory
from .artifacts import ArtifactError, ArtifactStore
from .demo import build_demo
from .protocol.claims import ClaimError
from .query import EvidenceSession, QueryError

DEFAULT_STORE = ".reachscope/artifacts"


def register_commands(subparsers: Any) -> None:
    """Register commands without requiring a running service."""
    index = subparsers.add_parser("index", help="Index a decoded APK and retain code evidence")
    index.add_argument("decoded_dir")
    index.add_argument("--store", default=DEFAULT_STORE)
    index.set_defaults(handler=run_workspace_command)

    query = subparsers.add_parser("query", help="Query an artifact; stdout is JSON")
    query.add_argument("artifact_id")
    query.add_argument("topic", choices=[
        "overview", "entries", "chains", "chain", "methods", "method", "check", "questions"
    ])
    query.add_argument("--store", default=DEFAULT_STORE)
    query.add_argument("--search", default="")
    query.add_argument("--entry")
    query.add_argument("--id")
    query.add_argument("--ref")
    query.add_argument("--claim")
    query.add_argument("--offset", type=int, default=0)
    query.add_argument("--limit", type=int, default=50)
    query.set_defaults(handler=run_workspace_command)

    artifacts = subparsers.add_parser("artifacts", help="List retained local artifacts")
    artifacts.add_argument("--store", default=DEFAULT_STORE)
    artifacts.set_defaults(handler=run_workspace_command)

    demo = subparsers.add_parser("demo", help="Build a local, offline evidence walkthrough")
    demo.add_argument("--out", default="reachscope-demo")
    demo.set_defaults(handler=run_workspace_command)

    doctor = subparsers.add_parser("doctor", help="Report local capabilities as JSON")
    doctor.set_defaults(handler=run_workspace_command)


def emit_json(data: object) -> None:
    """UTF-8 output also works with Windows redirection."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(text)


def _query(args: argparse.Namespace) -> dict[str, Any]:
    session = EvidenceSession(ArtifactStore(Path(args.store)).open(args.artifact_id))
    match args.topic:
        case "overview":
            return session.overview()
        case "entries":
            return session.entries(args.search, offset=args.offset, limit=args.limit)
        case "chains":
            return session.chains(args.entry, offset=args.offset, limit=args.limit)
        case "chain":
            if not args.id:
                raise QueryError("INVALID_ARGUMENT", "chain requires --id")
            return session.chain(args.id)
        case "methods":
            return session.methods(args.search, offset=args.offset, limit=args.limit)
        case "method":
            if not args.ref:
                raise QueryError("INVALID_ARGUMENT", "method requires --ref")
            return session.method(args.ref, offset=args.offset, limit=args.limit)
        case "check":
            if not args.claim:
                raise QueryError("INVALID_ARGUMENT", "check requires --claim FILE.json")
            claim = json.loads(Path(args.claim).read_text(encoding="utf-8"))
            if not isinstance(claim, dict):
                raise QueryError("INVALID_ARGUMENT", "Claim must be a JSON object")
            return session.check(claim)
        case "questions":
            return session.questions()
        case _:
            raise QueryError("INVALID_ARGUMENT", "Unsupported query")


def run_workspace_command(args: argparse.Namespace) -> int:
    """Return structured operational errors; programming errors reach the top-level handler."""
    try:
        match args.command:
            case "index":
                artifact, timings = index_directory(args.decoded_dir, args.store)
                result: object = {
                    "artifact_id": artifact.id,
                    "artifact_path": str(artifact.path),
                    "scope": "static_analysis_report",
                    "summary": artifact.report.summary(),
                    "timings": timings,
                }
            case "query":
                result = _query(args)
            case "artifacts":
                result = {"artifacts": ArtifactStore(Path(args.store)).list()}
            case "demo":
                result = build_demo(Path(args.out))
            case "doctor":
                result = {
                    "python": sys.version.split()[0],
                    "decoded_analysis": True,
                    "offline_demo": True,
                    "java": shutil.which("java"),
                    "apktool": shutil.which("apktool"),
                    "apk_scan_note": "APK input additionally needs Java and an apktool executable or JAR",
                    "model_api_required": False,
                }
            case _:
                raise QueryError("INVALID_ARGUMENT", "Unsupported command")
        emit_json(result)
        return 0
    except (ArtifactError, QueryError) as exc:
        emit_json({"error": {"code": exc.code, "message": str(exc)}})
        return 2
    except (OSError, ValueError, ClaimError) as exc:
        emit_json({"error": {"code": "INVALID_INPUT", "message": str(exc)}})
        return 2
