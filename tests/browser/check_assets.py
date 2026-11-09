"""Exercise the asset-first wizard and selective checks against the actual local API."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/asset-ui-validation"))
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    errors: list[str] = []
    jobs: dict[str, str] = {}
    tag = time.strftime("%H%M%S")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'<html><title>Asset flow fixture</title><form><input type="password"></form></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def next_step(page: Page) -> None:
        page.get_by_role("button", name="下一步", exact=True).click()

    def screenshot(page: Page, name: str) -> None:
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(output / name), full_page=False, animations="disabled")

    def finish(page: Page, name: str) -> dict[str, Any]:
        page.get_by_label("本次任务名称").fill(name)
        page.get_by_role("button", name="开始检查", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
        expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=60_000)
        response = page.request.get(args.base_url + "/api/jobs/" + page.url.split("/jobs/")[-1])
        assert response.ok
        result: dict[str, Any] = response.json()
        return result

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(args.browser) if args.browser else None)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.base_url + "/#/assets")
            expect(page.locator(".overview-heading h1")).to_contain_text("选好对象")
            page.get_by_role("button", name="新建检查", exact=True).first.click()
            page.locator(".asset-kind-picker button").nth(2).click()
            screenshot(page, "wizard-1.png")
            next_step(page)
            page.get_by_label("选择检查方式").select_option("cloud-demo")
            page.get_by_label("资产名称").fill(f"云配置样例 · 资产流程 {tag}")
            screenshot(page, "wizard-2.png")
            next_step(page)
            options = page.locator(".wizard-checks input")
            assert options.count() == 3
            options.nth(1).uncheck()
            options.nth(2).uncheck()
            screenshot(page, "wizard-3.png")
            next_step(page)
            expect(page.locator(".wizard-confirm")).to_contain_text("网络访问规则")
            screenshot(page, "wizard-4.png")
            network = finish(page, f"云样例 / 仅网络规则 {tag}")
            jobs["cloud_network"] = network["id"]
            assert network["config"]["checks"] == ["network"]
            assert network["asset_id"] and network["module"] == "cloud"
            execution = {item["id"]: item["status"] for item in network["result"]["details"]["execution"]}
            assert execution == {"network": "completed", "iam": "skipped", "storage": "skipped"}
            expect(page.get_by_label("本次执行范围")).to_contain_text("未选择")
            screenshot(page, "cloud-result.png")
            checks.append("four-step cloud sample selects and executes network rules only")

            page.locator(".web-check summary").first.click()
            page.get_by_role("button", name="查看原始证据").first.click()
            expect(page.get_by_role("tab", name="证据索引")).to_have_attribute("aria-selected", "true")
            expect(page.locator(".evidence-inspector .data-block")).to_be_visible()
            checks.append("cloud configuration checks lead to saved evidence")

            page.get_by_role("link", name="查看所属资产").click()
            expect(page.locator(".detail-heading h1")).to_contain_text("云配置样例")
            expect(page.locator(".asset-history>button")).to_have_count(1)
            page.get_by_role("button", name="再次检查", exact=True).click()
            expect(page.locator(".saved-asset-card")).to_be_visible()
            next_step(page)
            options = page.locator(".wizard-checks input")
            options.nth(0).uncheck()
            options.nth(2).uncheck()
            next_step(page)
            iam = finish(page, f"云样例 / 同资产权限检查 {tag}")
            jobs["cloud_iam_reuse"] = iam["id"]
            assert iam["asset_id"] == network["asset_id"] and iam["config"]["checks"] == ["iam"]
            page.get_by_role("link", name="查看所属资产").click()
            expect(page.locator(".asset-history>button")).to_have_count(2)
            screenshot(page, "asset-history.png")
            checks.append("saved cloud asset is reused with different checks and retains both jobs")

            page.get_by_role("button", name="新建检查", exact=True).first.click()
            page.locator(".asset-kind-picker button").nth(1).click()
            next_step(page)
            page.get_by_label("选择检查方式").select_option("website-probe")
            page.get_by_label("网站地址", exact=True).fill(f"http://127.0.0.1:{server.server_port}/")
            page.locator(".checkbox-field input").check()
            next_step(page)
            options = page.locator(".wizard-checks input")
            assert options.nth(0).is_disabled()
            for index in (1, 2, 3):
                options.nth(index).uncheck()
            next_step(page)
            http = finish(page, f"网站 / 仅响应采集 {tag}")
            jobs["website_http"] = http["id"]
            assert http["config"]["checks"] == ["http"]
            record = http["result"]["details"]["assets"][0]
            assert record["status_code"] == 200
            assert not set(record) & {"cookies", "tls", "page", "checks"}
            checks.append("website wizard controls actual HTTP-only execution")

            page.get_by_role("button", name="新建检查", exact=True).first.click()
            page.locator(".asset-kind-picker button").nth(2).click()
            next_step(page)
            page.get_by_label("选择检查方式").select_option("cloud-config")
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.locator(".error-box")).to_be_visible()
            page.get_by_label("选择检查方式").select_option("cloud-external")
            expect(page.locator(".wizard-boundary")).to_contain_text("不能仅凭 IP 判断")
            expect(page.get_by_label("云服务器服务地址", exact=True)).to_be_visible()
            page.keyboard.press("Escape")
            checks.append("missing configuration blocks progress and cloud external mode explains address limits")

            page.goto(args.base_url + "/#/assets")
            expect(page.locator(".asset-library-card").first).to_be_visible()
            screenshot(page, "assets.png")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
            page.get_by_role("button", name="新建检查", exact=True).first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Tab")
            assert page.get_by_role("dialog").evaluate("element=>element.contains(document.activeElement)")
            assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
            screenshot(page, "wizard-mobile.png")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            checks.append("asset library and wizard work at 390px with modal keyboard behavior")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        record = {"passed": len(checks), "checks": checks, "jobs": jobs, "console_errors": errors}
        (output / "asset-ui-validation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
