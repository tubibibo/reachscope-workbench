"""Generate/check request types against the real local OpenAPI schema, offline.

Run with --write after intentional API changes. Default mode verifies committed
schema/types without modifying the checkout. Requires frontend npm ci and Node.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from reachscope_workbench.api.app import create_app

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "frontend/contracts/openapi.json"
TYPES = ROOT / "frontend/src/generated/api.d.ts"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    node = shutil.which("node")
    generator = ROOT / "frontend/node_modules/openapi-typescript/bin/cli.js"
    prettier = ROOT / "frontend/node_modules/prettier/bin/prettier.cjs"
    if node is None or not generator.is_file() or not prettier.is_file():
        print("Contract generation requires Node and frontend npm ci.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="reachscope-contracts-") as directory:
        temporary = Path(directory)
        # No lifespan is started: no workers, teaching site, targets or providers.
        schema = create_app(temporary / "workspace").openapi()
        encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        schema_path, types_path = temporary / "openapi.json", temporary / "api.d.ts"
        schema_path.write_text(encoded, encoding="utf-8", newline="\n")
        for command in ([node, str(generator), str(schema_path), "--output", str(types_path)],
                        [node, str(prettier), "--parser", "typescript", "--write", str(types_path)]):
            completed = subprocess.run(command, cwd=ROOT, check=False, timeout=60,
                                       capture_output=True, text=True, encoding="utf-8")
            if completed.returncode:
                print("Local contract generator failed; check installed frontend tool versions.", file=sys.stderr)
                print(completed.stderr[:3000], file=sys.stderr)
                return 1
        generated = types_path.read_text(encoding="utf-8")
        expected = ((SCHEMA, encoded), (TYPES, generated))
        if args.write:
            for path, content in expected:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
            print("Updated local OpenAPI snapshot and generated request types.")
            return 0
        changed = [str(path.relative_to(ROOT)) for path, content in expected
                   if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if changed:
            print("Contract drift: " + ", ".join(changed), file=sys.stderr)
            print("Run python scripts/quality/check_contracts.py --write, review the diff, and commit intentional changes.", file=sys.stderr)
            return 1
        print("OpenAPI and generated TypeScript request contracts match the application.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
