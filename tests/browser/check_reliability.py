"""Verify response-loss recovery against real mutations, plus blocked preflight UX.

The browser proxy forwards a real mutation to the local API, then drops its
response. A retry must receive the same saved asset/job rather than create another.
The script creates clearly named local synthetic test records and never probes a
public target. A final deliberate preflight response verifies the display boundary.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Route, expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/reliability-ui"))
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"checks": [], "console_errors": []}
    asset_requests: list[dict[str, Any]] = []
    inspection_requests: list[dict[str, Any]] = []
    retry_requests: list[dict[str, Any]] = []
    timeout_requests: list[dict[str, Any]] = []
    tag = time.strftime("%H%M%S")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(args.browser) if args.browser else None)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: report["console_errors"].append(str(error)))

        def response_loss(route: Route, captured: list[dict[str, Any]]) -> None:
            if route.request.method != "POST":
                route.continue_()
                return
            response = route.fetch()
            assert response.ok, response.text()
            value = response.json()
            captured.append({"id": value["id"], "key": route.request.headers.get("idempotency-key")})
            assert captured[-1]["key"]
            if len(captured) == 1:
                route.abort("failed")
            else:
                route.fulfill(response=response)

        page.route("**/api/assets", lambda route: response_loss(route, asset_requests))
        page.route("**/api/assets/*/inspections", lambda route: response_loss(route, inspection_requests))
        try:
            page.goto(args.base_url + "/#/assets")
            page.get_by_role("button", name="新建检查", exact=True).first.click()
            page.locator(".asset-kind-picker button").nth(2).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_label("选择检查方式").select_option("cloud-demo")
            page.get_by_label("资产名称").fill(f"可靠性验收 · 响应丢失 {tag}")
            page.get_by_role("button", name="下一步", exact=True).click()
            page.locator(".wizard-checks input").nth(1).uncheck()
            page.locator(".wizard-checks input").nth(2).uncheck()
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_label("本次任务名称").fill(f"可靠性验收 · 网络检查 {tag}")
            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.locator(".error-box")).to_contain_text("无法确认服务响应")
            expect(page.get_by_role("dialog")).to_have_count(1)
            expect(page.locator(".wizard-confirm")).to_contain_text("网络访问规则")
            assert len(asset_requests) == 1 and not inspection_requests
            report["checks"].append("asset saved but response lost: selections remain and no inspection was created")

            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.locator(".error-box")).to_contain_text("无法确认服务响应")
            assert len(asset_requests) == 2 and len(inspection_requests) == 1
            assert asset_requests[0] == asset_requests[1]
            expect(page.get_by_label("运行条件检查")).to_contain_text("已满足")
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(output / "response-loss-recovery.png"), animations="disabled")
            report["checks"].append("asset retry replays the same ID/key, then the real job response is deliberately lost")

            def unavailable_preflight(route: Route) -> None:
                route.abort("failed")

            page.route("**/api/assets/*/preflight", unavailable_preflight)
            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
            page.unroute("**/api/assets/*/preflight", unavailable_preflight)
            expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=30_000)
            assert len(asset_requests) == 2 and len(inspection_requests) == 2
            assert inspection_requests[0] == inspection_requests[1]
            asset_id, job_id = asset_requests[0]["id"], inspection_requests[0]["id"]
            history = page.request.get(f"{args.base_url}/api/assets/{asset_id}/jobs").json()
            assert history["total"] == 1 and history["items"][0]["id"] == job_id
            report["checks"].append("inspection retry reaches replay despite unavailable preflight; one asset has exactly one inspection")

            page.route("**/api/jobs/*/retry", lambda route: response_loss(route, retry_requests))
            page.get_by_role("button", name="重新分析", exact=True).click()
            expect(page.locator(".error-box")).to_contain_text("无法确认服务响应")
            page.get_by_role("button", name="重试 ↗", exact=True).click()
            page.wait_for_url(f"**/#/jobs/{retry_requests[0]['id']}", timeout=20_000)
            expect(page.locator(".error-box")).to_have_count(0)
            expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=30_000)
            assert len(retry_requests) == 2 and retry_requests[0] == retry_requests[1]
            history = page.request.get(f"{args.base_url}/api/assets/{asset_id}/jobs").json()
            assert history["total"] == 2
            report["checks"].append("lost retry response is recovered with the same operation key and only one new run")

            page.goto(f"{args.base_url}/#/assets/{asset_id}")
            page.get_by_role("button", name="再次检查", exact=True).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("运行条件检查")).to_contain_text("已满足")
            report["checks"].append("saved asset confirmation performs a real preflight without creating a job")

            # Display-only injection: exercise the blocked condition response from
            # the API contract without removing or changing user files.
            def blocked(route: Route) -> None:
                response = route.fetch()
                assert response.ok
                value = response.json()
                value.update(ready=False, items=[{"id": "fixture_input", "label": "输入文件", "status": "blocked",
                                                "message": "验收模拟：文件暂时不可读取，请恢复文件后重试。"}])
                route.fulfill(status=200, content_type="application/json", body=json.dumps(value))

            page.route("**/api/assets/*/preflight", blocked)
            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.get_by_label("运行条件检查")).to_contain_text("文件暂时不可读取")
            expect(page.locator(".error-box")).to_contain_text("运行条件尚未满足")
            assert page.request.get(f"{args.base_url}/api/assets/{asset_id}/jobs").json()["total"] == 2
            report["checks"].append("blocked preflight stays in confirmation and creates no job (display contract injection)")

            page.unroute("**/api/assets/*/preflight", blocked)
            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
            expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=30_000)
            assert page.request.get(f"{args.base_url}/api/assets/{asset_id}/jobs").json()["total"] == 3
            report["checks"].append("restoring the preflight condition permits the next real inspection")

            def structured_error(route: Route) -> None:
                route.fulfill(status=503, content_type="application/json", headers={"X-Request-ID": "ui-reference-fixture"},
                              body=json.dumps({"error": {"code": "SERVICE_BUSY", "message": "验收模拟：服务暂忙", "request_id": "ui-reference-fixture"}}))

            page.route("**/api/jobs/*/retry", structured_error)
            page.get_by_role("button", name="重新分析", exact=True).click()
            expect(page.locator(".error-box")).to_contain_text("服务暂忙")
            page.get_by_text("查看操作编号", exact=True).click()
            expect(page.locator(".error-reference code")).to_have_text("ui-reference-fixture")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
            page.screenshot(path=str(output / "request-reference-mobile.png"), full_page=True, animations="disabled")
            report["checks"].append("structured error keeps a request reference in optional details and fits mobile")

            page.unroute("**/api/jobs/*/retry")

            def delayed_response(route: Route) -> None:
                response = route.fetch()
                assert response.ok
                timeout_requests.append({"id": response.json()["id"], "key": route.request.headers.get("idempotency-key")})
                if len(timeout_requests) > 1:
                    route.fulfill(response=response)
                # First response is intentionally held after the real API accepts
                # the job. The client's deadline must end waiting, without any
                # automatic retry or a claim that the server task was cancelled.

            page.route("**/api/jobs/*/retry", delayed_response)
            page.clock.install()
            page.get_by_role("button", name="重新分析", exact=True).click()
            deadline = time.monotonic() + 5
            while not timeout_requests and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            assert len(timeout_requests) == 1
            page.clock.fast_forward(30_001)
            expect(page.locator(".error-box")).to_contain_text("等待服务响应超时")
            assert len(timeout_requests) == 1
            assert page.get_by_role("button", name="重新分析", exact=True).is_enabled()
            page.get_by_role("button", name="重试 ↗", exact=True).click()
            page.wait_for_url(f"**/#/jobs/{timeout_requests[0]['id']}", timeout=20_000)
            assert len(timeout_requests) == 2 and timeout_requests[0] == timeout_requests[1]
            assert page.request.get(f"{args.base_url}/api/assets/{asset_id}/jobs").json()["total"] == 4
            report["checks"].append("30-second response deadline releases the UI and manual retry replays the accepted job without automatic duplication")
            assert not report["console_errors"], report["console_errors"]
            report.update(passed=len(report["checks"]), total=len(report["checks"]), asset_id=asset_id,
                          original_job=job_id, asset_requests=asset_requests, inspection_requests=inspection_requests,
                          retry_requests=retry_requests)
            return 0
        except Exception as error:
            report.update(error=f"{type(error).__name__}: {error}", passed=len(report["checks"]))
            page.screenshot(path=str(output / "failure.png"), full_page=True, animations="disabled")
            raise
        finally:
            browser.close()
            report.update(asset_requests=asset_requests, inspection_requests=inspection_requests, retry_requests=retry_requests, timeout_requests=timeout_requests)
            (output / "reliability-ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
