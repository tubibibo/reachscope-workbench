"""Exercise Android reviews and real source evidence in an isolated workbench.

Runs bundled synthetic Android inputs, never installs an APK or calls a model.
Historical-payload compatibility is a separately labelled browser fixture; the
normal checks always use real worker results from the temporary API workspace.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def isolated_service(base_url: str | None, output: Path) -> Iterator[str]:
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Android UI acceptance requires an isolated loopback service")
        with httpx.Client(base_url=base_url, trust_env=False, timeout=3) as client:
            response = client.get("/api/jobs?limit=1")
            response.raise_for_status()
            if response.json().get("total") != 0:
                raise ValueError("Use a fresh temporary workspace; existing job records must not be changed")
        yield base_url.rstrip("/")
        return
    environment = {key: value for key, value in os.environ.items() if not key.startswith("REACHSCOPE_AI_")}
    environment["PYTHONIOENCODING"] = "utf-8"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="reachscope-android-ui-") as workspace, (output / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "reachscope_workbench", "serve", "--port", str(port), "--data", workspace],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(base_url=base, trust_env=False, timeout=2) as client:
                while True:
                    try:
                        response = client.get("/api/health")
                        if response.status_code == 200 and response.json().get("ready") is True:
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Isolated Android workbench did not become ready")
                    time.sleep(.1)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def begin_sample(page: Page, sample: str, *, code: bool) -> dict[str, Any]:
    page.get_by_role("button", name="新建分析", exact=True).first.click()
    page.locator(".asset-kind-picker button").nth(0).click()
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_label("选择检查方式").select_option("android-demo")
    page.get_by_label("源码样例").select_option(sample)
    page.get_by_role("button", name="下一步", exact=True).click()
    options = page.locator(".wizard-checks input")
    if not code:
        options.nth(1).uncheck()
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_label("本次任务名称").fill("Android UI / " + sample + (" / code" if code else " / manifest"))
    page.get_by_role("button", name="开始检查", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=15_000)
    expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=60_000)
    job_id = page.url.rsplit("/jobs/", 1)[-1]
    response = page.request.get("/api/jobs/" + job_id)
    if not response.ok:
        raise RuntimeError("Saved Android job could not be loaded")
    return response.json()  # type: ignore[no-any-return]


def no_overflow(page: Page) -> bool:
    return bool(page.evaluate("Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1"))


def run(base: str, output: Path, executable: Path | None) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    errors: list[str] = []
    jobs: dict[str, str] = {}
    model_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable) if executable else None)
        context = browser.new_context(base_url=base, viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(12_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: model_requests.append(request.url) if request.method == "POST" and "/advisory" in request.url else None)
        try:
            page.goto(base)
            full = begin_sample(page, "cross_component", code=True)
            jobs["full"] = full["id"]
            result = full["result"]
            review = result["details"]["security_review"]
            assert len(review["checks"]) >= 8
            expect(page.get_by_label("安卓检查摘要")).to_contain_text("合成教学样例")
            expect(page.get_by_label("安卓检查摘要")).to_contain_text("33")
            expect(page.locator(".android-check")).to_have_count(len(review["checks"]))
            assert no_overflow(page)
            checks.append({"name": "actual full Android worker returns configuration review and labelled synthetic origin", "scope": "real local worker"})

            for state in ("review", "unknown", "pass", "not_applicable"):
                page.get_by_label("筛选安卓配置状态").select_option(state)
                expect(page.locator(".android-check")).to_have_count(sum(item["status"] == state for item in review["checks"]))
            page.get_by_label("筛选安卓配置状态").select_option("all")
            page.get_by_label("搜索安卓配置检查").fill("nothing-matches-this-query")
            expect(page.locator(".android-check")).to_have_count(0)
            page.get_by_label("搜索安卓配置检查").fill("android.debuggable")
            expect(page.locator(".android-check")).to_have_count(1)
            page.get_by_label("搜索安卓配置检查").fill("")
            checks.append({"name": "all four statuses and search match saved check data, including unknown", "scope": "real local worker"})

            check = page.locator('.android-check[data-control-id="android.debuggable"]')
            check.locator(":scope > summary").click()
            check.locator(".android-guidance > summary").click()
            expect(check).to_contain_text("红队：人工复核")
            expect(check).to_contain_text("蓝队：配置补强")
            expect(check.locator(".android-guidance-grid ol")).to_have_count(4)
            check.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "android-configuration-desktop.png"), animations="disabled")
            check.get_by_role("button", name="查看保存证据", exact=True).first.click()
            expect(page.get_by_role("tab", name="证据索引")).to_have_attribute("aria-selected", "true")
            expect(page.locator(".evidence-inspector .data-block")).to_contain_text("android.debuggable")
            checks.append({"name": "saved rule opens manual red and blue guidance and its real evidence", "scope": "real local worker"})

            page.goto(base + "/#/jobs/" + full["id"])
            page.get_by_role("tab", name="分析结果", exact=True).click()
            page.get_by_role("navigation", name="安卓结果导航").get_by_role("button", name="组件与深链").click()
            page.get_by_label("筛选安卓组件导出状态").select_option("yes")
            expected_exports = sum(item.get("effective_exported", item.get("exported")) is True for item in result["details"]["components"])
            expect(page.locator(".android-components-table tbody tr")).to_have_count(expected_exports)
            page.get_by_label("筛选安卓组件导出状态").select_option("all")
            page.get_by_label("搜索组件").fill("CrossTarget")
            expect(page.locator(".android-components-table tbody tr")).to_have_count(1)
            page.get_by_label("搜索组件").fill("")
            page.get_by_label("搜索安卓深链").fill("example.com")
            expect(page.locator(".android-deeplinks-table tbody tr")).to_have_count(1)
            expect(page.get_by_label("安卓深链声明")).to_contain_text("未验证服务器")
            checks.append({"name": "component export and deep-link inventory filters retain declaration limits", "scope": "real local worker"})

            page.get_by_role("navigation", name="安卓结果导航").get_by_role("button", name="代码证据").click()
            page.locator(".path-steps button").nth(1).click()
            expect(page.locator(".code-view .code-path")).to_contain_text("CrossTarget.smali")
            expect(page.locator(".code-view pre")).to_contain_text("getStringExtra")
            expect(page.locator(".code-view pre")).to_contain_text("loadUrl")
            page.screenshot(path=str(output / "android-source-evidence.png"), animations="disabled")
            checks.append({"name": "existing candidate path still opens actual matching method source", "scope": "real local worker"})

            manifest = begin_sample(page, "permission", code=False)
            jobs["manifest"] = manifest["id"]
            assert "artifact_id" not in manifest["result"]["details"]
            assert len(manifest["result"]["details"]["security_review"]["checks"]) >= 8
            expect(page.locator(".android-execution-brief")).to_contain_text("未执行")
            expect(page.locator(".method-reader")).to_have_count(0)
            expect(page.locator(".android-components-table")).to_contain_text("未评估")
            page.get_by_label("搜索安卓权限").fill("INTERNAL")
            expect(page.locator("#android-permissions")).to_contain_text("signature")
            page.get_by_label("搜索安卓权限").fill("not-a-permission")
            expect(page.locator("#android-permissions")).to_contain_text("没有匹配的自定义权限")
            page.get_by_label("搜索安卓权限").fill("")
            checks.append({"name": "manifest-only execution preserves no-code state and custom signature permissions", "scope": "real local worker"})

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("navigation", name="安卓结果导航").get_by_role("button", name="配置复核").click()
            first = page.locator(".android-check").first
            first.locator(":scope > summary").click()
            first.locator(".android-guidance > summary").click()
            assert no_overflow(page)
            page.screenshot(path=str(output / "android-review-mobile.png"), animations="disabled")
            page.get_by_role("navigation", name="安卓结果导航").get_by_role("button", name="组件与深链").click()
            assert no_overflow(page)
            page.screenshot(path=str(output / "android-inventory-mobile.png"), animations="disabled")
            checks.append({"name": "390px mobile review and inventories have no page overflow", "scope": "real local worker"})

            # A separately labelled fixture verifies old payloads without ever
            # changing a saved result or claiming that old jobs were upgraded.
            legacy = copy.deepcopy(manifest)
            legacy["result"]["details"].pop("security_review", None)
            legacy["result"]["details"].pop("execution", None)
            legacy["result"]["details"].pop("target_sdk", None)
            legacy["result"]["details"].pop("min_sdk", None)
            for component in legacy["result"]["details"]["components"]:
                component["effective_exported"] = None
                component["export_reason"] = "Fixture: missing SDK makes effective state unknown"
            pattern = "**/api/jobs/" + manifest["id"]
            page.route(pattern, lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(legacy)))
            page.goto(base + "/#/jobs/" + manifest["id"])
            page.reload()
            expect(page.get_by_label("安卓检查摘要")).to_contain_text("没有保存新版配置复核结果")
            expect(page.locator(".android-check")).to_have_count(0)
            page.get_by_label("筛选安卓组件导出状态").select_option("unknown")
            expect(page.locator(".android-components-table tbody tr")).to_have_count(len(legacy["result"]["details"]["components"]))
            expect(page.locator(".android-components-table")).to_contain_text("信息不足")
            assert no_overflow(page)
            page.unroute(pattern)
            checks.append({"name": "legacy absent-review payload and explicit unknown exported state stay unknown", "scope": "browser compatibility fixture only"})
            assert not model_requests
            assert not errors, errors
            checks.append({"name": "no AI submission or browser console and JavaScript errors", "scope": "all browser steps"})
        finally:
            browser.close()
    return {"passed": True, "checks": checks, "check_count": len(checks), "jobs": jobs, "errors": errors,
            "model_requests": model_requests, "commercial_inference": False, "apk_execution": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with isolated_service(args.base_url, output) as base:
        result = run(base, output, args.browser)
    (output / "android-ui-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "check_count": result["check_count"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
