"""Local HTTP adapter. Analysis modules and domain state are transport independent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import weakref
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..core.advisory_service import AdvisoryService
from ..core.ai_contracts import AdvisoryProvider
from ..core.assets import AssetRepository
from ..core.catalog import catalog
from ..core.inspections import InspectionService
from ..core.locking import WorkspaceLock
from ..core.models import WorkbenchError
from ..core.registry import ModuleRegistry
from ..core.repository import JobRepository
from ..core.runner import JobRunner
from ..core.scenarios.loader import ScenarioLoader
from ..integrations.ai_provider import ChatCompletionsProvider
from ..integrations.local_lab import LocalLab
from .advisory import advisory_router
from .collaboration import collaboration_router
from .contracts import AssetCreate, InspectionCreate, JobCreate
from .errors import domain_status, failure, idempotency_key
from .host_downloads import register_host_downloads
from .lab import lab_router
from .limits import RequestBudgetMiddleware

logger = logging.getLogger(__name__)
IDENTIFIER = re.compile(r"[a-f0-9]{32}\Z")
MAX_UPLOAD = 256 * 1024 * 1024
# Built-in scenario packs ship inside the package; user roots are appended at runtime.
BUILTIN_SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
# Per-process registry of live app instances per workspace (weak: apps that never
# start a lifespan — contract generation, tooling — age out on collection).
_ACTIVE_WORKSPACES: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()
_WORKSPACE_GUARD = threading.Lock()


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise WorkbenchError("INVALID_ID", "非法的任务标识")
    return value


def default_registry() -> ModuleRegistry:
    from ..modules.android import AndroidModule
    from ..modules.cloud import CloudModule
    from ..modules.host import HostModule
    from ..modules.web import WebModule

    return ModuleRegistry([AndroidModule(), WebModule(), CloudModule(), HostModule()])


def create_app(data_dir: Path, registry: ModuleRegistry | None = None, *, advisory_provider: AdvisoryProvider | None = None,
               scenarios_dirs: Sequence[Path] = ()) -> FastAPI:
    directory = data_dir.absolute()
    modules = registry or default_registry()
    scenario_catalog = ScenarioLoader([BUILTIN_SCENARIOS, *scenarios_dirs]).discover()
    lab = LocalLab(catalog=scenario_catalog)
    lock = WorkspaceLock(directory)
    resolved = str(directory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        lock.acquire()
        try:
            await asyncio.to_thread(repository.check_schema_version)
            await runner.start()
            await advisory.start()
            yield
        finally:
            try:
                await advisory.stop()
            finally:
                try:
                    await runner.stop()
                finally:
                    try:
                        await asyncio.to_thread(lab.stop)
                    finally:
                        lock.release()
                        _ACTIVE_WORKSPACES.pop(_, None)

    with _WORKSPACE_GUARD:
        if resolved in _ACTIVE_WORKSPACES.values():
            raise WorkbenchError("WORKSPACE_BUSY", "这个进程已经有一个实例在用这个工作目录")
        # Migration is a write too: never upgrade a workspace owned by another server.
        lock.acquire()
        try:
            repository = JobRepository(directory / "workbench.sqlite3")
            inventory = AssetRepository(repository)
            inspections = InspectionService(inventory, modules, directory / "uploads")
            runner = JobRunner(repository, modules, directory)
            advisory = AdvisoryService(repository, advisory_provider or ChatCompletionsProvider())
        finally:
            lock.release()
        app = FastAPI(title="ReachScope Workbench", version=__version__, lifespan=lifespan,
                      docs_url=None, redoc_url=None)
        # The registry closes the create→lifespan gap in-process; the OS lease
        # arbitrates across processes at lifespan start. A finalizer on the app
        # cannot do this job: FastAPI apps are cyclically referenced (release
        # would wait for cyclic GC), and an open lock handle blocks workspace
        # cleanup on Windows for tooling that never starts a lifespan.
        _ACTIVE_WORKSPACES[app] = resolved

    app.state.repository, app.state.runner = repository, runner
    app.state.advisory = advisory
    app.state.lab = lab
    app.include_router(advisory_router(advisory))
    app.include_router(lab_router(lab))
    app.include_router(collaboration_router(repository))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    app.add_middleware(RequestBudgetMiddleware)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Response:
        request.state.request_id = uuid4().hex
        started = time.perf_counter()
        # Request paths are untrusted even on loopback. ASCII JSON quoting
        # prevents terminal escape/bidi controls from altering audit displays.
        logged_path = json.dumps(request.url.path[:250], ensure_ascii=True)
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if request.headers.get("x-reachscope-client") != "workbench":
                return failure(request, "LOCAL_CLIENT_REQUIRED", "缺少本地客户端标识", 403)
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return failure(request, "CROSS_ORIGIN_DENIED", "不接受跨站请求", 403)
        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception("request_failed request_id=%s method=%s path=%s", request.state.request_id,
                             request.method, logged_path)
            response = failure(request, "INTERNAL_ERROR", "本地服务处理失败；可提供操作编号帮助定位。", 500)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            logger.info("request_completed request_id=%s method=%s path=%s status=%d elapsed_ms=%.1f",
                        request.state.request_id, request.method, logged_path, response.status_code,
                        (time.perf_counter() - started) * 1000)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    @app.exception_handler(WorkbenchError)
    async def domain_error(request: Request, exc: WorkbenchError) -> JSONResponse:
        return failure(request, exc.code, exc.message, domain_status(exc.code))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return failure(request, "INVALID_REQUEST", "请求字段无效", 422,
                       details=[{"field": [part if isinstance(part, int) else str(part).encode("utf-8", "replace").decode("utf-8")[:80]
                                            for part in error["loc"][:10]],
                                 "message": str(error["msg"]).encode("utf-8", "replace").decode("utf-8")[:300]}
                                for error in exc.errors()[:30]])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = failure(request, "ROUTE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                           "找不到这个接口" if exc.status_code == 404 else "请求方法或格式不受支持", exc.status_code)
        for name, value in (exc.headers or {}).items():
            if name.lower() in {"allow", "retry-after", "www-authenticate"}:
                response.headers[name] = value
        return response

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
        logger.error("database_failure request_id=%s type=%s", request.state.request_id, type(exc).__name__)
        response = failure(request, "WORKSPACE_BUSY" if busy else "STORAGE_ERROR",
                           "工作区暂忙，请稍后使用同一操作标识重试。" if busy else "本地存储不可用，请检查磁盘空间和文件权限。", 503)
        response.headers["Retry-After"] = "2"
        return response

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        alive = sum(not worker.done() for worker in runner.workers)
        ready = not runner.stopping and alive == runner.concurrency
        return {"status": "ok" if ready else "degraded", "version": __version__, "mode": "local", "modules": len(modules.describe()),
                "ready": ready,
                "tasks": {"queued": runner.queue.qsize(), "active": len(runner.active),
                          "queue_capacity": runner.queue.maxsize, "workers": runner.concurrency, "alive_workers": alive}}

    @app.get("/api/modules")
    async def module_list() -> dict[str, Any]:
        return {"items": modules.describe()}

    register_host_downloads(app, modules)

    @app.get("/api/catalog")
    async def analysis_catalog() -> dict[str, Any]:
        available = {item["id"] for item in modules.describe()}
        described = catalog()
        described["profiles"] = [profile for profile in described["profiles"] if profile["module"] in available]
        return described

    @app.get("/api/assets")
    async def asset_list(kind: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return await asyncio.to_thread(inventory.list, kind=kind, limit=limit, offset=offset)

    @app.post("/api/assets", status_code=201)
    async def create_asset(payload: AssetCreate, request: Request) -> dict[str, Any]:
        key = idempotency_key(request)
        def save() -> dict[str, Any]:
            name, normalized = inspections.prepare_asset(payload.kind, payload.name, payload.source)
            targets = normalized.get("targets", [])
            provenance = (lab.provenance_for(targets[0]) if payload.kind == "website"
                          and normalized.get("profile_id") == "website-probe"
                          and len(targets) == 1 else None)
            return inventory.create(payload.kind, name, normalized, idempotency_key=key, provenance=provenance)
        return await asyncio.to_thread(save)

    @app.get("/api/assets/{asset_id}")
    async def asset(asset_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(inventory.get, _identifier(asset_id))

    @app.get("/api/assets/{asset_id}/jobs")
    async def asset_jobs(asset_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        await asyncio.to_thread(inventory.get, _identifier(asset_id))
        return await asyncio.to_thread(repository.list, limit=limit, offset=offset, asset_id=asset_id)

    @app.post("/api/assets/{asset_id}/preflight")
    async def preflight(asset_id: str, payload: InspectionCreate) -> dict[str, Any]:
        return await asyncio.to_thread(inspections.preflight, _identifier(asset_id), payload.checks,
                                       payload.options.model_dump(exclude_none=True))

    @app.post("/api/assets/{asset_id}/inspections", status_code=201)
    async def inspect_asset(asset_id: str, payload: InspectionCreate, request: Request) -> dict[str, Any]:
        asset_id, key = _identifier(asset_id), idempotency_key(request)
        options = payload.options.model_dump(exclude_none=True)
        asset, profile, configuration = await asyncio.to_thread(inspections.prepare_inspection, asset_id, payload.checks, options)
        name = payload.name.strip() or f"{asset['name']} · {profile['label']}"
        replayed = await asyncio.to_thread(runner.replay, profile["module"], name, configuration,
                                           asset_id=asset_id, idempotency_key=key)
        if replayed is not None:
            return replayed
        readiness = await asyncio.to_thread(inspections.preflight, asset_id, payload.checks, options)
        if not readiness["ready"]:
            raise WorkbenchError("PREFLIGHT_BLOCKED", "输入或本机环境尚未就绪，请先查看预检中的阻断项。")
        return await runner.submit_async(profile["module"], name, configuration, asset_id=asset_id, idempotency_key=key)

    @app.get("/api/jobs")
    async def jobs(module: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if module:
            modules.get(module)
        return await asyncio.to_thread(repository.list, module, limit=limit, offset=offset)

    @app.post("/api/jobs", status_code=201)
    async def submit(payload: JobCreate, request: Request) -> dict[str, Any]:
        if len(json.dumps(payload.config)) > 65536:
            raise WorkbenchError("CONFIG_TOO_LARGE", "任务配置过大")
        return await runner.submit_async(payload.module, payload.name, payload.config,
                                         asset_id=_identifier(payload.asset_id) if payload.asset_id else None,
                                         idempotency_key=idempotency_key(request))

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(repository.get, _identifier(job_id))

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, after: int = 0, limit: int = 500) -> dict[str, Any]:
        return await asyncio.to_thread(repository.events, _identifier(job_id), after=after, limit=limit)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        return await runner.cancel_async(_identifier(job_id))

    @app.post("/api/jobs/{job_id}/retry", status_code=201)
    async def retry(job_id: str, request: Request) -> dict[str, Any]:
        return await runner.retry_async(_identifier(job_id), idempotency_key=idempotency_key(request))

    @app.post("/api/uploads", status_code=201)
    def upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        # FastAPI runs synchronous endpoints in its worker pool. Copying the
        # already-parsed spooled file and committing upload metadata must stay
        # in that same worker: SQLite contention and disk IO must not block the
        # event loop, and request cancellation must not unlink an input while
        # a detached metadata commit is still in progress.
        original = (file.filename or "upload").replace("\\", "/").split("/")[-1][:200]
        suffix = Path(original).suffix.lower()
        if suffix not in {".apk", ".json", ".csv", ".jsonl", ".ndjson", ".log", ".txt"}:
            raise WorkbenchError("UPLOAD_TYPE", "支持 APK、JSON、CSV、JSONL 和主机 LOG/TXT 文件")
        maximum = 2 * 1024 * 1024 if suffix in {".log", ".txt"} else MAX_UPLOAD
        upload_id, size, digest = uuid4().hex, 0, hashlib.sha256()
        path = directory / "uploads" / upload_id
        try:
            with path.open("xb") as handle:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise WorkbenchError("UPLOAD_LIMIT", "主机日志不得超过 2 MiB" if maximum != MAX_UPLOAD else "上传文件超过 256 MiB")
                    handle.write(chunk)
                    digest.update(chunk)
            if size == 0:
                raise WorkbenchError("UPLOAD_EMPTY", "不能上传空文件")
            return repository.add_upload(upload_id, original, size, digest.hexdigest())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    def completed(job_id: str) -> dict[str, Any]:
        item = repository.get(_identifier(job_id))
        if item["status"] != "completed" or not isinstance(item.get("result"), dict):
            raise WorkbenchError("RESULT_UNAVAILABLE", "任务尚未完成，没有完整结果")
        return item

    @app.get("/api/jobs/{job_id}/evidence/{evidence_id}")
    async def evidence(job_id: str, evidence_id: str) -> dict[str, Any]:
        result = (await asyncio.to_thread(completed, job_id))["result"]
        selected = next((item for item in result["evidence"] if item["id"] == evidence_id), None)
        if selected is None:
            raise WorkbenchError("EVIDENCE_NOT_FOUND", "该任务没有这条证据")
        return cast("dict[str, Any]", selected)

    def android_query(job_id: str, topic: str, **kwargs: Any) -> dict[str, Any]:
        from ..modules.android import query_artifact

        item = completed(job_id)
        if item["module"] != "android":
            raise WorkbenchError("MODULE_MISMATCH", "这个任务不提供 Android 方法查询")
        artifact_id = item["result"].get("details", {}).get("artifact_id")
        if not isinstance(artifact_id, str):
            raise WorkbenchError("QUERY_UNAVAILABLE", "此任务只检查应用清单，未建立方法源码索引")
        return query_artifact(directory / "jobs" / job_id,
                              artifact_id, topic, **kwargs)

    @app.get("/api/jobs/{job_id}/methods")
    async def methods(job_id: str, search: str = "", offset: int = 0, limit: int = 50) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            return android_query(job_id, "methods", query=search, offset=offset, limit=limit)
        return await asyncio.to_thread(read)

    @app.get("/api/jobs/{job_id}/method")
    async def method(job_id: str, ref: str = Query(min_length=1, max_length=2000),
                     offset: int = 0, limit: int = 80) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            return android_query(job_id, "method", ref=ref, offset=offset, limit=limit)
        return await asyncio.to_thread(read)

    @app.post("/api/jobs/{job_id}/check")
    async def check(job_id: str, claim: dict[str, Any]) -> dict[str, Any]:
        def verify() -> dict[str, Any]:
            return android_query(job_id, "check", claim=claim)
        return await asyncio.to_thread(verify)

    @app.get("/api/jobs/{job_id}/compare")
    async def compare(job_id: str, baseline: str = Query(min_length=32, max_length=32)) -> dict[str, Any]:
        from ..modules.web.comparison import compare_jobs

        current, previous = await asyncio.to_thread(completed, job_id), await asyncio.to_thread(completed, baseline)
        return await asyncio.to_thread(compare_jobs, previous, current)

    @app.get("/api/jobs/{job_id}/export")
    async def export(job_id: str, format: Literal["json", "html", "csv"] = "json") -> Response:
        item = await asyncio.to_thread(completed, job_id)
        if format == "json":
            content = json.dumps(item, ensure_ascii=False, indent=2)
            return Response(content, media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="reachscope-{job_id}.json"'})
        if format == "csv":
            from ..modules.web.export import inventory_csv

            content_csv = await asyncio.to_thread(inventory_csv, item)
            return Response(content_csv, media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="reachscope-web-{job_id}.csv"'})
        env = Environment(autoescape=True)
        template = env.from_string(EXPORT_TEMPLATE)
        return HTMLResponse(template.render(job=item), headers={
            "Content-Disposition": f'attachment; filename="reachscope-{job_id}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        })

    # Query/Artifact exceptions expose only domain errors, never a raw traceback.
    from reachscope.artifacts import ArtifactError
    from reachscope.query import QueryError

    async def evidence_error(request: Request, exc: ArtifactError | QueryError) -> JSONResponse:
        return failure(request, exc.code, str(exc), 400)
    app.add_exception_handler(ArtifactError, evidence_error)  # type: ignore[arg-type]  # — Starlette 签名宽于具体异常，运行期按精确类型分发
    app.add_exception_handler(QueryError, evidence_error)  # type: ignore[arg-type]  # — Starlette 签名宽于具体异常，运行期按精确类型分发

    static = Path(__file__).resolve().parents[1] / "static"
    assets = static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    async def frontend() -> Response:
        page = static / "index.html"
        if not page.is_file():
            return HTMLResponse("Frontend not built. Run npm ci and npm run build in frontend/.", status_code=503)
        return FileResponse(page)

    return app


EXPORT_TEMPLATE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>ReachScope · {{ job.name }}</title><style>body{font:15px/1.7 system-ui;background:#f1eee5;color:#242824;max-width:1100px;margin:50px auto;padding:20px}h1{font-weight:500}article{border-top:1px solid #ccc;padding:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#e7e5da;padding:15px}small{color:#696f64}</style>
<h1>{{ job.name }}</h1><small>{{ job.module }} / {{ job.created_at }} / {{ job.id }}</small>
<p>{{ job.result.target }}</p><pre>{{ job.result.summary|tojson(indent=2) }}</pre>
<h2>观察与检查项</h2>{% for item in job.result.observations %}<article><h3>{{ item.title }}</h3><p>{{ item.description }}</p><small>{{ item.severity }} / {{ item.confidence }}</small><p>{{ item.recommendation }}</p></article>{% endfor %}
<h2>证据</h2>{% for item in job.result.evidence %}<article><h3>{{ item.title }}</h3><small>{{ item.kind }} / {{ item.source }} / {{ item.id }}</small><pre>{{ item.data|tojson(indent=2) }}</pre></article>{% endfor %}
<h2>范围与限制</h2><ul>{% for limitation in job.result.limitations %}<li>{{ limitation }}</li>{% endfor %}</ul>
<p>本报告保存观察、推断及其证据，不是对整体安全性的证明。</p></html>"""
