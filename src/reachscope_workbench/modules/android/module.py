"""Android adapter: reuse ReachScope's analyzer, persist evidence, expose real code."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, cast

from reachscope.artifacts import Artifact, ArtifactError, ArtifactStore
from reachscope.ingest.apk import ApkInput, IngestError
from reachscope.query import EvidenceSession, QueryError

from ...core.models import (
    Evidence,
    ModuleResult,
    ModuleSpec,
    Observation,
    RunContext,
    WorkbenchError,
)
from .manifest_worker import inspect_manifest
from .posture import REVIEW_IDS
from .process import ProcessResult, run_process

SAMPLES = ("bridge", "cross_component", "wrong_key", "permission", "missing")
_UPLOAD_ID = re.compile(r"[0-9a-f]{32}\Z")
_ARTIFACT_ID = re.compile(r"[0-9a-f]{64}\Z")
MAX_COMPONENTS = 200
MAX_CHAINS = 100
CHECKS = ("manifest", "code_paths")


def _selected_checks(value: Any) -> list[str]:
    if value is None:
        return list(CHECKS)
    if not isinstance(value, list) or not value or len(value) > len(CHECKS) or any(not isinstance(item, str) or item not in CHECKS for item in value):
        raise WorkbenchError("INVALID_CONFIG", "Android checks must select manifest and/or code_paths")
    return [check for check in CHECKS if check in value or check == "manifest"]


def _execution(checks: list[str]) -> list[dict[str, str]]:
    return [{"id": check, "label": label, "status": "completed" if check in checks else "skipped",
             "reason": "已执行" if check in checks else "本次未选择，未建立源码索引或分析代码路径"}
            for check, label in (("manifest", "基础配置、权限与入口"), ("code_paths", "候选代码路径与源码"))]


class AndroidModule:
    spec = ModuleSpec(
        id="android", name="Android 客户端",
        description="分析 APK 的导出入口、深链、组件传参和 WebView 候选路径，保留原始代码证据。",
        capabilities=["manifest", "deeplinks", "candidate_paths", "method_source", "claim_check"],
        input_modes=["demo", "apk"],
    )

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = config.get("mode", "demo")
        if mode not in self.spec.input_modes:
            raise WorkbenchError("INVALID_CONFIG", "Android mode must be demo or apk")
        timeout = config.get("timeout", 600)
        if type(timeout) not in (int, float) or not 1 <= timeout <= 900:
            raise WorkbenchError("INVALID_CONFIG", "Analysis timeout must be between 1 and 900 seconds")
        clean: dict[str, Any] = {"mode": mode, "timeout": float(timeout), "checks": _selected_checks(config.get("checks"))}
        if mode == "demo":
            sample = config.get("sample", "cross_component")
            if sample not in SAMPLES:
                raise WorkbenchError("INVALID_CONFIG", f"Unknown Android sample; choose {', '.join(SAMPLES)}")
            clean["sample"] = sample
        else:
            upload_id = config.get("upload_id")
            if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
                raise WorkbenchError("INVALID_CONFIG", "APK analysis requires a valid upload_id")
            filename = config.get("filename", "uploaded.apk")
            if not isinstance(filename, str) or not filename.lower().endswith(".apk"):
                raise WorkbenchError("INVALID_CONFIG", "Upload filename must end in .apk")
            clean.update(upload_id=upload_id, filename=Path(filename.replace("\\", "/")).name[:200])
            apktool = config.get("apktool")
            if apktool is not None:
                if not isinstance(apktool, str) or not apktool.strip() or len(apktool) > 2000:
                    raise WorkbenchError("INVALID_CONFIG", "apktool must be a path to a local JAR")
                # HTTP configuration may choose a JAR; executables are operator-configured.
                if Path(apktool).suffix.lower() != ".jar":
                    raise WorkbenchError("INVALID_CONFIG", "Only .jar paths are accepted in APK task settings")
                clean["apktool"] = apktool
        return clean

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        clean = self.validate(config)
        workspace = context.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        store = workspace / "artifacts"
        env = dict(os.environ)
        # Both editable checkouts and installed wheels use this package's own engine.
        source_root = str(Path(__file__).resolve().parents[3])
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        context.progress(5, "校验 Android 输入与本地分析环境")
        if "code_paths" not in clean["checks"]:
            return await _manifest_only(clean, context, env)
        if clean["mode"] == "demo":
            sample = files("reachscope").joinpath("samples", clean["sample"])
            with as_file(sample) as decoded:
                configuration = await asyncio.to_thread(inspect_manifest, decoded / "AndroidManifest.xml")
                command = [sys.executable, "-m", "reachscope", "index", str(decoded), "--store", str(store)]
                context.progress(15, "在独立进程中索引合成 Android 源码")
                completed = await run_process(
                    command, timeout=clean["timeout"], env=env, cwd=str(workspace),
                )
            artifact_id = _indexed_artifact(completed)
            target = f"sample:{clean['sample']}"
        else:
            uploaded = _upload_path(context.uploads, clean["upload_id"])
            try:
                await asyncio.to_thread(ApkInput.load, uploaded)
            except IngestError as exc:
                raise WorkbenchError("INVALID_APK", exc.to_message()) from exc
            apktool = _apktool_path(clean.get("apktool"))
            output = workspace / "scan"
            command = [sys.executable, "-m", "reachscope_workbench.modules.android.code_worker", str(uploaded),
                       "--out", str(output), "--store", str(store), "--no-apkid", "--quiet"]
            if apktool:
                command.extend(["--apktool", apktool])
            context.progress(15, "解码并分析 APK；目标应用不会被执行")
            try:
                completed = await run_process(command, timeout=clean["timeout"], env=env, cwd=str(workspace))
            finally:
                for path in workspace.glob("android-*"):
                    if path.is_dir() and not path.is_symlink():
                        await asyncio.to_thread(shutil.rmtree, path, True)
            _check_process(completed)
            try:
                pointer = json.loads((output / "artifact.json").read_text(encoding="utf-8"))
                artifact_id = pointer["artifact_id"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise WorkbenchError("WORKER_OUTPUT_INVALID", "Analysis did not produce an artifact identity") from exc
            target = clean["filename"]
            configuration_path = output / "manifest-result.json"
            try:
                configuration = await asyncio.to_thread(_read_configuration, configuration_path)
            except (TypeError, ValueError, OSError) as exc:
                raise WorkbenchError("WORKER_OUTPUT_INVALID", "Configuration worker returned an invalid result") from exc
        context.progress(80, "校验保存的代码快照并整理组件、路径和方法索引")
        try:
            result = await asyncio.to_thread(_assemble_result, workspace, artifact_id, target, completed.stderr)
        except ArtifactError as exc:
            raise WorkbenchError("EVIDENCE_INVALID", f"Saved Android evidence could not be verified: {exc}") from exc
        context.progress(100, "Android 分析完成；可以逐步查看路径和原始代码")
        result.details["execution"] = _execution(clean["checks"])
        _apply_configuration(result, configuration)
        return result


async def _manifest_only(config: dict[str, Any], context: RunContext, env: dict[str, str]) -> ModuleResult:
    output = context.workspace.resolve() / "manifest-result.json"
    command = [sys.executable, "-m", "reachscope_workbench.modules.android.manifest_worker", "--output", str(output)]
    context.progress(15, "仅解析清单配置，不读取 smali 或构建代码图")
    if config["mode"] == "demo":
        sample = files("reachscope").joinpath("samples", config["sample"])
        with as_file(sample) as decoded:
            completed = await run_process([*command, "--manifest", str(decoded / "AndroidManifest.xml")],
                                          timeout=config["timeout"], env=env, cwd=str(context.workspace))
        target = f"sample:{config['sample']}"
    else:
        uploaded = _upload_path(context.uploads, config["upload_id"])
        try:
            await asyncio.to_thread(ApkInput.load, uploaded)
        except IngestError as exc:
            raise WorkbenchError("INVALID_APK", exc.to_message()) from exc
        jar = _apktool_path(config.get("apktool"))
        command.extend(["--apk", str(uploaded)])
        if jar:
            command.extend(["--apktool", jar])
        try:
            completed = await run_process(command, timeout=config["timeout"], env=env, cwd=str(context.workspace))
        finally:
            # A cancelled process cannot run TemporaryDirectory.__exit__. This
            # worker owns only these private generated decoder directories.
            for path in context.workspace.glob("manifest-*"):
                if path.is_dir() and not path.is_symlink():
                    await asyncio.to_thread(shutil.rmtree, path, True)
        target = config["filename"]
    _check_process(completed)
    try:
        data = _read_configuration(output)
    except (TypeError, ValueError, OSError) as exc:
        raise WorkbenchError("WORKER_OUTPUT_INVALID", "Manifest worker did not return its bounded result") from exc
    context.progress(100, "清单配置检查完成；代码路径未执行")
    evidence = Evidence(id="manifest", kind="manifest_configuration", title="Android 清单配置",
                        source="AndroidManifest.xml", data=data, sha256=data["manifest_sha256"])
    result = ModuleResult(
        module="android", target=target,
        summary={"package": data["package"], "components": data["components_total"], "exported": data["exported_total"],
                 "deeplinks": len(data["deeplinks"]), "permissions": data["permissions_total"], "warnings": len(data["warnings"])},
        evidence=[evidence], observations=[Observation(
            id="manifest-entry", title=f"观察到 {data['exported_total']} 个导出组件", severity="info", category="android_attack_surface",
            description="仅依据清单配置记录；代码实现、实际可调用性与风险路径未评估。", evidence_ids=["manifest"],
            recommendation="如需代码证据，另选候选代码路径检查。",
        )],
        details={**data, "entries": [], "chains": [], "methods": [], "questions": [], "query_operations": [],
                 "execution": _execution(config["checks"]), "worker_log_tail": completed.stderr[-4000:]},
        limitations=["本次只解析 AndroidManifest.xml，未建立代码工件、验证实现、分析路径或判断可利用性。",
                     "导出组件与声明权限不等于可利用漏洞，资源引用及运行时配置仍可能需要复核。"],
    )
    _apply_configuration(result, data)
    return result


def _read_configuration(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Configuration output exceeds its budget")
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("security_review"), dict):
        raise TypeError("Configuration output must include a structured review")
    required = {"package", "manifest_sha256", "components", "components_total", "exported_total", "deeplinks", "permissions_total", "warnings",
                "target_sdk", "min_sdk", "permissions", "declared_permissions", "sdk_source"}
    review = data["security_review"]
    if not required.issubset(data) or not isinstance(data["package"], str) or not _ARTIFACT_ID.fullmatch(str(data["manifest_sha256"])):
        raise ValueError("Configuration output is missing required bounded fields")
    if review.get("version") != 1 or review.get("package") != data["package"] or not isinstance(review.get("checks"), list) or len(review["checks"]) != 8:
        raise ValueError("Configuration review has an unsupported structure")
    if (not isinstance(data["components"], list) or len(data["components"]) > 200 or
            any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in data["components"]) or
            not isinstance(data["permissions"], list) or len(data["permissions"]) > 500 or not all(isinstance(item, str) for item in data["permissions"]) or
            not isinstance(data["declared_permissions"], dict) or not isinstance(data["sdk_source"], dict) or
            any(type(data[key]) is not int or data[key] < 0 for key in ("components_total", "exported_total", "permissions_total")) or
            not isinstance(data["deeplinks"], list) or not isinstance(data["warnings"], list) or
            not isinstance(review.get("coverage"), dict) or not isinstance(review.get("limitations"), list)):
        raise ValueError("Configuration output contains invalid inventory fields")
    identities: set[str] = set()
    for check in review["checks"]:
        if (not isinstance(check, dict) or check.get("status") not in {"pass", "review", "unknown", "not_applicable"}
                or not isinstance(check.get("id"), str) or check["id"] not in REVIEW_IDS or check["id"] in identities
                or check.get("resource_id") != data["package"] or check.get("evidence_ids") != [f"android-review:{check['id']}"]
                or any(not isinstance(check.get(key), str) for key in ("title", "description", "recommendation", "source"))
                or not isinstance(check.get("facts"), list) or len(check["facts"]) > 80 or type(check.get("complete")) is not bool
                or not isinstance(check.get("guidance"), dict)):
            raise ValueError("Configuration review contains an invalid check")
        identities.add(check["id"])
    return cast("dict[str, Any]", data)


def _apply_configuration(result: ModuleResult, configuration: dict[str, Any]) -> None:
    for key in ("security_review", "target_sdk", "min_sdk", "permissions", "declared_permissions", "sdk_source"):
        result.details[key] = configuration[key]
    configurations = {item["name"]: item for item in configuration["components"]}
    for component in result.details.get("components", []):
        source = configurations.get(component.get("name"), {})
        for key in ("effective_exported", "export_reason", "exported_assessment", "inherited_permission", "effective_permission",
                    "permission_levels", "read_permission", "write_permission", "path_permissions", "grant_uri_permissions"):
            if key in source:
                component[key] = source[key]
    checks = configuration["security_review"]["checks"]
    result.summary["configuration_reviews"] = sum(check["status"] == "review" for check in checks)
    result.summary["configuration_unknown"] = sum(check["status"] == "unknown" for check in checks)
    result.summary["exported"] = configuration.get("exported_total", result.summary.get("exported", 0))
    result.summary["exported_unknown"] = configuration.get("exported_unknown", 0)
    for check in checks:
        raw = json.dumps(check, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        result.evidence.append(Evidence(id=check["evidence_ids"][0], kind="android_configuration_review",
                                        title=check["title"], source=check["source"], data=check,
                                        sha256=hashlib.sha256(raw).hexdigest()))
        if check["status"] == "review":
            result.observations.append(Observation(id=f"android-config:{check['id']}", title=check["title"], severity="info",
                                                  category="android_configuration", description=check["description"],
                                                  evidence_ids=check["evidence_ids"], confidence="configuration_observed",
                                                  recommendation=check["recommendation"]))
    result.limitations.extend(configuration["security_review"]["limitations"])


def _upload_path(root: Path, upload_id: str) -> Path:
    directory = root.resolve()
    original = directory / upload_id
    if original.is_symlink():
        raise WorkbenchError("INVALID_UPLOAD", "Uploaded APK must be a regular local file")
    path = original.resolve()
    if path.parent != directory or not path.is_file():
        raise WorkbenchError("UPLOAD_NOT_FOUND", "Uploaded APK is not available")
    return path


def _apktool_path(explicit: str | None) -> str | None:
    jar = explicit or os.environ.get("APKTOOL_JAR")
    if jar:
        if Path(jar).suffix.lower() != ".jar" or not Path(jar).is_file():
            raise WorkbenchError("APKTOOL_UNAVAILABLE", "APKTOOL_JAR must point to an installed apktool JAR")
        if shutil.which("java") is None:
            raise WorkbenchError("JAVA_UNAVAILABLE", "APK analysis needs Java on PATH")
        return str(Path(jar).resolve())
    if shutil.which("apktool") is None:
        raise WorkbenchError("APKTOOL_UNAVAILABLE", "Configure APKTOOL_JAR or install apktool on PATH")
    return None


def _check_process(completed: ProcessResult) -> None:
    if completed.returncode:
        message = (completed.stderr or completed.stdout).strip()[-4000:]
        code = "APK_UNANALYZABLE" if completed.returncode == 3 else "ANALYSIS_FAILED"
        raise WorkbenchError(code, message or f"Android worker exited with code {completed.returncode}")


def _indexed_artifact(completed: ProcessResult) -> str:
    _check_process(completed)
    try:
        result = json.loads(completed.stdout)
        identity = result["artifact_id"]
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkbenchError("WORKER_OUTPUT_INVALID", "Index worker returned an invalid result") from exc
    if not isinstance(identity, str) or not _ARTIFACT_ID.fullmatch(identity):
        raise WorkbenchError("WORKER_OUTPUT_INVALID", "Index worker returned an invalid artifact identity")
    return identity


def open_artifact(workspace: Path, artifact_id: str) -> Artifact:
    """Open only the artifact under the caller's known job workspace."""
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise WorkbenchError("INVALID_ARTIFACT", "Invalid Android artifact identity")
    try:
        return ArtifactStore(workspace / "artifacts").open(artifact_id)
    except ArtifactError as exc:
        raise WorkbenchError(exc.code, str(exc)) from exc


def read_method(
    workspace: Path, artifact_id: str, method_ref: str, *, offset: int = 0, limit: int = 80,
) -> dict[str, Any]:
    """Revalidate and page real source; call through to_thread from async transports."""
    try:
        return EvidenceSession(open_artifact(workspace, artifact_id)).method(method_ref, offset=offset, limit=limit)
    except QueryError as exc:
        raise WorkbenchError(exc.code, str(exc)) from exc


def query_artifact(
    workspace: Path, artifact_id: str, topic: str, *, query: str = "", entry: str | None = None,
    ref: str = "", offset: int = 0, limit: int = 50, claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One API adapter entry point; retain the engine's paged response contracts."""
    session = EvidenceSession(open_artifact(workspace, artifact_id))
    try:
        if topic == "methods":
            return session.methods(query, offset=offset, limit=limit)
        if topic == "method":
            return session.method(ref, offset=offset, limit=limit)
        if topic == "entries":
            return session.entries(query, offset=offset, limit=limit)
        if topic == "chains":
            return session.chains(entry, offset=offset, limit=limit)
        if topic == "chain":
            return session.chain(ref)
        if topic == "questions":
            return session.questions()
        if topic == "check":
            if claim is None:
                raise WorkbenchError("INVALID_CLAIM", "A claim object is required")
            return session.check(claim)
        if topic == "overview":
            return session.overview()
    except QueryError as exc:
        raise WorkbenchError(exc.code, str(exc)) from exc
    raise WorkbenchError("INVALID_QUERY", "Unknown Android evidence query")


def _method_for_location(artifact: Artifact, source: dict[str, Any], cache: dict[str, list[Any]]) -> str | None:
    file = str(source.get("file", ""))
    if file not in cache:
        parts = file.split("/", 1)
        descriptor = "L" + parts[1][:-6] + ";->" if len(parts) == 2 and file.endswith(".smali") else ""
        page = artifact.list_methods(query=descriptor, limit=500) if descriptor else {"methods": []}
        cache[file] = cast("list[Any]", page["methods"])
    for method in cache[file]:
        if method["file"] == file and method["start_line"] <= source.get("line", 0) <= method["end_line"]:
            return str(method["method_ref"])
    return None


def _assemble_result(workspace: Path, artifact_id: str, target: str, worker_stderr: str) -> ModuleResult:
    artifact = open_artifact(workspace, artifact_id)
    session = EvidenceSession(artifact)
    report = artifact.report
    entries = session.entries(limit=100)["data"]
    components = [item.to_dict() for item in report.components[:MAX_COMPONENTS]]
    methods = session.methods(limit=100)
    chains: list[dict[str, Any]] = []
    evidence: list[Evidence] = []
    observations: list[Observation] = []
    metadata = artifact.metadata
    source_files = metadata.get("files", [])
    manifest_sha = next((str(item["sha256"]) for item in source_files
                         if isinstance(item, dict) and item.get("path") == "AndroidManifest.xml"), "") if isinstance(source_files, list) else ""
    evidence.append(Evidence(
        id="manifest", kind="manifest_configuration", title="Android manifest 配置",
        source="AndroidManifest.xml", sha256=manifest_sha,
        data={"package": report.meta.package, "target_sdk": report.meta.target_sdk,
              "min_sdk": report.meta.min_sdk, "components": components},
    ))
    method_cache: dict[str, list[Any]] = {}
    for chain in report.chains[:MAX_CHAINS]:
        data = session.chain(chain.id)["data"]
        for step in data["steps"]:
            if step.get("source"):
                step["method_ref"] = _method_for_location(artifact, step["source"], method_cache)
        chains.append(data)
        evidence.append(Evidence(
            id=f"chain:{chain.id}", kind="static_candidate_path", title=f"候选路径 {chain.id}",
            source=f"artifact:{artifact.id}", data=data,
        ))
    for finding in report.findings[:100]:
        observations.append(Observation(
            id=f"risk:{finding.chain_id}", title=finding.title, severity="medium",
            category="android_static_risk", description=finding.summary,
            evidence_ids=[f"chain:{finding.chain_id}"] if any(chain["id"] == finding.chain_id for chain in chains) else ["manifest"],
            confidence="static_inference", recommendation="结合路径源码和运行条件人工复核；静态判据不等同于可利用性证明。",
        ))
    exposed = [item for item in report.components if item.exported]
    if exposed:
        observations.append(Observation(
            id="exported-components", title=f"观察到 {len(exposed)} 个导出组件", severity="info",
            category="android_attack_surface", description="导出配置是入口事实，权限及调用方式仍需逐项检查。",
            evidence_ids=["manifest"], recommendation="查看权限、实现状态与对应候选路径。",
        ))
    missing = [component for component in report.components if not component.impl_present]
    if missing:
        observations.append(Observation(
            id="missing-implementation", title=f"{len(missing)} 个组件实现不可见", severity="info",
            category="analysis_gap", description="索引内没有找到具体实现；可能存在动态加载、混淆或输入缺失。",
            evidence_ids=["manifest"], confidence="unknown", recommendation="补充可分析的代码后重新检查。",
        ))
    overview = session.overview()
    limitations = list(overview["limitations"])
    limitations.append("APKiD is not run by this workbench adapter; APK protection status may be unknown.")
    details = {
        "artifact_id": artifact.id, "package": report.meta.package,
        "components": components, "entries": entries, "deeplinks": [item.to_dict() for item in report.deeplinks[:200]],
        "chains": chains, "methods": methods["data"], "questions": session.questions()["data"],
        "warnings": report.meta.warnings[:50], "protection": report.protection.to_dict(),
        "limits": {"components_total": len(report.components), "components_returned": len(components),
                   "chains_total": len(report.chains), "chains_returned": len(chains),
                   "methods_total": methods["pagination"]["total"], "methods_returned": len(methods["data"]),
                   "warnings_total": len(report.meta.warnings)},
        "worker_log_tail": worker_stderr[-4000:],
        "query_operations": ["overview", "entries", "chains", "chain", "methods", "method", "questions", "check"],
    }
    return ModuleResult(
        module="android", target=target,
        summary={"package": report.meta.package, "components": len(report.components),
                 "exported": len(exposed), "deeplinks": len(report.deeplinks), "chains": len(report.chains),
                 "findings": len(report.findings), "methods": methods["pagination"]["total"],
                 "warnings": len(report.meta.warnings)},
        evidence=evidence, observations=observations, details=details, limitations=limitations,
    )
