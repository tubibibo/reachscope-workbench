"""Manifest-only worker: decode/parse configuration without indexing code or graphs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from reachscope.extract.components import normalize_class_name
from reachscope.extract.deeplinks import extract_deeplinks
from reachscope.ingest.apk import ApkInput, IngestError, resolve_apktool
from reachscope.ingest.manifest import ANDROID_NS, parse_manifest

from .posture import component_assessments, inspect_security_review

MANIFEST_LIMIT = 2 * 1024 * 1024


def inspect_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MANIFEST_LIMIT:
        raise IngestError("manifest limit", "Manifest must be a regular file of at most 2 MiB")
    raw = path.read_bytes()
    declarations = raw.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise IngestError("manifest parse failed", "Document declarations are not accepted")
    sdk_metadata = path.parent / "apktool.yml"
    if sdk_metadata.exists() and (sdk_metadata.is_symlink() or not sdk_metadata.is_file() or sdk_metadata.stat().st_size > 64 * 1024):
        raise IngestError("SDK metadata limit", "Apktool SDK metadata must be a bounded regular file")
    info = parse_manifest(path)
    root = ET.fromstring(raw)
    review = inspect_security_review(path, target_sdk=info.target_sdk, min_sdk=info.min_sdk)
    assessments = component_assessments(root, info.target_sdk, info.min_sdk)
    requested = sorted({element.get(f"{{{ANDROID_NS}}}name", "")[:300]
                        for element in root if element.tag in {"uses-permission", "uses-permission-sdk-23"}} - {""})
    components = []
    for index, component in enumerate(info.components[:200]):
        record = component.to_dict()
        record["name"] = normalize_class_name(component.name, info.package)
        if component.target_activity:
            record["target_activity"] = normalize_class_name(component.target_activity, info.package)
        record["impl_present"] = None
        record["impl_reason"] = "未选择代码路径检查，未读取实现代码"
        if index < len(assessments):
            record.update(assessments[index])
        if record.get("source"):
            record["source"]["file"] = "AndroidManifest.xml"
        components.append(record)
    deeplinks = [link.to_dict() for link in extract_deeplinks(info.components, info.package)[:200]]
    for link in deeplinks:
        if link.get("source"):
            link["source"]["file"] = "AndroidManifest.xml"
    return {
        "package": info.package, "version_name": info.version_name, "version_code": info.version_code,
        "min_sdk": info.min_sdk, "target_sdk": info.target_sdk,
        "permissions": requested[:500], "declared_permissions": dict(list(info.permissions.items())[:500]),
        "components": components, "deeplinks": deeplinks,
        "components_total": len(info.components), "permissions_total": len(requested),
        "exported_total": sum(item["effective_exported"] is True for item in assessments),
        "exported_unknown": sum(item["effective_exported"] is None for item in assessments),
        "warnings": [warning.replace(str(path), "AndroidManifest.xml")[:1000] for warning in info.warnings[:50]],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "security_review": review,
        "sdk_source": {"manifest": "AndroidManifest.xml", "apktool_metadata_sha256": hashlib.sha256(sdk_metadata.read_bytes()).hexdigest() if sdk_metadata.exists() else None},
        "capture_scope": "Manifest configuration only; implementation presence and code paths were not evaluated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--apktool")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.manifest is not None:
            result = inspect_manifest(args.manifest)
        elif args.apk is not None:
            uploaded = ApkInput.load(args.apk)
            # The parent owns the deadline/process tree. Decoder diagnostics are
            # unused: discard them instead of allowing an unbounded disk log.
            with tempfile.TemporaryDirectory(prefix="manifest-", dir=args.output.parent) as temp:
                decoded = Path(temp) / "decoded"
                completed = subprocess.run(
                    [*resolve_apktool(args.apktool), "d", "-s", "--force-manifest", "--no-assets",
                     "-o", str(decoded), str(uploaded.path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=False,
                )
                if completed.returncode:
                    raise IngestError("apktool failed", "Manifest decoding failed; check the configured Apktool version")
                result = inspect_manifest(decoded / "AndroidManifest.xml")
        else:
            raise IngestError("input missing", "Choose a bundled manifest or uploaded APK")
        args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return 0
    except (IngestError, OSError, ValueError) as exc:
        print(str(exc)[:2000], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
