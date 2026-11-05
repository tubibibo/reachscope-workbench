"""An opt-in, bounded loopback teaching site; never an arbitrary target server."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ..core.models import WorkbenchError
from ..core.scenarios.loader import LoadedScenario, ScenarioCatalog

LabProfile = Literal["baseline", "hardened"]
_HARDENED_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_LIMITATIONS = [
    "本地教学场景只监听 127.0.0.1 的随机端口，响应是项目内置的固定内容，不代表生产网站。",
    "启动或切换版本不会执行检查、调用 AI、创建发现或关闭事项；请保存资产并明确选择检查。",
    "补强版只演示四类 HTTP 响应头，不代表完成应用安全审计；此 HTTP 场景不演示 TLS/HSTS。",
    "停止或重启服务会结束本场景；历史证据仍保留，旧地址不会自动重新启动或转向其他目标。",
    "切换版本会影响后续请求；已保存证据不改变，执行中的请求以实际捕获的响应为准。",
]
# 场景模式 body 缺省 Content-Type（profile 未声明时按 body 后缀补默认值）。
_SCENARIO_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".css": "text/css; charset=utf-8",
}
# 这三个状态码按 HTTP 语义不得携带 body；头部仍全部发送，仅 Content-Length 归零。
_BODYLESS_STATUS = frozenset({204, 205, 304})


class _LabHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8

    def __init__(self, lab: LocalLab) -> None:
        self.lab = lab
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", 0), _LabHandler)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, address = super().get_request()
        request.settimeout(2)
        return request, address

    def process_request(self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class _LabHandler(BaseHTTPRequestHandler):
    server: _LabHTTPServer

    def version_string(self) -> str:
        return "ReachScope-Local-Lab/1"

    def log_message(self, format: str, *args: Any) -> None:
        # Fixed local content needs no access log, target/header echo or secrets.
        pass

    def _empty(self, status: int) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host", []) != [expected_host]:
            self._empty(421)
            return
        snapshot = self.server.lab.status()
        if snapshot["scenario"] is not None:
            self._serve_scenario(snapshot, expected_host)
        else:
            self._serve_legacy(snapshot, expected_host)

    def _serve_legacy(self, snapshot: dict[str, Any], expected_host: str) -> None:
        if self.path != "/":
            self._empty(404)
            return
        if snapshot["status"] != "running" or snapshot["url"] != f"http://{expected_host}/":
            self._empty(503)
            return
        profile = str(snapshot["profile"])
        title = "ReachScope local teaching site / " + profile
        body = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>" + title + "</title>"
                "<h1>Local response-header teaching site</h1><p>Profile: " + profile + "</p>"
                "<p>This fixed page is served by ReachScope on loopback. It is not a production target.</p>"
                "<p>Inspect the saved evidence, change the profile explicitly, and compare the same URL.</p></html>").encode("utf-8")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-ReachScope-Lab-Session", str(snapshot["session_id"]))
        self.send_header("X-ReachScope-Lab-Generation", str(snapshot["generation"]))
        self.send_header("X-ReachScope-Lab-Profile", profile)
        if profile == "hardened":
            for name, value in _HARDENED_HEADERS.items():
                self.send_header(name, value)
        else:
            # Explicitly permissive so the example teaches a real policy
            # difference. The fixed page has no links/resources or private data.
            self.send_header("Referrer-Policy", "unsafe-url")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def _serve_scenario(self, snapshot: dict[str, Any], expected_host: str) -> None:
        if snapshot["status"] != "running" or snapshot["url"] != f"http://{expected_host}/":
            self._empty(503)
            return
        plan = self.server.lab.scenario_serving(self.path)
        if plan is None:
            self._empty(404)
            return
        root, body_relative, status, headers, cookies = plan
        # B1 already validated the body stays inside the pack; re-verify at serve
        # time and treat any escape or unreadable file as 503 instead of crashing.
        body_file = (root / body_relative).resolve()
        if not body_file.is_relative_to(root):
            self._empty(503)
            return
        try:
            body = body_file.read_bytes()
        except OSError:
            self._empty(503)
            return
        bodyless = status in _BODYLESS_STATUS
        self.close_connection = True
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        declared = {name.lower() for name, _ in headers}
        if "content-type" not in declared:
            self.send_header("Content-Type", _SCENARIO_CONTENT_TYPES.get(body_file.suffix, "text/html; charset=utf-8"))
        self.send_header("Content-Length", "0" if bodyless else str(len(body)))
        if "cache-control" not in declared:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-ReachScope-Lab-Session", str(snapshot["session_id"]))
        self.send_header("X-ReachScope-Lab-Generation", str(snapshot["generation"]))
        self.send_header("X-ReachScope-Lab-Profile", str(snapshot["profile"]))
        self.end_headers()
        if not bodyless:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                pass

    def do_HEAD(self) -> None:
        self._empty(405)

    def do_POST(self) -> None:
        self._empty(405)

    def do_PUT(self) -> None:
        self._empty(405)

    def do_DELETE(self) -> None:
        self._empty(405)


class LocalLab:
    """One ephemeral site per app instance; all lifecycle mutations are serialized."""

    def __init__(self, catalog: ScenarioCatalog | None = None) -> None:
        self._lock = threading.RLock()
        self._catalog = catalog
        self._scenario: LoadedScenario | None = None
        self._server: _LabHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._generation = uuid4().hex
        self._session_id: str | None = None
        self._profile: LabProfile = "baseline"

    def status(self) -> dict[str, Any]:
        with self._lock:
            url = f"http://127.0.0.1:{self._server.server_port}/" if self._server else None
            scenario = None
            if self._scenario is not None:
                pack = self._scenario.pack
                scenario = {"id": pack.id, "title": dict(pack.title), "difficulty": pack.difficulty}
            return {
                "status": "running" if self._server else "stopped", "generation": self._generation,
                "session_id": self._session_id, "profile": self._profile, "scenario": scenario, "url": url,
                "source": {"kind": "local_training", "label": "本地教学站点 / 实际 loopback 采集", "production": False},
                "asset_template": {
                    "kind": "website", "name": "本地教学站点 / HTTP 响应头补强",
                    "source": {"profile_id": "website-probe", "mode": "probe", "targets": [url], "allow_private": True},
                } if url else None,
                "limits": {"bind_host": "127.0.0.1", "paths": ["/"], "methods": ["GET"],
                           "max_connections": 8, "connection_timeout_seconds": 2},
                "automatic_scan": False, "automatic_ai": False, "limitations": list(_LIMITATIONS),
            }

    def scenario_serving(self, path: str) -> tuple[Path, str, int, list[tuple[str, str]], list[str]] | None:
        """场景模式的应答要素：(包根, body 相对路径, 状态码, 按声明顺序的响应头, Cookie 列表)。

        请求路径与路由键必须完全相等（不解码、不规范化、不剥离 query）；无此路由返回 None。
        """
        with self._lock:
            loaded = self._scenario
            if loaded is None:
                return None
            profile = loaded.pack.profiles[self._profile]
            route = profile.routes.get(path)
            if route is None:
                return None
            headers = [(name, value) for name, value in profile.headers.items()]
            return loaded.root, route.body, route.status, headers, list(profile.cookies)

    def scenarios(self) -> dict[str, Any]:
        """场景目录：已加载的包（catalog 已按 id 升序）与坏包 issue（(source, code, message) 稳定序）。"""
        catalog = self._catalog
        if catalog is None:
            return {"packs": [], "issues": []}
        return {
            "packs": [{"id": loaded.pack.id, "title": dict(loaded.pack.title),
                       "summary": dict(loaded.pack.summary), "difficulty": loaded.pack.difficulty}
                      for loaded in catalog.packs.values()],
            "issues": [{"source": issue.source, "code": issue.code, "message": issue.message}
                       for issue in catalog.issues],
        }

    def start(self, scenario_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if scenario_id is None:
                # 旧行为：运行中即幂等返回（即使当前是场景模式，也不做破坏性切换）。
                if self._server is not None:
                    return self.status()
                return self._start_server(None)
            loaded = self._catalog.packs.get(scenario_id) if self._catalog is not None else None
            if loaded is None:
                # 先解析再动运行中的站点：未知 id 不许停掉现有服务。
                raise WorkbenchError("LAB_SCENARIO_NOT_FOUND", "找不到这个本地教学场景。")
            if self._server is not None:
                if self._scenario is not None and self._scenario.pack.id == scenario_id:
                    return self.status()
                self._stop_locked()
            return self._start_server(loaded)

    def _start_server(self, loaded: LoadedScenario | None) -> dict[str, Any]:
        server: _LabHTTPServer | None = None
        try:
            server = _LabHTTPServer(self)
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05},
                                      name="reachscope-local-lab", daemon=True)
            worker.start()
        except (OSError, RuntimeError) as exc:
            if server is not None:
                server.server_close()
            raise WorkbenchError("LAB_UNAVAILABLE", "本机教学站点未能启动，请检查回环网络与本机服务限制。") from exc
        self._server, self._thread = server, worker
        self._session_id, self._generation = uuid4().hex, uuid4().hex
        self._profile = "baseline"
        self._scenario = loaded
        return self.status()

    def configure(self, generation: str, profile: LabProfile) -> dict[str, Any]:
        with self._lock:
            if self._server is None:
                raise WorkbenchError("LAB_NOT_RUNNING", "请先启动本地教学站点。")
            if generation != self._generation:
                raise WorkbenchError("LAB_CONFLICT", "教学站点已变更，请刷新当前版本后再操作。")
            if profile not in {"baseline", "hardened"}:
                raise WorkbenchError("INVALID_LAB", "只支持初始版或响应头补强版。")
            if profile != self._profile:
                self._profile, self._generation = profile, uuid4().hex
            return self.status()

    def provenance_for(self, url: str) -> dict[str, Any] | None:
        """Recognize this owned live URL, never an arbitrary loopback hostname."""
        snapshot = self.status()
        if snapshot["status"] != "running" or snapshot["url"] != url:
            return None
        provenance: dict[str, Any] = {"kind": "local_training", "label": snapshot["source"]["label"],
                                      "session_id": snapshot["session_id"]}
        if snapshot["scenario"] is not None:
            # 加性键：只有场景模式才有；legacy 记录保持 0.14 的三键形状。
            provenance["scenario_id"] = snapshot["scenario"]["id"]
        return provenance

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._server is None:
                return self.status()
            self._stop_locked()
            return self.status()

    def _stop_locked(self) -> None:
        server = self._server
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server, self._thread, self._session_id = None, None, None
        self._generation, self._profile = uuid4().hex, "baseline"
        self._scenario = None
