"""Decode once, capture bounded configuration, then reuse the saved-code engine.

Runs only inside the workbench's isolated/owned process tree. Temporary decoded
resources are removed after a bounded configuration summary and code artifact
have been persisted; no APK is installed or executed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from reachscope.analyze.pipeline import analyze_workdir
from reachscope.artifacts import ArtifactError, ArtifactStore, snapshot_decoded
from reachscope.ingest.apk import ApkInput, IngestError, check_apktool_version, resolve_apktool
from reachscope.ingest.protection import detect_protection

from .manifest_worker import inspect_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--apktool")
    parser.add_argument("--no-apkid", action="store_true", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        apk = ApkInput.load(args.apk)
        base = resolve_apktool(args.apktool)
        version = check_apktool_version(base)
        args.out.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="android-", dir=args.out.parent) as temporary:
            temporary_path = Path(temporary)
            decoded = temporary_path / "decoded"
            # Only the worker's bounded result/error channel is consumed.
            # Unused decoder diagnostics must not create an unbounded disk log.
            completed = subprocess.run(
                [*base, "d", "-f", "--no-assets", "-o", str(decoded), str(apk.path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=False,
            )
            if completed.returncode:
                raise IngestError("apktool failed", "APK decoding failed; check the configured Apktool version")
            configuration = inspect_manifest(decoded / "AndroidManifest.xml")
            snapshot = snapshot_decoded(decoded, temporary_path / "source")
            # Apktool moves uses-sdk into sdkInfo. Preserve only the parsed
            # numeric metadata for the engine, never an unbounded YAML input.
            sdk_lines = [f"  {key}: '{configuration[value]}'" for key, value in
                         (("minSdkVersion", "min_sdk"), ("targetSdkVersion", "target_sdk"))
                         if type(configuration[value]) is int]
            if sdk_lines:
                (snapshot / "apktool.yml").write_text("sdkInfo:\n" + "\n".join(sdk_lines) + "\n", encoding="utf-8")
            protection = detect_protection(apk.path, no_apkid=True)
            report = analyze_workdir(snapshot, protection=protection, apk_path=str(apk.path),
                                    apk_sha256=apk.sha256, apktool_version=version)
            artifact = ArtifactStore(args.store).create(snapshot, report,
                                                       config={"input_mode": "apk", "call_depth": 4, "component_hops": 1})
            (args.out / "manifest-result.json").write_text(json.dumps(configuration, ensure_ascii=False), encoding="utf-8")
            (args.out / "artifact.json").write_text(json.dumps({"artifact_id": artifact.id}), encoding="utf-8")
        return 0
    except (IngestError, ArtifactError, OSError, ValueError) as exc:
        print(str(exc)[:2000], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
