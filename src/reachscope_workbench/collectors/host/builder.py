"""Deterministic source-containing zipapp; building never collects host data."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

_FILES = ("__init__.py", "collector.py", "runner.py", "projection.py", "builder.py", "LICENSE")


def build_zipapp() -> bytes:
    """Return a reviewable stdlib-only archive with a fixed entry point."""
    output = io.BytesIO()
    directory = Path(__file__).resolve().parent
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        entries = {"__main__.py": b"from reachscope_host_collector.collector import main\nraise SystemExit(main())\n",
                   **{"reachscope_host_collector/" + filename: (directory / filename).read_bytes() for filename in _FILES}}
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output.getvalue()
