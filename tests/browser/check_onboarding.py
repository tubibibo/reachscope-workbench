"""Verify onboarding, module routes and provider forms in an isolated workspace.

No real target or model is contacted. The diagnostic target is a local HTTP fixture
and the only credential used is an explicit synthetic test value.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, object]] = []
    checks: list[str] = []
    errors: list[str] = []
    writes: list[str] = []
    api_requests: list[dict[str, object]] = []

    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append({"path": self.path, "authorization_present": bool(self.headers.get("Authorization"))})
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_: object) -> None:
            pass

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    repository = Path(__file__).resolve().parents[2]
    # Do not inherit any real provider config or credential in a browser fixture.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("REACHSCOPE_AI_")}
    try:
        with tempfile.TemporaryDirectory(prefix="reachscope-onboarding-") as workspace:
            process = subprocess.Popen(
                [sys.executable, "-m", "reachscope_workbench.cli", "serve", "--port", str(port), "--data", workspace],
                cwd=repository, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                with httpx.Client(base_url=base, trust_env=False, timeout=3) as client:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            if client.get("/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if time.monotonic() > deadline or process.poll() is not None:
                            raise RuntimeError("Isolated workbench did not become ready")
                        time.sleep(.1)
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, executable_path=str(args.browser) if args.browser else None)
                        context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
                        page = context.new_page()
                        page.set_default_timeout(8000)
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

                        def observe(request: object) -> None:
                            method = request.method  # type: ignore[attr-defined]
                            url = request.url  # type: ignore[attr-defined]
                            if url.startswith(base + "/api/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
                                writes.append(url)
                            if url.endswith("/api/ai/diagnose"):
                                api_requests.append(request.post_data_json)  # type: ignore[attr-defined]
                        page.on("request", observe)
                        page.goto(base, wait_until="networkidle")
                        expect(page.get_by_role("button", name="查看上手指南")).to_be_visible()
                        page.get_by_role("button", name="查看上手指南").click()
                        expect(page).to_have_url(base + "/#/guide")
                        expect(page.get_by_role("heading", name="这次检查什么？")).to_be_visible()
                        page.screenshot(path=str(args.out / "guide-desktop.png"), full_page=True)
                        checks.append("asset empty state exposes an actionable getting-started guide")
                        for title, asset in [("网站", "网站"), ("Android 应用", "APK"), ("云资产", "云")]:
                            page.get_by_role("group", name="选择入门资产类型").get_by_role("button", name=title, exact=True).click()
                            page.get_by_role("button", name="开始" + title + "检查", exact=True).click()
                            expect(page.get_by_role("dialog")).to_be_visible()
                            expect(page.locator('.asset-kind-picker [aria-pressed="true"]')).to_contain_text(asset)
                            page.get_by_role("button", name="关闭新建任务").click()
                        assert not writes, writes
                        checks.append("all three input paths preselect the matching wizard without submitting jobs")
                        for label, module in [("Android", "android"), ("Web", "web"), ("云资产", "cloud")]:
                            page.get_by_role("navigation", name="工作台导航").get_by_role("button", name=label, exact=False).click()
                            expect(page).to_have_url(base + "/#/modules/" + module)
                            expect(page.locator(".sidebar nav > button.active")).to_contain_text(label)
                            page.reload(wait_until="networkidle")
                            expect(page.locator(".sidebar nav > button.active")).to_contain_text(label)
                        checks.append("module navigation and reload retain module-specific routes")
                        page.go_back(wait_until="networkidle")
                        expect(page.locator(".sidebar nav > button.active")).to_contain_text("Web")
                        checks.append("browser history restores the previous module")
                        page.locator(".skip-link").focus()
                        page.keyboard.press("Enter")
                        assert page.evaluate("document.activeElement.id") == "main-content"
                        assert page.url.endswith("#/modules/web")
                        checks.append("keyboard skip link focuses main content without changing application route")
                        page.goto(base + "/#/jobs/%E0%A4%A", wait_until="networkidle")
                        expect(page.locator("main")).to_contain_text("分析记录")
                        checks.append("malformed encoded deep link does not crash the application")
                        page.get_by_role("navigation").get_by_role("button", name="AI 接口", exact=True).click()
                        provider = page.get_by_label("AI 提供商预设", exact=True)
                        expect(provider).to_be_visible()
                        expect(provider.locator("option")).to_have_count(3)
                        provider.select_option("deepseek")
                        expect(page.get_by_label("AI 模型标识", exact=True)).to_have_value("deepseek-flash")
                        assert set(page.get_by_label("推理强度", exact=True).locator("option").evaluate_all("els => els.map(e => e.value)")) == {"default", "none", "low", "high", "max"}
                        assert "Ultra" not in page.get_by_label("推理强度", exact=True).inner_text()
                        expect(page.get_by_label("推理强度", exact=True)).to_have_value("default")
                        assert not writes, writes
                        checks.append("provider capabilities and current DeepSeek models come from the API without a model call")
                        page.get_by_label("AI API 密钥", exact=True).fill("SYNTHETIC_PROVIDER_KEY_NOT_REAL")
                        page.get_by_role("button", name="保存接口设置", exact=True).click()
                        expect(page.locator(".workspace-success")).to_be_visible()
                        expect(page.get_by_label("AI API 密钥", exact=True)).to_have_value("")
                        assert client.get("/api/ai/config").json()["has_key"]
                        provider.select_option("custom")
                        expect(page.get_by_text("服务商或地址已变化。", exact=False)).to_be_visible()
                        page.get_by_label("AI 兼容接口地址", exact=True).fill("https://example.invalid/v1")
                        page.get_by_label("AI 模型标识", exact=True).fill("fixture-model")
                        page.get_by_role("button", name="保存接口设置", exact=True).click()
                        expect(page.locator(".workspace-success")).to_be_visible()
                        assert not client.get("/api/ai/config").json()["has_key"]
                        assert len(writes) == 2, writes
                        checks.append("saving never invokes a model; changing endpoint clears the previous session credential")
                        fixture_base = f"http://127.0.0.1:{fixture.server_port}/v1"
                        page.get_by_label("AI 兼容接口地址", exact=True).fill(fixture_base)
                        page.get_by_text("高级协议与本机接口", exact=True).click()
                        page.get_by_label("允许本机 AI 接口", exact=True).check()
                        page.get_by_role("button", name="连接诊断", exact=True).click()
                        expect(page.locator(".ai-diagnosis-result")).to_contain_text(fixture_base)
                        assert api_requests == [{"provider_id": "custom", "base_url": fixture_base, "allow_local": True}], api_requests
                        assert requests == [{"path": "/v1", "authorization_present": False}], requests
                        assert client.get("/api/ai/config").json()["base_url"] == "https://example.invalid/v1"
                        assert len(writes) == 3, writes
                        checks.append("diagnosis checks exact unsaved draft with one credential-free GET and does not mutate saved configuration")
                        assert "SYNTHETIC_PROVIDER_KEY_NOT_REAL" not in page.inner_text("body")
                        assert page.evaluate("JSON.stringify({...localStorage,...sessionStorage})") == "{}"
                        checks.append("fixture credential is absent from rendered text and browser storage")
                        page.screenshot(path=str(args.out / "providers-desktop.png"), full_page=True)
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.get_by_role("button", name="展开导航", exact=True).click()
                        page.get_by_role("navigation").get_by_role("button", name="上手指南", exact=True).click()
                        expect(page.get_by_role("heading", name="这次检查什么？")).to_be_visible()
                        assert page.evaluate("Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1")
                        page.screenshot(path=str(args.out / "guide-mobile.png"), full_page=True)
                        page.get_by_role("button", name="展开导航", exact=True).click()
                        page.get_by_role("navigation").get_by_role("button", name="AI 接口", exact=True).click()
                        expect(page.get_by_label("AI 提供商预设", exact=True)).to_be_visible()
                        assert page.evaluate("Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1")
                        page.screenshot(path=str(args.out / "providers-mobile.png"), full_page=True)
                        checks.append("390px guide and provider settings have no horizontal overflow and mobile navigation works")
                        assert not errors, errors
                        checks.append("no browser console or uncaught JavaScript errors")
                        browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
    finally:
        fixture.shutdown()
        fixture.server_close()
    report = {"scope": "isolated browser acceptance, synthetic key, local diagnostic fixture only", "checks": [{"name": item, "passed": True} for item in checks], "browser_errors": errors, "inference_requests": 0, "diagnostic_requests": requests}
    (args.out / "onboarding-ui.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(checks), "browser_errors": len(errors), "inference_requests": 0, "out": str(args.out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
