"""Android module workflows use real persisted source and cancellable workers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from reachscope_workbench.core.models import RunContext, WorkbenchError
from reachscope_workbench.modules.android import AndroidModule, query_artifact, read_method
from reachscope_workbench.modules.android import module as android
from reachscope_workbench.modules.android.process import OUTPUT_LIMIT, ProcessResult, run_process


@pytest.fixture
def context(tmp_path: Path) -> RunContext:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    return RunContext(job_id="test-job", workspace=tmp_path / "job", uploads=uploads,
                      progress=lambda percent, message: None)


@pytest.mark.parametrize("config", [
    {"mode": "decoded", "path": "anywhere"},
    {"mode": "demo", "sample": "../../outside"},
    {"mode": "demo", "timeout": True},
    {"mode": "demo", "timeout": float("nan")},
    {"mode": "demo", "timeout": 901},
    {"mode": "apk", "upload_id": "../../outside"},
    {"mode": "apk", "upload_id": "a" * 32, "filename": "x.exe"},
    {"mode": "apk", "upload_id": "a" * 32, "apktool": "cmd.exe"},
])
def test_task_configuration_is_explicit(config: dict[str, Any]) -> None:
    with pytest.raises(WorkbenchError) as caught:
        AndroidModule().validate(config)
    assert caught.value.code == "INVALID_CONFIG"


@pytest.mark.asyncio
@pytest.mark.parametrize(("sample", "paths", "findings"), [
    ("cross_component", 1, 0), ("wrong_key", 0, 0), ("bridge", 1, 1),
    ("missing", 0, 0), ("permission", 1, 0),
])
async def test_real_source_demo_preserves_analysis_boundaries(
    context: RunContext, sample: str, paths: int, findings: int,
) -> None:
    result = await AndroidModule().run({"mode": "demo", "sample": sample}, context)
    assert result.module == "android" and result.target == f"sample:{sample}"
    assert result.summary["chains"] == paths and result.summary["findings"] == findings
    assert result.details["artifact_id"]
    assert result.evidence[0].id == "manifest"
    assert result.evidence[0].sha256
    assert all(observation.confidence != "confirmed" for observation in result.observations)
    assert any("not proof" in limitation or "not confirmed" in limitation for limitation in result.limitations)
    if sample == "cross_component":
        steps = result.details["chains"][0]["steps"]
        source, target = [step["method_ref"] for step in steps]
        assert source and target
        first = await asyncio.to_thread(read_method, context.workspace, result.details["artifact_id"], source)
        second = await asyncio.to_thread(read_method, context.workspace, result.details["artifact_id"], target)
        assert "putExtra" in first["data"]["code"]
        assert "getStringExtra" in second["data"]["code"] and "loadUrl" in second["data"]["code"]


@pytest.mark.asyncio
async def test_query_pages_and_claim_check_reuse_saved_artifact(context: RunContext) -> None:
    result = await AndroidModule().run({"mode": "demo", "sample": "cross_component"}, context)
    artifact_id = result.details["artifact_id"]
    methods = query_artifact(context.workspace, artifact_id, "methods", query="CrossTarget", limit=1)
    assert methods["pagination"]["total"] >= 1
    code = query_artifact(context.workspace, artifact_id, "method", ref=methods["data"][0]["reference"], limit=2)
    assert code["data"]["truncated"]
    checked = query_artifact(context.workspace, artifact_id, "check", claim={
        "kind": "reachability", "entry": {"kind": "component", "name": "com.example.app.CrossEntry"},
        "sink": {"kind": "webview"},
    })
    assert checked["data"]["verdict"]["status"] == "SUPPORTED"
    assert checked["scope"] == "static_analysis_report"
    with pytest.raises(WorkbenchError):
        query_artifact(context.workspace, artifact_id, "method", ref="../../outside")
    with pytest.raises(WorkbenchError, match="Unknown"):
        query_artifact(context.workspace, artifact_id, "invented")
    with pytest.raises(WorkbenchError, match="claim object"):
        query_artifact(context.workspace, artifact_id, "check")


@pytest.mark.asyncio
async def test_apk_requires_valid_uploaded_archive(context: RunContext) -> None:
    config = {"mode": "apk", "upload_id": "a" * 32}
    with pytest.raises(WorkbenchError) as caught:
        await AndroidModule().run(config, context)
    assert caught.value.code == "UPLOAD_NOT_FOUND"
    (context.uploads / ("a" * 32)).write_text("not an APK", encoding="utf-8")
    with pytest.raises(WorkbenchError) as caught:
        await AndroidModule().run(config, context)
    assert caught.value.code == "INVALID_APK"


def test_missing_decoder_is_a_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APKTOOL_JAR", raising=False)
    monkeypatch.setattr(android.shutil, "which", lambda _: None)
    with pytest.raises(WorkbenchError) as caught:
        android._apktool_path(None)
    assert caught.value.code == "APKTOOL_UNAVAILABLE"
    with pytest.raises(WorkbenchError) as caught:
        android._apktool_path("/missing/apktool.jar")
    assert caught.value.code == "APKTOOL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_apk_worker_uses_uploaded_id_and_no_shell(
    context: RunContext, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A real demo artifact supplies the expected successful worker output.
    initial = await AndroidModule().run({"mode": "demo", "sample": "cross_component"}, context)
    apk = context.uploads / ("b" * 32)
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", "binary-placeholder")
    commands: list[list[str]] = []

    async def fake_worker(command: list[str], **kwargs: Any) -> ProcessResult:
        commands.append(command)
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        output = Path(command[command.index("--out") + 1])
        output.mkdir()
        (output / "artifact.json").write_text(json.dumps({"artifact_id": initial.details["artifact_id"]}), encoding="utf-8")
        configuration = {**initial.details, "manifest_sha256": initial.evidence[0].sha256,
                         "components_total": initial.summary["components"], "exported_total": initial.summary["exported"],
                         "permissions_total": len(initial.details["permissions"])}
        (output / "manifest-result.json").write_text(json.dumps(configuration), encoding="utf-8")
        return ProcessResult(0, "scan complete", "protection: skipped by --no-apkid")

    monkeypatch.setattr(android, "run_process", fake_worker)
    monkeypatch.setattr(android, "_apktool_path", lambda _: "operator apktool.jar")
    result = await AndroidModule().run({"mode": "apk", "upload_id": "b" * 32, "filename": "../../test.apk"}, context)
    assert result.target == "test.apk"
    assert commands[0][0] == sys.executable
    assert str(apk) in commands[0] and "--no-apkid" in commands[0]
    assert commands[0][commands[0].index("--apktool") + 1] == "operator apktool.jar"


@pytest.mark.asyncio
async def test_worker_failure_is_not_an_empty_success(
    context: RunContext, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> ProcessResult:
        return ProcessResult(3, "", "Cannot analyze protected APK")

    monkeypatch.setattr(android, "run_process", broken)
    with pytest.raises(WorkbenchError) as caught:
        await AndroidModule().run({"mode": "demo"}, context)
    assert caught.value.code == "APK_UNANALYZABLE"
    assert "protected" in str(caught.value)


@pytest.mark.asyncio
async def test_worker_timeout_stops_running_process(tmp_path: Path) -> None:
    start = time.monotonic()
    with pytest.raises(WorkbenchError) as caught:
        await run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                          timeout=.2, env=dict(os.environ), cwd=str(tmp_path))
    assert caught.value.code == "ANALYSIS_TIMEOUT"
    assert time.monotonic() - start < 15


@pytest.mark.asyncio
async def test_cancel_terminates_worker_and_its_child(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
    child += "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(.05)')"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    task = asyncio.create_task(run_process([sys.executable, "-c", parent], timeout=60,
                                           env=dict(os.environ), cwd=str(tmp_path)))
    for _ in range(150):
        if heartbeat.exists():
            break
        await asyncio.sleep(.02)
    assert heartbeat.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    content = heartbeat.read_text(encoding="utf-8")
    await asyncio.sleep(.3)
    assert heartbeat.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_timeout_owns_child_even_if_worker_exits_before_pipe_closes(tmp_path: Path) -> None:
    heartbeat = tmp_path / "orphan-heartbeat"
    child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
    child += "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(.05)')"
    parent = f"import subprocess,sys,time,os; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(.3); os._exit(0)"
    with pytest.raises(WorkbenchError) as caught:
        await run_process([sys.executable, "-c", parent], timeout=1, env=dict(os.environ), cwd=str(tmp_path))
    assert caught.value.code == "ANALYSIS_TIMEOUT"
    assert heartbeat.exists()
    content = heartbeat.read_text(encoding="utf-8")
    await asyncio.sleep(.3)
    assert heartbeat.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_subprocess_drains_both_streams_with_bounded_tails(tmp_path: Path) -> None:
    code = "import sys; sys.stdout.write('x'*200000+'END'); sys.stderr.write('y'*200000+'ERR')"
    result = await run_process([sys.executable, "-c", code], timeout=20, env=dict(os.environ), cwd=str(tmp_path))
    assert result.returncode == 0
    assert len(result.stdout) <= OUTPUT_LIMIT and result.stdout.endswith("END")
    assert len(result.stderr) <= OUTPUT_LIMIT and result.stderr.endswith("ERR")


@pytest.mark.parametrize("output", ["not json", "[]", '{"artifact_id":"oops"}'])
def test_invalid_worker_output_is_rejected(output: str) -> None:
    with pytest.raises(WorkbenchError):
        android._indexed_artifact(ProcessResult(0, output, ""))
