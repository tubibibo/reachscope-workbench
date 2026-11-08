"""Verify real cloud previews, offline guides and cloud-service Web evidence.

Uses a fresh temporary workspace and the fixed managed loopback teaching site.
No cloud credentials, remote infrastructure, commercial model or AI fixture is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from check_android import isolated_service, no_overflow
from playwright.sync_api import Page, expect, sync_playwright


def document() -> dict[str, Any]:
    return {"format_version": "1.2", "planned_values": {"root_module": {"resources": [
        {"address": "aws_security_group.public_fixture", "type": "aws_security_group", "name": "public_fixture",
         "values": {"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}]}},
        {"address": "aws_security_group_rule.incomplete_fixture", "type": "aws_security_group_rule", "name": "incomplete_fixture",
         "values": {"type": "ingress", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}},
        {"address": "aws_s3_bucket_public_access_block.partial_fixture", "type": "aws_s3_bucket_public_access_block", "name": "partial_fixture",
         "values": {"block_public_acls": True}},
        {"address": "aws_iam_policy.unselected_fixture", "type": "aws_iam_policy", "name": "unselected_fixture",
         "values": {"policy": {"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}}},
        {"address": "aws_instance.inventory_fixture", "type": "aws_instance", "name": "inventory_fixture",
         "values": {"user_data": "PRIVATE_INPUT_VALUE_NEVER_SHOWN_IN_PREVIEW"}},
    ]}}}


def new_cloud(page: Page) -> None:
    page.get_by_role("button", name="新建检查", exact=True).first.click()
    page.locator(".asset-kind-picker button").nth(2).click()
    page.get_by_role("button", name="下一步", exact=True).click()


def wait_job(page: Page, base: str) -> dict[str, Any]:
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=30_000)
    response = page.request.get(base + "/api/jobs/" + page.url.rsplit("/jobs/", 1)[-1])
    assert response.ok
    return response.json()  # type: ignore[no-any-return]


def run(base: str, output: Path, executable: Path | None) -> dict[str, Any]:
    checks: list[str] = []
    errors: list[str] = []
    model_requests: list[str] = []
    jobs: dict[str, str] = {}
    with httpx.Client(base_url=base, trust_env=False, timeout=5,
                      headers={"X-ReachScope-Client": "workbench"}) as client, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable) if executable else None)
        context = browser.new_context(base_url=base, viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(12_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: model_requests.append(request.url) if request.method == "POST" and "/advisory" in request.url else None)
        try:
            page.goto(base)
            new_cloud(page)
            page.get_by_label("选择检查方式").select_option("cloud-config")
            page.locator('input[type="file"]').set_input_files({"name": "cloud-coverage-fixture.json", "mimeType": "application/json", "buffer": json.dumps(document()).encode()})
            page.get_by_role("button", name="下一步", exact=True).click()
            page.locator(".wizard-checks input").nth(1).uncheck()
            expect(page.locator(".wizard-boundary")).to_contain_text("还不会创建检查任务")
            page.get_by_role("button", name="下一步", exact=True).click()
            preview = page.get_by_label("云配置输入预览", exact=True)
            expect(preview).to_be_visible(timeout=20_000)
            expect(preview).to_contain_text("Terraform Plan JSON")
            expect(preview.locator(".cloud-preview-counts dd")).to_have_text(["5", "4", "1"])
            expect(preview.locator(".cloud-preview-table tbody tr")).to_have_count(2)
            assert client.get("/api/jobs").json()["total"] == 0
            assert client.get("/api/assets").json()["total"] == 1
            assert "PRIVATE_INPUT_VALUE" not in preview.inner_text()
            assert "public_fixture" not in preview.inner_text()
            checks.append("actual uploaded cloud config is saved and previewed before any inspection job exists")

            preview.locator(".cloud-preview-gaps > summary").click()
            expect(preview).to_contain_text("缺少字段")
            expect(preview).to_contain_text("protocol")
            expect(preview).to_contain_text("unsupported_resource")
            preview.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "cloud-input-preview-desktop.png"), animations="disabled")
            assert no_overflow(page)
            page.set_viewport_size({"width": 390, "height": 844})
            preview.locator("header").scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "cloud-input-preview-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            checks.append("preview separates selected groups, missing fields and unsupported resources without raw values")

            page.get_by_role("button", name="开始检查", exact=True).click()
            cloud = wait_job(page, base)
            jobs["cloud"] = cloud["id"]
            assert cloud["config"]["checks"] == ["network", "storage"]
            execution = {item["id"]: item["status"] for item in cloud["result"]["details"]["execution"]}
            assert execution == {"network": "completed", "iam": "skipped", "storage": "completed"}
            saved_checks = cloud["result"]["details"]["checks"]
            assert all(item["guidance"]["executed"] is False for item in saved_checks)
            assert all(not item["id"].startswith("iam.") for item in saved_checks)
            expect(page.get_by_label("云配置覆盖摘要")).to_contain_text("未选择：身份与权限")
            for state in ("review", "unknown", "pass", "not_applicable"):
                page.get_by_label("云检查状态", exact=True).select_option(state)
                expect(page.locator(".cloud-results .web-check")).to_have_count(sum(item["status"] == state for item in saved_checks))
            page.get_by_label("云检查状态", exact=True).select_option("all")
            checks.append("selected cloud rule groups really execute; unknown and unselected work remain distinct")

            first = page.locator(".cloud-results .web-check").first
            first.locator(":scope > summary").click()
            first.locator(".cloud-manual-guidance > summary").click()
            expect(first).to_contain_text("红队：复核配置条件")
            expect(first).to_contain_text("蓝队：最小化配置范围")
            expect(first.locator(".cloud-manual-grid ol")).to_have_count(5)
            first.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "cloud-manual-guide-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            first.locator(".cloud-manual-guidance").scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "cloud-manual-guide-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            first.get_by_role("button", name="查看原始证据", exact=True).click()
            expect(page.get_by_role("tab", name="证据索引")).to_have_attribute("aria-selected", "true")
            expect(page.locator(".evidence-inspector .data-block")).to_contain_text("aws_security_group.public_fixture")
            expect(page.locator(".evidence-inspector .data-block")).to_contain_text('"deployed_state_verified": false')
            checks.append("cloud manual red and blue guides lead to saved original evidence without execution or AI")

            page.get_by_role("tab", name="分析结果", exact=True).click()
            resource_tab = page.get_by_role("tab", name="资源清单", exact=False)
            resource_tab.click()
            expect(page.locator(".cloud-resource")).to_have_count(5)
            expect(page.locator(".cloud-resource")).to_contain_text(["可审查资源", "可审查资源", "可审查资源", "可审查资源", "未覆盖资源"])
            resource_tab.press("ArrowLeft")
            expect(page.locator("#cloud-tab-checks")).to_have_attribute("aria-selected", "true")
            checks.append("resource inventory and keyboard tabs preserve unsupported resources")

            new_cloud(page)
            page.get_by_label("选择检查方式").select_option("cloud-config")
            page.locator('input[type="file"]').set_input_files({"name": "invalid-fixture.json", "mimeType": "application/json", "buffer": b"{"})
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("运行条件检查")).to_contain_text("暂时无法开始", timeout=15_000)
            expect(page.get_by_label("云配置输入预览", exact=True)).to_have_count(0)
            assert client.get("/api/jobs").json()["total"] == 1
            page.keyboard.press("Escape")
            checks.append("malformed JSON blocks preflight without creating a job or fabricated coverage")

            response = client.post("/api/lab/start", json={})
            response.raise_for_status()
            lab = response.json()
            new_cloud(page)
            page.get_by_label("选择检查方式").select_option("cloud-external")
            page.get_by_label("云服务器服务地址", exact=True).fill(lab["url"])
            page.locator(".checkbox-field input").check()
            page.get_by_role("button", name="下一步", exact=True).click()
            for index in (2, 3):
                page.locator(".wizard-checks input").nth(index).uncheck()
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_role("button", name="开始检查", exact=True).click()
            service = wait_job(page, base)
            jobs["cloud_service"] = service["id"]
            assert service["asset_snapshot"]["kind"] == "cloud" and service["module"] == "web"
            response = client.get(f"/api/jobs/{service['id']}/controls")
            response.raise_for_status()
            assert response.json()["origin"] == "cloud_service_probe"
            assert response.json()["ai_required"] is False and response.json()["items"]
            page.get_by_role("tab", name="配置实施指南", exact=True).click()
            expect(page.locator(".job-control-guides")).to_contain_text("云服务")
            expect(page.locator(".job-guide-grid .ai-advice-card").first).to_be_visible()
            expect(page.locator(".job-control-guides")).to_contain_text("HTTP")
            page.locator(".job-control-guides").scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "cloud-service-web-guides.png"), animations="disabled")
            checks.append("saved cloud service URL uses actual bounded Web evidence and no-AI HTTP guides")

            assert not model_requests
            assert not errors, errors
            client.post("/api/lab/stop", json={}).raise_for_status()
            checks.append("all flows remain local with zero AI submissions or browser errors")
        finally:
            browser.close()
    return {"passed": True, "check_count": len(checks), "checks": checks, "jobs": jobs, "errors": errors,
            "commercial_inference": False, "model_requests": model_requests, "cloud_credentials": False}


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
    (output / "web-cloud-ui-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "check_count": result["check_count"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
