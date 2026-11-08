"""Exercise the real local workbench, without replacing its API or module results.

Requires the optional Python Playwright dependency. Start the workbench first.
All active Web requests target a temporary HTTP server on this machine.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect, sync_playwright

_pending_name = ""


class LocalTarget(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/slow":
            time.sleep(5)
        body = (
            b"<!doctype html><title>Workbench local target</title>"
            b'<main><script>window.targetExecuted=true</script>local inspection fixture</main>'
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Server", "nginx/fixture")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_: object) -> None:
        pass


def wait_complete(page: Page) -> None:
    expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=60_000)


def new_task(page: Page, name: str, module: str = "android", mode: str = "demo") -> None:
    global _pending_name
    _pending_name = name
    page.get_by_role("button", name="新建检查", exact=True).first.click()
    page.locator(".asset-kind-picker button").nth(1 if module == "web" else 0).click()
    page.get_by_role("button", name="下一步", exact=True).click()
    profile = "android-demo" if module == "android" else f"website-{mode}"
    page.get_by_label("选择检查方式").select_option(profile)


def start(page: Page) -> str:
    previous = page.url
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_label("本次任务名称").fill(_pending_name)
    page.get_by_role("button", name="开始检查", exact=True).click()
    page.wait_for_url(lambda url: url != previous, timeout=15_000)
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator(".detail-heading")).to_be_visible(timeout=15_000)
    return page.url.split("/jobs/")[-1]


def no_overflow(page: Page) -> bool:
    return page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", "--base-url", dest="url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/legacy-ui"))
    args = parser.parse_args()
    run_tag = time.strftime("%H%M%S")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalTarget)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    target = f"http://127.0.0.1:{server.server_port}"
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    job_ids: dict[str, str] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(args.browser) if args.browser else None, headless=True
            )
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url)
            expect(page.locator(".overview-heading h1")).to_be_visible()
            assert no_overflow(page)
            checks.append({"name": "live service and dashboard", "passed": True})

            new_task(page, f"UI验收 {run_tag} / Android 跨组件")
            job_ids["android"] = start(page)
            wait_complete(page)
            page.locator(".path-steps button").nth(1).click()
            expect(page.locator(".code-view .code-path")).to_contain_text("CrossTarget.smali")
            expect(page.locator(".code-view pre")).to_contain_text("getStringExtra")
            expect(page.locator(".code-view pre")).to_contain_text("loadUrl")
            assert no_overflow(page)
            page.screenshot(path=str(output / "android-result.png"), full_page=True)
            checks.append({"name": "Android submit, persisted chain and actual target method", "passed": True})

            page.get_by_role("tab", name="证据索引").click()
            page.locator(".evidence-list button").first.click()
            expect(page.locator(".evidence-inspector .data-block")).to_be_visible()
            page.get_by_role("tab", name="执行记录").click()
            assert page.locator(".event-list li").count() > 2
            page.get_by_role("tab", name="输入与配置").click()
            expect(page.locator(".data-block")).to_contain_text("cross_component")
            checks.append({"name": "evidence, event journal and reproducible input", "passed": True})

            with page.expect_download() as download:
                page.get_by_role("link", name="导出 JSON", exact=True).click()
            download.value.save_as(output / "android-export.json")
            exported = json.loads((output / "android-export.json").read_text(encoding="utf-8"))
            assert "android" in json.dumps(exported)
            checks.append({"name": "real JSON export", "passed": True})

            new_task(page, f"UI验收 {run_tag} / 本地 HTTP 探测", "web", "probe")
            page.get_by_label("网站地址", exact=True).fill(target + "/")
            page.locator(".checkbox-field input").check()
            job_ids["probe"] = start(page)
            wait_complete(page)
            assert page.locator(".asset-table tbody tr").count() == 1
            expect(page.locator(".asset-table")).to_contain_text("200")
            expect(page.locator(".asset-table")).to_contain_text("Workbench local target")
            assert page.evaluate("window.targetExecuted") is None
            page.locator(".asset-name").first.click()
            expect(page.get_by_role("dialog", name="资产响应详情")).to_contain_text("headers")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog", name="资产响应详情")).to_have_count(0)
            checks.append({"name": "actual loopback HTTP probe, headers and safe target text", "passed": True})

            new_task(page, f"UI验收 {run_tag} / 导入资产", "web", "import")
            imported = [{"url": "https://imported.example.com", "title": "<script>window.importExecuted=true</script>", "server": "nginx", "status_code": 200}]
            page.locator('input[type="file"]').set_input_files({"name": "assets.json", "mimeType": "application/json", "buffer": json.dumps(imported).encode()})
            job_ids["import"] = start(page)
            wait_complete(page)
            expect(page.locator(".asset-table")).to_contain_text("imported.example.com")
            assert page.evaluate("window.importExecuted") is None
            checks.append({"name": "real upload/import and untrusted title escaping", "passed": True})

            new_task(page, f"UI验收 {run_tag} / Web 规则分析", "web")
            job_ids["web_demo"] = start(page)
            wait_complete(page)
            assert page.locator(".asset-table tbody tr").count() == 20
            assert page.locator(".candidate-paths > details").count() > 0
            page.locator(".candidate-paths > details > summary").first.click()
            expect(page.locator(".investigation-step").first).to_be_visible()
            page.get_by_label("搜索 Web 资产").fill("nginx")
            assert 0 < page.locator(".asset-table tbody tr").count() < 20
            page.get_by_label("搜索 Web 资产").fill("")
            checks.append({"name": "reused asset rules, inspectable candidate steps and asset search", "passed": True})

            # Hold a real response from the old route, switch jobs, then release it.
            old_id = job_ids["android"]
            held: list[Any] = []
            pattern = f"**/api/jobs/{old_id}"
            page.route(pattern, lambda route: held.append(route))
            page.goto(args.url + "/#/jobs/" + old_id)
            page.wait_for_timeout(300)
            page.evaluate("(id) => { location.hash = '/jobs/' + id; }", job_ids["probe"])
            expect(page.locator(".detail-heading h1")).to_contain_text("本地 HTTP 探测")
            for route in held:
                try:
                    response = route.fetch()
                    route.fulfill(response=response)
                except Exception:  # noqa: BLE001 -- A navigation may already have disposed the held request.
                    route.abort()
            page.unroute(pattern)
            page.wait_for_timeout(700)
            expect(page.locator(".detail-heading h1")).to_contain_text("本地 HTTP 探测")
            checks.append({"name": "late old-job response cannot replace current job", "passed": True})

            new_task(page, f"UI验收 {run_tag} / 取消慢请求", "web", "probe")
            page.get_by_label("网站地址", exact=True).fill(target + "/slow")
            page.locator(".checkbox-field input").check()
            job_ids["cancel"] = start(page)
            page.get_by_role("button", name="取消任务", exact=True).click()
            expect(page.locator(".detail-heading .status-tag")).to_have_text("已取消", timeout=15_000)
            checks.append({"name": "actual task cancellation", "passed": True})

            page.get_by_role("button", name="分析总览").click()
            page.get_by_label("搜索分析任务").fill(f"UI验收 {run_tag} / 本地 HTTP")
            assert page.locator(".jobs-table tbody tr").count() >= 1
            assert all("本地 HTTP" in value for value in page.locator(".jobs-table tbody tr").all_text_contents())
            page.get_by_label("搜索分析任务").fill("")
            page.screenshot(path=str(output / "dashboard.png"))
            assert no_overflow(page)
            checks.append({"name": "persistent job history and task search", "passed": True})

            page.set_viewport_size({"width": 390, "height": 844})
            assert no_overflow(page)
            page.get_by_role("button", name="展开导航").click()
            page.locator(".sidebar nav").get_by_role("button", name="Web", exact=False).click()
            expect(page.locator(".overview-heading h1")).to_contain_text("摸清资产")
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            page.get_by_role("button", name="新建检查", exact=True).first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            assert no_overflow(page)
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            checks.append({"name": "390px mobile navigation, layout and modal keyboard behavior", "passed": True})

            page.goto(args.url + "/#/jobs/" + job_ids["android"])
            wait_complete(page)
            assert no_overflow(page)
            checks.append({"name": "refresh preserves job route and result", "passed": True})
            assert not errors, errors
            checks.append({"name": "no browser execution errors", "passed": True})
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    record = {"passed": len(checks), "total": len(checks), "checks": checks, "jobs": job_ids, "console_errors": errors}
    (output / "ui-validation.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
