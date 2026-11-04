"""Use cases shared by the CLI and Python clients; no model or transport dependency."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .analyze.pipeline import analyze_workdir
from .artifacts import Artifact, ArtifactError, ArtifactStore, snapshot_decoded
from .ir.model import Protection


def index_directory(
    decoded_dir: str | Path,
    store_dir: str | Path,
    *,
    protection: Protection | None = None,
) -> tuple[Artifact, dict[str, float]]:
    """Analyze a decoded directory and retain queryable evidence.

    The caller explicitly supplies the decoded tree. Embedded protection.json,
    claims, and arbitrary documents never supply analysis instructions.
    """
    root = Path(decoded_dir).absolute()
    if not root.is_dir() or not (root / "AndroidManifest.xml").is_file():
        raise ArtifactError("INVALID_INPUT", "Expected a decoded directory with AndroidManifest.xml")
    store_root = Path(store_dir).resolve()
    if store_root == root or root in store_root.parents:
        raise ArtifactError("INVALID_INPUT", "The artifact store must be outside the decoded input")
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="reachscope-snapshot-") as temporary:
        snapshot = snapshot_decoded(root, Path(temporary) / "source")
        snapshotted = time.perf_counter()
        report = analyze_workdir(snapshot, protection=protection)
        analyzed = time.perf_counter()
        artifact = ArtifactStore(store_root).create(
            snapshot, report, config={"input_mode": "decoded", "call_depth": 4, "component_hops": 1}
        )
    stored = time.perf_counter()
    return artifact, {
        "snapshot_seconds": round(snapshotted - start, 6),
        "analysis_seconds": round(analyzed - snapshotted, 6),
        "storage_seconds": round(stored - analyzed, 6),
        "total_seconds": round(stored - start, 6),
    }
