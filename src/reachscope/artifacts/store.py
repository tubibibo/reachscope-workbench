"""Store decoded evidence without resources, executable deserialization, or a server.

An artifact binds a report and its method locations to the exact saved source bytes.
Hashes detect corruption and accidental changes; they are not signatures and do not
establish that a report uploaded by another party is trustworthy.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from .._version import SCHEMA_VERSION, __version__
from ..ingest.smali import build_index
from ..ir.model import Report
from ..ir.serialize import IRDeserializeError
from ..report.json_report import normalize_report, render_json

ARTIFACT_SCHEMA_VERSION = "1"
_ID = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PAGE_SIZE = 500
_METADATA_LIMIT = 64 * 1024 * 1024
_PUBLISH_RETRY_DELAYS = (0.05, 0.1, 0.2)
_LIMITATIONS: tuple[str, ...] = (
    "Candidate static paths are not proof of runtime exploitability.",
    "Call graph depth is limited to four and explicit component transfers to one hop.",
    "General data propagation is not fully branch- or instance-sensitive.",
    "Implicit intents, reflection, JNI, dynamic loading and asynchronous flows may be missed.",
    "A missing path does not establish that the program is unreachable or safe.",
)


class ArtifactError(ValueError):
    """Structured artifact failure suitable for CLI or tool responses."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _Source:
    path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class _Method:
    ref: str
    file: str
    start_line: int
    end_line: int
    complete: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "method_ref": self.ref,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "complete": self.complete,
        }


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ArtifactError("INVALID_INPUT", f"Value is not finite JSON data: {exc}") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _disk_path(path: Path) -> Path:
    """Use Win32 extended-length names for filesystem operations, not evidence IDs.

    Prefixes require an absolute normalized path; UNC names need the separate
    ``UNC`` form. Do not resolve symlinks here: callers check their components.
    """
    if os.name != "nt":
        return path
    ordinary = str(_public_path(path))
    absolute = ntpath.normpath(ntpath.abspath(ordinary))
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def _public_path(path: Path) -> Path:
    """Keep user-facing paths ordinary while using prefixed paths internally."""
    text = str(path)
    if os.name == "nt":
        if text[:8].upper() == "\\\\?\\UNC\\":
            return Path("\\\\" + text[8:])
        if text.startswith("\\\\?\\"):
            return Path(text[4:])
    return path


def _is_link(path: Path) -> bool:
    info = _disk_path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse points/junctions.
    )


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            linked = _is_link(part)
        except FileNotFoundError:
            continue
        if linked:
            raise ArtifactError("UNSAFE_PATH", f"Symbolic links are not allowed: {part}")


def _relative_file(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or pure.is_absolute()
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ArtifactError("UNSAFE_PATH", f"Invalid artifact-relative path: {relative!r}")
    target = _disk_path(root.joinpath(*pure.parts))
    return target


class _PathGuard:
    """Check ancestors once per operation, never cache across artifact accesses.

    File entries are always checked again. Like ordinary filesystem reads this
    does not provide an OS-level snapshot against concurrent hostile renames.
    """

    def __init__(self, root: Path) -> None:
        _no_links(root)
        self.root = _disk_path(root)
        self._directories: set[Path] = {self.root}

    def file(self, relative: str) -> Path:
        target = _relative_file(self.root, relative)
        current = self.root
        parts = PurePosixPath(relative).parts
        for index, part in enumerate(parts):
            current /= part
            if index < len(parts) - 1 and current in self._directories:
                continue
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ArtifactError("UNSAFE_PATH", f"Symbolic links are not allowed: {current}")
            if stat.S_ISDIR(info.st_mode):
                self._directories.add(current)
        return target


def _read_bytes(path: Path, limit: int, *, check_links: bool = True) -> bytes:
    if check_links:
        _no_links(path)
    path = _disk_path(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        raise ArtifactError("CORRUPT_ARTIFACT", f"Required file is missing: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise ArtifactError("CORRUPT_ARTIFACT", f"Expected a regular file: {path}")
    if info.st_size > limit:
        raise ArtifactError("SIZE_LIMIT", f"File exceeds byte limit {limit}: {path}")
    with path.open("rb") as handle:
        # Reading the whole budget for each tiny file allocates tens of MiB per
        # read on CPython. Read the known size plus one byte to detect growth.
        data = handle.read(info.st_size + 1)
    if len(data) > limit:
        raise ArtifactError("SIZE_LIMIT", f"File exceeds byte limit {limit}: {path}")
    if len(data) != info.st_size:
        raise ArtifactError("INPUT_CHANGED", f"File size changed while reading: {path}")
    return data


def _json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ArtifactError("CORRUPT_ARTIFACT", f"Invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError("CORRUPT_ARTIFACT", f"Expected JSON object in {label}")
    return cast("dict[str, Any]", value)


def _validate_manifest(data: bytes) -> None:
    declaration_bytes = data.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declaration_bytes or b"<!ENTITY" in declaration_bytes:
        raise ArtifactError("INVALID_MANIFEST", "Manifest DTDs and entities are not supported")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        raise ArtifactError("INVALID_MANIFEST", f"Cannot parse decoded manifest: {exc}") from exc
    if root.tag != "manifest":
        raise ArtifactError("INVALID_MANIFEST", "Decoded XML root must be manifest")


def _semantic_report(report: Report) -> str:
    # Persistence sorts semantically unordered top-level collections. Hash that
    # same representation so a valid report keeps its identity after loading.
    data = normalize_report(report).to_dict()
    # These values vary when identical input is scanned on another machine or date.
    meta = cast("dict[str, object]", data["meta"])
    meta.pop("apk_path", None)
    meta.pop("analyzed_at", None)
    return _sha(_canonical(data))


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ArtifactError("CORRUPT_ARTIFACT", f"Invalid {label}: {value!r}")
    return value


def _is_windows() -> bool:
    """Read the platform at call time so tests can simulate either branch."""
    return sys.platform == "win32"


def _rename_stage(stage: Path, destination: Path) -> None:
    """Retry only bounded Windows sharing/access races during atomic publication.

    Antivirus/indexer handles can briefly prevent a complete staging directory
    from being renamed. Never fall back to copying a partially visible artifact,
    retry other filesystem failures, or replace an existing destination. The
    caller still opens/verifies a concurrent winner and cleans any unused stage.
    """
    for attempt in range(len(_PUBLISH_RETRY_DELAYS) + 1):
        try:
            stage.rename(destination)
            return
        except PermissionError as exc:
            if (
                not _is_windows()
                or getattr(exc, "winerror", None) not in {5, 32, 33}
                or attempt == len(_PUBLISH_RETRY_DELAYS)
                or destination.exists()
                or destination.is_symlink()
            ):
                raise
            time.sleep(_PUBLISH_RETRY_DELAYS[attempt])


def _page(offset: int, limit: int) -> None:
    if type(offset) is not int or offset < 0:
        raise ArtifactError("INVALID_INPUT", "offset must be a nonnegative integer")
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE_SIZE:
        raise ArtifactError("INVALID_INPUT", f"limit must be between 1 and {_MAX_PAGE_SIZE}")


class Artifact:
    """A verified report and persistent code snapshot.

    Construction is internal to ArtifactStore. Method reads recheck source hashes,
    including modifications made after opening an artifact.
    """

    def __init__(
        self,
        path: Path,
        report: Report,
        metadata: dict[str, Any],
        sources: dict[str, _Source],
        methods: dict[str, _Method],
        max_file_bytes: int,
    ) -> None:
        self.path = path
        self.report = report
        self.id = str(metadata["artifact_id"])
        self._metadata = metadata
        self._sources = sources
        self._methods = methods
        self._max_file_bytes = max_file_bytes

    @property
    def metadata(self) -> dict[str, object]:
        """Return a defensive JSON copy so callers cannot alter stored validation state."""
        return cast("dict[str, object]", json.loads(_canonical(self._metadata)))

    def list_methods(
        self, query: str = "", *, offset: int = 0, limit: int = 50
    ) -> dict[str, object]:
        _page(offset, limit)
        if not isinstance(query, str) or len(query) > 1000:
            raise ArtifactError("INVALID_INPUT", "query must be a string of at most 1000 characters")
        matches = [self._methods[ref] for ref in sorted(self._methods) if query in ref]
        selected = matches[offset : offset + limit]
        next_offset = offset + len(selected)
        return {
            "artifact_id": self.id,
            "methods": [item.to_dict() for item in selected],
            "total": len(matches),
            "offset": offset,
            "limit": limit,
            "truncated": next_offset < len(matches),
            "next_offset": next_offset if next_offset < len(matches) else None,
        }

    def read_method(
        self, method_ref: str, *, offset: int = 0, limit: int = 80
    ) -> dict[str, object]:
        _page(offset, limit)
        method = self._methods.get(method_ref)
        if method is None:
            raise ArtifactError("METHOD_NOT_FOUND", f"Method is not in this artifact: {method_ref}")
        source = self._sources[method.file]
        try:
            guard = _PathGuard(self.path / "source")
            data = _read_bytes(guard.file(method.file), self._max_file_bytes, check_links=False)
        except OSError as exc:
            raise ArtifactError("IO_ERROR", f"Cannot read method evidence: {exc}") from exc
        if _sha(data) != source.sha256:
            raise ArtifactError("INTEGRITY_ERROR", f"Source changed: {method.file}")
        lines = data.decode("utf-8", errors="replace").splitlines()
        if method.end_line > len(lines):
            raise ArtifactError("CORRUPT_ARTIFACT", f"Method location exceeds file: {method_ref}")
        body = lines[method.start_line - 1 : method.end_line]
        selected = body[offset : offset + limit]
        next_offset = offset + len(selected)
        return {
            "artifact_id": self.id,
            "method_ref": method_ref,
            "file": method.file,
            "sha256": source.sha256,
            "method_start_line": method.start_line,
            "method_end_line": method.end_line,
            "start_line": method.start_line + offset if selected else None,
            "end_line": method.start_line + offset + len(selected) - 1 if selected else None,
            "complete": method.complete,
            "code": "\n".join(selected),
            "total_lines": len(body),
            "offset": offset,
            "limit": limit,
            "truncated": next_offset < len(body),
            "next_offset": next_offset if next_offset < len(body) else None,
        }


class ArtifactStore:
    """Local content-addressed evidence directories with explicit resource budgets."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_total_bytes: int = 256 * 1024 * 1024,
        max_file_bytes: int = 32 * 1024 * 1024,
        max_files: int = 100_000,
    ) -> None:
        for label, value in (
            ("max_total_bytes", max_total_bytes),
            ("max_file_bytes", max_file_bytes),
            ("max_files", max_files),
        ):
            if type(value) is not int or value <= 0:
                raise ArtifactError("INVALID_INPUT", f"{label} must be a positive integer")
        self.root = Path(root).absolute()
        self.max_total_bytes = max_total_bytes
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files

    def create(
        self,
        decoded_dir: Path,
        report: Report,
        *,
        config: dict[str, object] | None = None,
    ) -> Artifact:
        """Snapshot decoded Manifest/smali and publish only a complete artifact.

        Source contents, report semantics, tool versions and config determine the
        ID. Repeated scans with a different timestamp reuse the original artifact.
        """
        try:
            return self._create(Path(decoded_dir), report, {} if config is None else config)
        except OSError as exc:
            raise ArtifactError("IO_ERROR", f"Cannot create artifact: {exc}") from exc

    def _create(self, decoded: Path, report: Report, config: dict[str, object]) -> Artifact:
        if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
            raise ArtifactError("INVALID_INPUT", "config must be a JSON object with string keys")
        clean_config = _json(_canonical(config), "config")
        _no_links(decoded)
        decoded = _disk_path(decoded)
        if not decoded.is_dir():
            raise ArtifactError("INVALID_INPUT", f"Decoded directory does not exist: {decoded}")
        _no_links(self.root)
        disk_root = _disk_path(self.root)
        disk_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=disk_root))
        try:
            sources = self._copy_sources(decoded, stage / "source")
            _validate_manifest(_read_bytes(stage / "source" / "AndroidManifest.xml", self.max_file_bytes))
            methods, index_warnings = _index_methods(stage / "source")
            methods_data = _canonical({ref: item.to_dict() for ref, item in methods.items()})
            report_data = render_json(report).encode("utf-8")
            identity: dict[str, object] = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "report_schema_version": SCHEMA_VERSION,
                "tool_version": __version__,
                "report_tool_version": report.meta.tool_version,
                "apktool_version": report.meta.apktool_version,
                "apk_sha256": report.meta.apk_sha256,
                "decoded_sha256": _sha(_canonical([item.to_dict() for item in sources.values()])),
                "report_semantic_sha256": _semantic_report(report),
                "methods_sha256": _sha(methods_data),
                "config": clean_config,
                "limitations": list(_LIMITATIONS),
                "warnings": sorted({*report.meta.warnings, *index_warnings}),
            }
            artifact_id = _sha(_canonical(identity))
            metadata: dict[str, object] = {
                **identity,
                "artifact_id": artifact_id,
                "package": report.meta.package,
                "files": [item.to_dict() for item in sources.values()],
                "report_sha256": _sha(report_data),
                "method_count": len(methods),
                "source_bytes": sum(item.size for item in sources.values()),
            }
            metadata_data = _canonical(metadata)
            if any(len(payload) > _METADATA_LIMIT for payload in (report_data, methods_data, metadata_data)):
                raise ArtifactError("SIZE_LIMIT", "Analysis metadata exceeds artifact byte limit")
            (stage / "report.json").write_bytes(report_data)
            (stage / "methods.json").write_bytes(methods_data)
            (stage / "artifact.json").write_bytes(metadata_data)
            destination = disk_root / artifact_id
            if destination.exists() or destination.is_symlink():
                return self.open(artifact_id)
            try:
                _rename_stage(stage, destination)
            except OSError:
                # Another process may have atomically published the same content.
                if destination.exists():
                    return self.open(artifact_id)
                raise
            return self.open(artifact_id)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _copy_sources(self, decoded: Path, target: Path) -> dict[str, _Source]:
        return _copy_sources(
            decoded, target, max_total_bytes=self.max_total_bytes,
            max_file_bytes=self.max_file_bytes, max_files=self.max_files,
        )

    def open(self, artifact_id: str) -> Artifact:
        """Open and validate a supported artifact, including source content hashes."""
        if not isinstance(artifact_id, str) or _ID.fullmatch(artifact_id) is None:
            raise ArtifactError("INVALID_INPUT", "artifact_id must be a 64-character lowercase SHA256")
        try:
            return self._open(artifact_id)
        except OSError as exc:
            raise ArtifactError("IO_ERROR", f"Cannot open artifact: {exc}") from exc

    def _open(self, artifact_id: str) -> Artifact:
        _no_links(self.root)
        path = _disk_path(self.root / artifact_id)
        _no_links(path)
        if not path.is_dir():
            raise ArtifactError("ARTIFACT_NOT_FOUND", f"Artifact does not exist: {artifact_id}")
        metadata = _json(_read_bytes(path / "artifact.json", _METADATA_LIMIT), "artifact.json")
        if metadata.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
            raise ArtifactError("UNSUPPORTED_SCHEMA", "Artifact schema version is not supported")
        if metadata.get("report_schema_version") != SCHEMA_VERSION:
            raise ArtifactError("UNSUPPORTED_SCHEMA", "Report schema version is not supported")
        if metadata.get("artifact_id") != artifact_id:
            raise ArtifactError("INTEGRITY_ERROR", "Artifact directory and metadata IDs differ")
        sources = self._validate_sources(path, metadata)
        report_data = _read_bytes(path / "report.json", _METADATA_LIMIT)
        if _sha(report_data) != metadata.get("report_sha256"):
            raise ArtifactError("INTEGRITY_ERROR", "Stored report has changed")
        report_doc = _json(report_data, "report.json")
        if report_doc.get("schema_version") != SCHEMA_VERSION:
            raise ArtifactError("UNSUPPORTED_SCHEMA", "Stored report schema version is not supported")
        try:
            report = Report.from_dict(report_doc)
        except (IRDeserializeError, TypeError, ValueError) as exc:
            raise ArtifactError("CORRUPT_ARTIFACT", f"Invalid stored report: {exc}") from exc
        methods_data = _read_bytes(path / "methods.json", _METADATA_LIMIT)
        if _sha(methods_data) != metadata.get("methods_sha256"):
            raise ArtifactError("INTEGRITY_ERROR", "Stored method index has changed")
        methods = _load_methods(_json(methods_data, "methods.json"), sources)
        identity = {key: metadata.get(key) for key in (
            "artifact_schema_version", "report_schema_version", "tool_version", "report_tool_version",
            "apktool_version", "apk_sha256", "decoded_sha256", "report_semantic_sha256",
            "methods_sha256", "config", "limitations", "warnings",
        )}
        if (
            _sha(_canonical(identity)) != artifact_id
            or _semantic_report(report) != metadata.get("report_semantic_sha256")
            or len(methods) != metadata.get("method_count")
            or report.meta.apk_sha256 != metadata.get("apk_sha256")
            or report.meta.tool_version != metadata.get("report_tool_version")
            or report.meta.apktool_version != metadata.get("apktool_version")
            or report.meta.package != metadata.get("package")
        ):
            raise ArtifactError("INTEGRITY_ERROR", "Artifact identity or analysis metadata has changed")
        return Artifact(_public_path(path), report, metadata, sources, methods, self.max_file_bytes)

    def _validate_sources(self, path: Path, metadata: dict[str, Any]) -> dict[str, _Source]:
        inventory = metadata.get("files")
        if not isinstance(inventory, list) or not inventory or len(inventory) > self.max_files:
            raise ArtifactError("CORRUPT_ARTIFACT", "Invalid source inventory")
        sources: dict[str, _Source] = {}
        total = 0
        guard = _PathGuard(path / "source")
        for record in inventory:
            if not isinstance(record, dict):
                raise ArtifactError("CORRUPT_ARTIFACT", "Invalid source record")
            relative, digest = record.get("path"), record.get("sha256")
            if not isinstance(relative, str) or not isinstance(digest, str) or not _ID.fullmatch(digest):
                raise ArtifactError("CORRUPT_ARTIFACT", "Invalid source path or hash")
            if relative in sources:
                raise ArtifactError("CORRUPT_ARTIFACT", "Duplicate source path")
            source_path = guard.file(relative)
            if relative not in {"AndroidManifest.xml", "apktool.yml"} and not (
                relative.split("/")[0].startswith("smali") and relative.endswith(".smali")
            ):
                raise ArtifactError("CORRUPT_ARTIFACT", "Unexpected source file kind")
            size = _integer(record.get("size"), "source size")
            total += size
            if total > self.max_total_bytes:
                raise ArtifactError("SIZE_LIMIT", "Artifact exceeds total source byte limit")
            data = _read_bytes(source_path, self.max_file_bytes, check_links=False)
            if len(data) != size or _sha(data) != digest:
                raise ArtifactError("INTEGRITY_ERROR", f"Source changed: {relative}")
            if relative == "AndroidManifest.xml":
                _validate_manifest(data)
            sources[relative] = _Source(relative, digest, size)
        if "AndroidManifest.xml" not in sources:
            raise ArtifactError("CORRUPT_ARTIFACT", "Artifact has no decoded manifest")
        ordered = [item.to_dict() for item in sources.values()]
        if _sha(_canonical(ordered)) != metadata.get("decoded_sha256") or total != metadata.get("source_bytes"):
            raise ArtifactError("INTEGRITY_ERROR", "Decoded source identity has changed")
        return sources

    def list(self) -> list[dict[str, object]]:
        """List verified completed artifacts; interrupted staging directories are ignored."""
        try:
            _no_links(self.root)
            disk_root = _disk_path(self.root)
            if not disk_root.exists():
                return []
            results: list[dict[str, object]] = []
            for path in sorted(disk_root.iterdir()):
                if _ID.fullmatch(path.name):
                    artifact = self.open(path.name)
                    results.append({
                        "artifact_id": artifact.id,
                        "package": artifact.report.meta.package,
                        "apk_sha256": artifact.report.meta.apk_sha256,
                        "tool_version": artifact.metadata["tool_version"],
                        "method_count": len(artifact._methods),
                    })
            return results
        except OSError as exc:
            raise ArtifactError("IO_ERROR", f"Cannot list artifacts: {exc}") from exc


def snapshot_decoded(
    decoded: str | Path,
    destination: str | Path,
    *,
    max_total_bytes: int = 256 * 1024 * 1024,
    max_file_bytes: int = 32 * 1024 * 1024,
    max_files: int = 100_000,
) -> Path:
    """Copy bounded analysis inputs before analyzing untrusted decoded trees.

    The destination must be new or empty and outside the input. It contains
    Manifest, smali and optional apktool SDK metadata only. Callers should analyze
    this snapshot and create their artifact from this same snapshot, never from
    the original mutable tree. No directory is analyzed by this function.
    """
    for label, value in (
        ("max_total_bytes", max_total_bytes), ("max_file_bytes", max_file_bytes),
        ("max_files", max_files),
    ):
        if type(value) is not int or value <= 0:
            raise ArtifactError("INVALID_INPUT", f"{label} must be a positive integer")
    source = Path(decoded).absolute()
    target = Path(destination).absolute()
    try:
        _no_links(source)
        _no_links(target)
        source = _disk_path(source)
        target = _disk_path(target)
        if not source.is_dir():
            raise ArtifactError("INVALID_INPUT", f"Decoded directory does not exist: {source}")
        if target.resolve().is_relative_to(source.resolve()):
            raise ArtifactError("INVALID_INPUT", "Snapshot destination must be outside decoded input")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ArtifactError("INVALID_INPUT", "Snapshot destination must be new or empty")
        target.mkdir(parents=True, exist_ok=True)
        try:
            _copy_sources(
                source, target, max_total_bytes=max_total_bytes,
                max_file_bytes=max_file_bytes, max_files=max_files,
            )
            _validate_manifest(_read_bytes(target / "AndroidManifest.xml", max_file_bytes))
        except (ArtifactError, OSError):
            # This directory was verified empty above and contains only our copy.
            # Recheck links before cleanup, including Windows reparse points.
            _no_links(target)
            shutil.rmtree(target)
            raise
        return target
    except OSError as exc:
        raise ArtifactError("IO_ERROR", f"Cannot snapshot decoded input: {exc}") from exc


def _copy_sources(
    decoded: Path, target: Path, *, max_total_bytes: int, max_file_bytes: int, max_files: int
) -> dict[str, _Source]:
    decoded = _disk_path(decoded)
    target = _disk_path(target)
    source_guard = _PathGuard(decoded)
    target_guard = _PathGuard(target)
    manifest = source_guard.file("AndroidManifest.xml")
    if not manifest.is_file():
        raise ArtifactError("INVALID_MANIFEST", "Decoded AndroidManifest.xml is missing")
    candidates = [manifest]
    sdk_metadata = source_guard.file("apktool.yml")
    if sdk_metadata.exists():
        candidates.append(sdk_metadata)
    if len(candidates) > max_files:
        raise ArtifactError("SIZE_LIMIT", "Source file count exceeds artifact limit")
    for directory in sorted(decoded.glob("smali*"), key=lambda item: (len(item.name), item.name)):
        source_guard.file(directory.relative_to(decoded).as_posix())
        if not directory.is_dir():
            continue
        for base, directories, filenames in os.walk(
            directory, followlinks=False, onerror=_walk_error
        ):
            for name in directories:
                source_guard.file((Path(base) / name).relative_to(decoded).as_posix())
            for name in filenames:
                candidate = Path(base) / name
                source_guard.file(candidate.relative_to(decoded).as_posix())
                if candidate.suffix == ".smali":
                    candidates.append(candidate)
                    if len(candidates) > max_files:
                        raise ArtifactError("SIZE_LIMIT", "Source file count exceeds artifact limit")
    sources: dict[str, _Source] = {}
    total = 0
    for candidate in sorted(candidates, key=lambda item: item.relative_to(decoded).as_posix()):
        relative = candidate.relative_to(decoded).as_posix()
        source_guard.file(relative)
        data = _read_bytes(candidate, max_file_bytes, check_links=False)
        total += len(data)
        if total > max_total_bytes:
            raise ArtifactError("SIZE_LIMIT", "Decoded sources exceed total artifact byte limit")
        output = target_guard.file(relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        sources[relative] = _Source(relative, _sha(data), len(data))
    return sources


def _walk_error(error: OSError) -> None:
    raise error


def _index_methods(root: Path) -> tuple[dict[str, _Method], list[str]]:
    root = _disk_path(root)
    try:
        index = build_index(root)
    except (ValueError, OSError) as exc:
        raise ArtifactError("INVALID_SOURCE", f"Cannot index saved smali: {exc}") from exc
    methods: dict[str, _Method] = {}
    cached_file = ""
    lines: list[str] = []
    for ref, method in sorted(index.method_index.items(), key=lambda item: (item[1].source.file, item[0])):
        if method.source.file != cached_file:
            cached_file = method.source.file
            lines = _relative_file(root, cached_file).read_text(encoding="utf-8", errors="replace").splitlines()
        start = method.source.line
        if not 1 <= start <= len(lines):
            raise ArtifactError("INVALID_SOURCE", f"Invalid method location: {ref}")
        end = start
        complete = False
        for cursor in range(start, len(lines)):
            stripped = lines[cursor].strip().split("#", 1)[0].strip()
            if stripped.startswith(".method "):
                break
            end = cursor + 1
            if stripped == ".end method":
                complete = True
                break
        methods[ref] = _Method(ref, method.source.file, start, end, complete)
    return dict(sorted(methods.items())), list(index.warnings)


def _load_methods(doc: dict[str, Any], sources: dict[str, _Source]) -> dict[str, _Method]:
    methods: dict[str, _Method] = {}
    for ref, value in doc.items():
        if not isinstance(value, dict):
            raise ArtifactError("CORRUPT_ARTIFACT", "Invalid method record")
        relative = value.get("file")
        if not isinstance(relative, str) or relative not in sources or value.get("method_ref") != ref:
            raise ArtifactError("CORRUPT_ARTIFACT", "Method refers to unknown source or identity")
        start = _integer(value.get("start_line"), "method start line", minimum=1)
        end = _integer(value.get("end_line"), "method end line", minimum=start)
        complete = value.get("complete")
        if type(complete) is not bool:
            raise ArtifactError("CORRUPT_ARTIFACT", "Invalid method completeness")
        methods[ref] = _Method(ref, relative, start, end, complete)
    return methods
