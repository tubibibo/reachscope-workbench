"""Run after `reachscope demo --out reachscope-demo`.

Usage: python examples/evidence_session.py reachscope-demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reachscope.artifacts import ArtifactStore
from reachscope.query import EvidenceSession


def main() -> None:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "reachscope-demo")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    case = next(item for item in summary["results"] if item["id"] == "cross_component")
    session = EvidenceSession(ArtifactStore(directory / "artifacts").open(case["artifact_id"]))
    print(json.dumps(session.chains(entry=case["entry"]), indent=2, ensure_ascii=False))
    methods = session.methods(query="CrossTarget")
    ref = methods["data"][0]["reference"]
    print(json.dumps(session.method(ref), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
