"""Developer entry point: backend checks and typed frontend production build."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [subprocess.run([sys.executable, str(root / "scripts/quality/check_repository.py")],
                             cwd=root, check=False).returncode]
    checks.append(subprocess.run([sys.executable, str(root / "scripts/check.py")], cwd=root, check=False).returncode)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        print("Node.js/npm required for frontend checks", file=sys.stderr)
        return 1
    checks.append(subprocess.run([sys.executable, str(root / "scripts/quality/check_contracts.py")], cwd=root, check=False).returncode)
    checks.append(subprocess.run([npm, "run", "check"], cwd=root / "frontend", check=False).returncode)
    checks.append(subprocess.run([npm, "run", "format:check"], cwd=root / "frontend", check=False).returncode)
    checks.append(subprocess.run([npm, "run", "build"], cwd=root / "frontend", check=False).returncode)
    return int(any(checks))


if __name__ == "__main__":
    raise SystemExit(main())
