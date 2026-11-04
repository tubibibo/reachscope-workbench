"""An opt-in, bounded loopback teaching site; never an arbitrary target server."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from uuid import uuid4

from ..core.models import WorkbenchError

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
        if self.path != "/":
            self._empty(404)
            return
        snapshot = self.server.lab.status()
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

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._server: _LabHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._generation = uuid4().hex
        self._session_id: str | None = None
        self._profile: LabProfile = "baseline"

    def status(self) -> dict[str, Any]:
        with self._lock:
            url = f"http://127.0.0.1:{self._server.server_port}/" if self._server else None
            return {
                "status": "running" if self._server else "stopped", "generation": self._generation,
                "session_id": self._session_id, "profile": self._profile, "url": url,
                "source": {"kind": "local_training", "label": "本地教学站点 / 实际 loopback 采集", "production": False},
                "asset_template": {
                    "kind": "website", "name": "本地教学站点 / HTTP 响应头补强",
                    "source": {"profile_id": "website-probe", "mode": "probe", "targets": [url], "allow_private": True},
                } if url else None,
                "limits": {"bind_host": "127.0.0.1", "paths": ["/"], "methods": ["GET"],
                           "max_connections": 8, "connection_timeout_seconds": 2},
                "automatic_scan": False, "automatic_ai": False, "limitations": list(_LIMITATIONS),
            }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                return self.status()
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
        return {"kind": "local_training", "label": snapshot["source"]["label"],
                "session_id": snapshot["session_id"]}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._server is None:
                return self.status()
            self._server.shutdown()
            self._server.server_close()
            if self._thread is not None:
                self._thread.join(timeout=2)
            self._server, self._thread, self._session_id = None, None, None
            self._generation, self._profile = uuid4().hex, "baseline"
            return self.status()
