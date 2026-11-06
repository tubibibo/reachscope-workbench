"""Evidence snapshot integrity and paging; no APK decoder or network required."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from reachscope.artifacts import ArtifactError, ArtifactStore, snapshot_decoded
from reachscope.artifacts.store import _disk_path
from reachscope.ingest.manifest import parse_manifest
from reachscope.ir.model import Bridge, Component, Meta, Report
from reachscope.report.json_report import render_json

METHOD_REF = "Lcom/example/Demo;->open()V"
SOURCE_PATH = "smali/com/example/Demo.smali"
SOURCE = """.class public Lcom/example/Demo;
.super Ljava/lang/Object;

.method public open()V
    .locals 1
    const-string v0, "https://example.com"
    return-void
.end method

.method public close()V
    .locals 0
    return-void
.end method
"""


@pytest.fixture
def decoded(tmp_path: Path) -> Path:
    root = tmp_path / "decoded"
    source = root / SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding="utf-8")
    (root / "AndroidManifest.xml").write_text(
        '<manifest package="com.example"><application/></manifest>', encoding="utf-8"
    )
    (root / "res").mkdir()
    (root / "res" / "image.png").write_bytes(b"not needed")
    return root


@pytest.fixture
def report() -> Report:
    return Report(meta=Meta(
        apk_path="/different/machine/app.apk",
        apk_sha256="b" * 64,
        package="com.example",
        tool_version="test-version",
        apktool_version="2.11.1",
        analyzed_at="2026-11-01T00:00:00Z",
        warnings=["example analysis warning"],
    ))


def _metadata(path: Path) -> dict[str, object]:
    return json.loads((path / "artifact.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _change_metadata(path: Path, **changes: object) -> None:
    data = _metadata(path)
    data.update(changes)
    (path / "artifact.json").write_text(json.dumps(data), encoding="utf-8")


def test_snapshot_round_trip_and_only_evidence_is_copied(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report, config={"mode": "full"})
    assert len(artifact.id) == 64
    assert (artifact.path / "report.json").read_text(encoding="utf-8") == render_json(report)
    assert (artifact.path / "source" / SOURCE_PATH).read_text(encoding="utf-8") == SOURCE
    assert not (artifact.path / "source" / "res").exists()
    reopened = store.open(artifact.id)
    assert reopened.report == report
    assert reopened.metadata["config"] == {"mode": "full"}
    assert reopened.metadata["warnings"] == report.meta.warnings
    assert reopened.metadata["limitations"]
    assert store.list() == [{
        "artifact_id": artifact.id,
        "package": "com.example",
        "apk_sha256": "b" * 64,
        "tool_version": artifact.metadata["tool_version"],
        "method_count": 2,
    }]


def test_repeated_scans_reuse_identity_across_timestamp_and_paths(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    first = store.create(decoded, report)
    moved = dataclasses.replace(report, meta=dataclasses.replace(
        report.meta, analyzed_at="2099-01-01", apk_path="C:/elsewhere/app.apk"
    ))
    second = store.create(decoded, moved)
    assert second.id == first.id
    assert second.report.meta.analyzed_at == report.meta.analyzed_at
    assert len(store.list()) == 1
    assert not list(store.root.glob(".staging-*"))


def test_unordered_report_collections_round_trip_with_stable_identity(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    unordered = dataclasses.replace(
        report,
        components=[Component(name="z.Last"), Component(name="a.First")],
        bridges=[Bridge(id="z", impl_class="Lz;"), Bridge(id="a", impl_class="La;")],
    )
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, unordered)
    reordered = dataclasses.replace(
        unordered, components=list(reversed(unordered.components)), bridges=list(reversed(unordered.bridges))
    )
    assert store.open(artifact.id).id == artifact.id
    assert store.create(decoded, reordered).id == artifact.id
    assert [bridge.id for bridge in artifact.report.bridges] == ["a", "z"]


def test_sources_config_versions_and_report_semantics_change_identity(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    original = store.create(decoded, report).id
    configured = store.create(decoded, report, config={"depth": 2}).id
    changed_report = dataclasses.replace(report, meta=dataclasses.replace(report.meta, target_sdk=35))
    semantic = store.create(decoded, changed_report).id
    versioned = store.create(decoded, dataclasses.replace(
        report, meta=dataclasses.replace(report.meta, apktool_version="different")
    )).id
    (decoded / SOURCE_PATH).write_text(SOURCE.replace("example.com", "example.org"), encoding="utf-8")
    changed_source = store.create(decoded, report).id
    assert len({original, configured, semantic, versioned, changed_source}) == 5


def test_list_methods_and_read_method_have_physical_lines_and_pagination(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    artifact = ArtifactStore(tmp_path / "store").create(decoded, report)
    page = artifact.list_methods(limit=1)
    assert page["total"] == 2
    assert page["truncated"] is True
    assert page["next_offset"] == 1
    assert artifact.list_methods("open")["total"] == 1
    assert artifact.list_methods("nothing")["methods"] == []
    first = artifact.read_method(METHOD_REF, limit=2)
    assert first["method_start_line"] == 4
    assert first["method_end_line"] == 8
    assert first["start_line"] == 4
    assert first["end_line"] == 5
    assert first["code"] == ".method public open()V\n    .locals 1"
    assert first["sha256"] == hashlib.sha256((decoded / SOURCE_PATH).read_bytes()).hexdigest()
    assert first["truncated"] is True
    assert first["next_offset"] == 2
    rest = artifact.read_method(METHOD_REF, offset=2)
    assert rest["code"].endswith(".end method")
    assert rest["truncated"] is False
    assert rest["next_offset"] is None
    assert rest["complete"] is True
    empty = artifact.read_method(METHOD_REF, offset=100)
    assert empty["start_line"] is None
    assert empty["code"] == ""
    assert empty["truncated"] is False


@pytest.mark.parametrize(("offset", "limit"), [(-1, 10), (0, 0), (0, 501), (True, 5)])
def test_bad_paging_is_rejected(
    tmp_path: Path, decoded: Path, report: Report, offset: int, limit: int
) -> None:
    artifact = ArtifactStore(tmp_path / "store").create(decoded, report)
    for operation in (artifact.list_methods, lambda **kw: artifact.read_method(METHOD_REF, **kw)):
        with pytest.raises(ArtifactError) as caught:
            operation(offset=offset, limit=limit)
        assert caught.value.code == "INVALID_INPUT"


def test_unknown_method_and_artifact_are_distinct(tmp_path: Path, decoded: Path, report: Report) -> None:
    store = ArtifactStore(tmp_path / "store")
    assert store.list() == []
    with pytest.raises(ArtifactError, match="does not exist") as caught:
        store.open("a" * 64)
    assert caught.value.code == "ARTIFACT_NOT_FOUND"
    artifact = store.create(decoded, report)
    with pytest.raises(ArtifactError) as caught:
        artifact.read_method("Lmissing;->no()V")
    assert caught.value.code == "METHOD_NOT_FOUND"


@pytest.mark.parametrize("artifact_id", ["../elsewhere", "ABC", "A" * 64, "a" * 63, "C:/source"])
def test_artifact_id_cannot_traverse_paths(tmp_path: Path, artifact_id: str) -> None:
    with pytest.raises(ArtifactError) as caught:
        ArtifactStore(tmp_path).open(artifact_id)
    assert caught.value.code == "INVALID_INPUT"


def test_source_tampering_is_detected_during_reads_and_open(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    (artifact.path / "source" / SOURCE_PATH).write_text(SOURCE + "# changed", encoding="utf-8")
    with pytest.raises(ArtifactError) as caught:
        artifact.read_method(METHOD_REF)
    assert caught.value.code == "INTEGRITY_ERROR"
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "INTEGRITY_ERROR"
    with pytest.raises(ArtifactError):
        store.create(decoded, report)  # Never silently reuse a corrupt existing directory.


@pytest.mark.parametrize("filename", ["methods.json", "report.json"])
def test_report_and_method_index_tampering_is_detected(
    tmp_path: Path, decoded: Path, report: Report, filename: str
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    (artifact.path / filename).write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "INTEGRITY_ERROR"


def test_unsupported_schema_and_broken_metadata_are_explicit(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    _change_metadata(artifact.path, artifact_schema_version="future")
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "UNSUPPORTED_SCHEMA"
    (artifact.path / "artifact.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "CORRUPT_ARTIFACT"


def test_inventory_traversal_is_rejected_before_file_access(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    data = _metadata(artifact.path)
    files = data["files"]
    assert isinstance(files, list)
    files[0]["path"] = "../../outside.txt"
    _change_metadata(artifact.path, files=files)
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "UNSAFE_PATH"


def test_metadata_is_a_defensive_copy(tmp_path: Path, decoded: Path, report: Report) -> None:
    artifact = ArtifactStore(tmp_path / "store").create(decoded, report)
    metadata = artifact.metadata
    warnings = metadata["warnings"]
    assert isinstance(warnings, list)
    warnings.clear()
    assert artifact.metadata["warnings"] == report.meta.warnings


@pytest.mark.parametrize("changes", [{"warnings": []}, {"limitations": []}, {"package": "wrong"}])
def test_analysis_context_tampering_is_detected(
    tmp_path: Path, decoded: Path, report: Report, changes: dict[str, object]
) -> None:
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    _change_metadata(artifact.path, **changes)
    with pytest.raises(ArtifactError) as caught:
        store.open(artifact.id)
    assert caught.value.code == "INTEGRITY_ERROR"


@pytest.mark.parametrize("bad_config", [{"bad": float("nan")}, {"bad": Path("x")}])
def test_non_json_configuration_is_rejected(
    tmp_path: Path, decoded: Path, report: Report, bad_config: dict[str, object]
) -> None:
    with pytest.raises(ArtifactError) as caught:
        ArtifactStore(tmp_path / "store").create(decoded, report, config=bad_config)
    assert caught.value.code == "INVALID_INPUT"


def test_missing_manifest_and_broken_method_source_are_explicit(
    tmp_path: Path, decoded: Path, report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path / "store")
    manifest = decoded / "AndroidManifest.xml"
    data = manifest.read_bytes()
    manifest.unlink()
    with pytest.raises(ArtifactError) as caught:
        store.create(decoded, report)
    assert caught.value.code == "INVALID_MANIFEST"
    manifest.write_bytes(data)

    def fail_to_index(_root: Path) -> None:
        raise ValueError("synthetic smali parser failure")

    monkeypatch.setattr("reachscope.artifacts.store.build_index", fail_to_index)
    with pytest.raises(ArtifactError) as caught:
        store.create(decoded, report)
    assert caught.value.code == "INVALID_SOURCE"


def test_malformed_locals_artifact_preserves_source_and_warning(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    source = SOURCE.replace(".locals 1", ".locals BAD")
    (decoded / SOURCE_PATH).write_text(source, encoding="utf-8")
    store = ArtifactStore(tmp_path / "store")
    artifact = store.create(decoded, report)
    assert (artifact.path / "source" / SOURCE_PATH).read_text(encoding="utf-8") == source
    assert any("1 行未知语法" in str(warning) for warning in artifact.metadata["warnings"])
    assert store.open(artifact.id).metadata["warnings"] == artifact.metadata["warnings"]


@pytest.mark.parametrize("manifest", ["<broken", "<application/>", '<!DOCTYPE manifest [<!ENTITY a "x">]><manifest/>'])
def test_invalid_manifest_leaves_no_partial_artifact(
    tmp_path: Path, decoded: Path, report: Report, manifest: str
) -> None:
    (decoded / "AndroidManifest.xml").write_text(manifest, encoding="utf-8")
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactError) as caught:
        store.create(decoded, report)
    assert caught.value.code == "INVALID_MANIFEST"
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("budget", [{"max_total_bytes": 1}, {"max_file_bytes": 10}, {"max_files": 1}])
def test_resource_limits_do_not_publish_partial_data(
    tmp_path: Path, decoded: Path, report: Report, budget: dict[str, int]
) -> None:
    store = ArtifactStore(tmp_path / "store", **budget)
    with pytest.raises(ArtifactError) as caught:
        store.create(decoded, report)
    assert caught.value.code == "SIZE_LIMIT"
    assert list(store.root.iterdir()) == []


def test_symlinks_cannot_redirect_saved_evidence(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    link = decoded / "smali" / "linked.smali"
    try:
        link.symlink_to(decoded / SOURCE_PATH)
    except OSError:
        pytest.skip("OS does not permit creating symbolic links")
    with pytest.raises(ArtifactError) as caught:
        ArtifactStore(tmp_path / "store").create(decoded, report)
    assert caught.value.code == "UNSAFE_PATH"


def test_truncated_method_is_identified(tmp_path: Path, decoded: Path, report: Report) -> None:
    (decoded / SOURCE_PATH).write_text(SOURCE.split(".end method", 1)[0], encoding="utf-8")
    artifact = ArtifactStore(tmp_path / "store").create(decoded, report)
    assert artifact.read_method(METHOD_REF)["complete"] is False
    assert any("未闭合" in str(warning) for warning in artifact.metadata["warnings"])


def test_staging_directories_do_not_appear_as_completed_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".staging-interrupted").mkdir()
    assert ArtifactStore(tmp_path).list() == []


def test_snapshot_preserves_sdk_metadata_and_is_independent_of_original(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    (decoded / "apktool.yml").write_text(
        "sdkInfo:\n  minSdkVersion: '21'\n  targetSdkVersion: '35'\n", encoding="utf-8"
    )
    target = snapshot_decoded(decoded, tmp_path / "snapshot")
    parsed = parse_manifest(target / "AndroidManifest.xml")
    assert parsed.min_sdk == 21
    assert parsed.target_sdk == 35
    assert not (target / "res").exists()
    original = (target / SOURCE_PATH).read_bytes()
    (decoded / SOURCE_PATH).write_text("changed after snapshot", encoding="utf-8")
    artifact = ArtifactStore(tmp_path / "store").create(target, report)
    assert (artifact.path / "source" / SOURCE_PATH).read_bytes() == original
    assert (artifact.path / "source" / "apktool.yml").exists()


def test_sdk_metadata_participates_in_artifact_identity(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    first = store.create(decoded, report)
    (decoded / "apktool.yml").write_text("sdkInfo:\n  targetSdkVersion: '35'\n", encoding="utf-8")
    second = store.create(decoded, report)
    assert first.id != second.id


def test_snapshot_accepts_empty_destination_but_never_overwrites_files(
    tmp_path: Path, decoded: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert snapshot_decoded(decoded, empty).samefile(empty)
    with pytest.raises(ArtifactError) as caught:
        snapshot_decoded(decoded, empty)
    assert caught.value.code == "INVALID_INPUT"
    assert (empty / SOURCE_PATH).exists()
    file_target = tmp_path / "user-file"
    file_target.write_text("preserve me", encoding="utf-8")
    with pytest.raises(ArtifactError):
        snapshot_decoded(decoded, file_target)
    assert file_target.read_text(encoding="utf-8") == "preserve me"


def test_snapshot_cannot_be_created_inside_input(decoded: Path) -> None:
    for target in (decoded, decoded / "smali" / "snapshot"):
        with pytest.raises(ArtifactError) as caught:
            snapshot_decoded(decoded, target)
        assert caught.value.code == "INVALID_INPUT"
    assert not (decoded / "smali" / "snapshot").exists()


@pytest.mark.parametrize("budget", [{"max_total_bytes": 1}, {"max_file_bytes": 10}, {"max_files": 1}])
def test_snapshot_budgets_remove_incomplete_output(
    tmp_path: Path, decoded: Path, budget: dict[str, int]
) -> None:
    destination = tmp_path / "snapshot"
    with pytest.raises(ArtifactError) as caught:
        snapshot_decoded(decoded, destination, **budget)
    assert caught.value.code == "SIZE_LIMIT"
    assert not destination.exists()


def test_snapshot_rejects_encoded_dtd_before_analysis(tmp_path: Path, decoded: Path) -> None:
    (decoded / "AndroidManifest.xml").write_bytes(
        '<!DOCTYPE manifest [<!ENTITY a "x">]><manifest/>'.encode("utf-16")
    )
    destination = tmp_path / "snapshot"
    with pytest.raises(ArtifactError) as caught:
        snapshot_decoded(decoded, destination)
    assert caught.value.code == "INVALID_MANIFEST"
    assert not destination.exists()


def test_concurrent_publish_reuses_one_complete_artifact(
    tmp_path: Path, decoded: Path, report: Report
) -> None:
    store = ArtifactStore(tmp_path / "store")
    with ThreadPoolExecutor(max_workers=3) as executor:
        artifacts = list(executor.map(lambda _: store.create(decoded, report), range(3)))
    assert len({artifact.id for artifact in artifacts}) == 1
    assert len(store.list()) == 1
    assert not list(store.root.glob(".staging-*"))


def test_long_paths_round_trip_without_changing_relative_evidence_names(
    tmp_path: Path, report: Report
) -> None:
    """Real file I/O beyond Win32 MAX_PATH; every component stays below 255."""
    base = tmp_path / ("long-path-" + "a" * 65) / ("nested-" + "b" * 65)

    def fixture_io(path: Path) -> Path:
        if os.name == "nt":
            return Path("\\\\?\\" + str(path.absolute()))
        return path

    try:
        decoded = base / "decoded"
        # Similar to Kotlin's generated coroutine class names in real APKs.
        filename = "IntrinsicsKt__" + "createCoroutineUnintercepted$" * 4 + "1.smali"
        relative = f"smali/kotlin/coroutines/intrinsics/{filename}"
        source = fixture_io(decoded / relative)
        assert len(str(decoded / relative)) > 260
        assert len(filename) < 255
        source.parent.mkdir(parents=True)
        source.write_text(SOURCE, encoding="utf-8")
        fixture_io(decoded / "AndroidManifest.xml").write_text(
            '<manifest package="com.example"><application/></manifest>', encoding="utf-8"
        )
        store = ArtifactStore(base / "artifacts")
        first = store.create(decoded, report)
        assert first.read_method(METHOD_REF)["file"] == relative
        assert first.read_method(METHOD_REF)["code"].endswith(".end method")
        assert store.open(first.id).id == first.id
        assert store.list()[0]["artifact_id"] == first.id
        snap = snapshot_decoded(decoded, base / "snapshot")
        assert (snap / relative).read_text(encoding="utf-8") == SOURCE
        second = store.create(snap, report)
        assert second.id == first.id
        if os.name == "nt":
            prefixed = ArtifactStore(fixture_io(base / "artifacts"))
            assert prefixed.open(first.id).read_method(METHOD_REF)["file"] == relative
    finally:
        io_base = fixture_io(base)
        if io_base.exists():
            shutil.rmtree(io_base)


@pytest.mark.skipif(os.name != "nt", reason="Win32 disk/UNC path syntax")
@pytest.mark.parametrize(("original", "expected"), [
    (r"C:\code\folder\..\artifact", r"\\?\C:\code\artifact"),
    (r"\\server\share\folder\..\artifact", r"\\?\UNC\server\share\artifact"),
    (r"\\?\C:\code\artifact", r"\\?\C:\code\artifact"),
    (r"\\?\unc\server\share\artifact", r"\\?\UNC\server\share\artifact"),
])
def test_windows_extended_paths_normalize_drive_and_unc(original: str, expected: str) -> None:
    assert str(_disk_path(Path(original))) == expected
