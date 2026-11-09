"""Exercise the 0.14 host preparation and existing case workflow in private data.

Uses deliberately controlled v2 upload fixtures, not a claim that a Linux host
was collected. Downloads are saved for inspection but never executed here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from check_android import isolated_service, no_overflow
from check_blue_team import baseline, finish, prepare
from playwright.sync_api import Page, expect, sync_playwright


def projected(*, hardened: bool = False, failed_ssh: bool = False) -> dict[str, Any]:
    value = baseline(hardened=hardened)
    value["schema_version"] = "reachscope-host/2"
    value["nginx"] = None
    value["collector"] = {
        "version": "0.14.0", "projection": "reachscope-minimal/1", "plan_sha256": "a" * 64,
        "components": {
            "ssh": {"state": "collected", "complete": True, "exit_code": 0, "reason_code": "ok"},
            "nginx": {"state": "unavailable", "complete": False, "exit_code": None, "reason_code": "missing_executable"},
        },
    }
    if failed_ssh:
        value["ssh"] = None
        value["collected_at"] = "2026-11-02T00:03:00Z"
        value["collector"]["components"]["ssh"] = {
            "state": "failed", "complete": False, "exit_code": 1, "reason_code": "nonzero_exit",
        }
    return value


def upload(page: Page, name: str, value: dict[str, Any]) -> dict[str, Any]:
    prepare(page, "host-baseline", name, json.dumps(value).encode())
    page.get_by_role("button", name="下一步", exact=True).click()
    expect(page.get_by_label("主机输入预览", exact=True)).to_be_visible(timeout=20_000)
    return finish(page)


def link(page: Page, asset_id: str, note: str) -> None:
    page.get_by_label("主机加固处理步骤").get_by_role("button", name="02", exact=False).click()
    options = page.get_by_label("选择修订输入", exact=True)
    expect(options.locator(f'option[value="{asset_id}"]')).to_have_count(1)
    options.select_option(asset_id)
    page.get_by_label("修订关联说明", exact=True).fill(note)
    page.get_by_role("button", name="关联修订文件", exact=True).click()
    expect(page.locator(".workspace-success")).to_contain_text("修订输入已关联")


def run(base: str, output: Path, executable: Path | None) -> dict[str, Any]:
    checks: list[str] = []
    errors: list[str] = []
    ai_requests: list[str] = []
    saved: dict[str, str] = {}
    with httpx.Client(base_url=base, trust_env=False, timeout=10,
                      headers={"X-ReachScope-Client": "workbench"}) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(executable) if executable else None)
        context = browser.new_context(base_url=base, viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: ai_requests.append(request.url)
                if request.method == "POST" and "/advisory" in request.url else None)
        try:
            page.goto(base + "/#/modules/host")
            page.get_by_role("button", name="新建检查", exact=True).first.click()
            page.locator(".asset-kind-picker button").nth(3).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_label("选择检查方式").select_option("host-baseline")
            preparation = page.get_by_label("准备主机配置资料", exact=True)
            expect(preparation).to_contain_text("--ssh-context global --output snapshot.json")
            expect(preparation).to_contain_text("--collect --plan-sha256 PLAN_SHA256")
            for label, filename in (("下载只读采集器", "reachscope-host-collector.pyz"),
                                    ("下载源码审阅", "reachscope-host-collector-source.zip"),
                                    ("使用 v1 格式模板", "reachscope-host-template.json")):
                with page.expect_download() as info:
                    preparation.get_by_role("link", name=label, exact=False).click()
                download = info.value
                assert download.suggested_filename == filename
                download.save_as(output / filename)
            assert (output / "reachscope-host-collector.pyz").read_bytes() == (output / "reachscope-host-collector-source.zip").read_bytes()
            assert client.get("/api/jobs").json()["total"] == 0
            preparation.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "host-preparation-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            preparation.scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "host-preparation-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            checks.append("download-only plan/source/template controls work with matching output/context commands and no job or execution")

            page.locator('input[type="file"]').set_input_files({"name": "projected-before.json", "mimeType": "application/json",
                                                              "buffer": json.dumps(projected()).encode()})
            page.get_by_label("主机标识", exact=True).fill("host-ui-01")
            page.get_by_role("button", name="下一步", exact=True).click()
            page.get_by_role("button", name="下一步", exact=True).click()
            preview = page.get_by_label("主机输入预览", exact=True)
            expect(preview).to_be_visible(timeout=20_000)
            expect(preview.locator('[data-collector-component="ssh"]')).to_contain_text("资料已导出")
            expect(preview.locator('[data-collector-component="nginx"]')).to_contain_text("命令不可用")
            expect(preview).to_contain_text("未独立认证")
            assert client.get("/api/jobs").json()["total"] == 0
            original = finish(page)
            saved["original"] = original["id"]
            rules = original["result"]["details"]["checks"]
            assert all(row["status"] == "unknown" for row in rules if row["id"].startswith("host.nginx."))
            expect(page.get_by_label("采集资料状态")).to_contain_text("命令不可用")
            checks.append("real v2 upload preview preserves declared failure and projection limits; missing Nginx never passes")

            action = page.get_by_label("从主机证据进入整改", exact=True)
            action.get_by_role("button", name="选择证据建立事项", exact=False).click()
            action.get_by_role("button", name="建立包含此资产的工作区", exact=False).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("工作区名称", exact=False).fill("Controlled host journey")
            dialog.get_by_label("本次目标", exact=False).fill("Controlled offline SSH baseline review")
            dialog.get_by_label("授权与范围说明", exact=False).fill("Operator-owned controlled fixture only; no live host or network target.")
            expect(dialog.locator('.scope-asset-options input[type="checkbox"]:checked')).to_have_count(1)
            dialog.get_by_role("button", name="建立工作区", exact=True).click()
            expect(dialog).to_have_count(0)
            choices = action.get_by_label("选择主机整改证据", exact=True)
            expected = next(row for row in client.get(f"/api/engagements/{action.get_by_label('选择主机整改工作区').input_value()}/candidates",
                                                     params={"job_id": original["id"]}).json()["items"]
                            if row["category"] == "host.ssh.root_login")
            choices.select_option(expected["source_ref"])
            create = action.get_by_role("button", name="确认建立整改事项", exact=True)
            expect(create).to_be_disabled()
            action.get_by_label("确认主机整改工作区", exact=True).check()
            # Timing-only browser fixture: the real server commits normally;
            # delay one fetch resolution to exercise duplicate clicks/cancel.
            page.evaluate("""() => {
                const original = window.fetch.bind(window); let delayed = false;
                window.fetch = async (input, init) => {
                    const response = await original(input, init);
                    if (!delayed && init?.method === 'POST' && /\\/engagements\\/[^/]+\\/cases$/.test(String(input))) {
                        delayed = true;
                        await new Promise(resolve => setTimeout(resolve, 1800));
                    }
                    return response;
                };
            }""")
            create.click()
            expect(action.get_by_role("button", name="正在建立…", exact=False)).to_be_disabled()
            action.get_by_role("button", name="停止等待建立结果", exact=True).click()
            expect(action).to_contain_text("服务端可能已建立事项")
            page.wait_for_timeout(1900)
            assert "/jobs/" in page.url
            create.click()
            expect(page.get_by_label("主机加固处理步骤", exact=True)).to_be_visible()
            case_url = page.url
            case_id = case_url.rsplit("/cases/", 1)[-1]
            saved["case"] = case_id
            case = client.get("/api/cases/" + case_id).json()
            assert case["job_id"] == original["id"] and case["status"] == "open"
            assert client.get(f"/api/engagements/{case['engagement_id']}/cases").json()["total"] == 1
            checks.append("actual result-to-scope-to-candidate UI creates one explicitly confirmed case with original evidence")
            checks.append("delayed real create response is cancellable without stale navigation; retry uses the same idempotency key and preserves one case")

            failed = upload(page, "failed-capture.json", projected(failed_ssh=True))
            saved["failed"] = failed["id"]
            assert all(row["status"] == "unknown" for row in failed["result"]["details"]["checks"])
            expect(page.get_by_label("采集资料状态").locator('[data-collector-component="ssh"]')).to_contain_text("采集失败")
            page.goto(case_url)
            link(page, failed["asset_id"], "Controlled failed capture; retain unknown, never a fix.")
            page.get_by_label("选择复测检查", exact=True).select_option(failed["id"])
            expect(page.locator(".retest-outcome.outcome-not_comparable")).to_be_visible()
            expect(page.locator(".host-retest-help")).to_contain_text("下一步先补齐比较条件")
            assert client.get("/api/cases/" + case_id).json()["status"] == "open"
            checks.append("failed SSH capture stays unknown and visible non-comparable guidance cannot close the case")

            old = upload(page, "legacy-safe.json", baseline(hardened=True))
            saved["legacy"] = old["id"]
            expect(page.locator(".host-results")).to_contain_text("没有 v2")
            page.goto(case_url)
            link(page, old["asset_id"], "Deliberate v1/v2 format mismatch for comparable-scope guard.")
            page.get_by_label("选择复测检查", exact=True).select_option(old["id"])
            expect(page.locator(".retest-outcome.outcome-not_comparable")).to_be_visible()
            expect(page.locator(".host-retest-help")).to_contain_text("格式/投影版本")
            checks.append("legacy uploads remain supported, while full v1 and projected v2 are not silently compared")

            corrected = upload(page, "projected-corrected.json", projected(hardened=True))
            saved["corrected"] = corrected["id"]
            page.goto(case_url)
            link(page, corrected["asset_id"], "Same declared host/global context/projection; controlled later corrected export.")
            page.get_by_label("主机加固处理步骤").get_by_role("button", name="03", exact=False).click()
            page.get_by_label("选择复测检查", exact=True).select_option(corrected["id"])
            expect(page.locator(".retest-outcome")).to_contain_text("本次范围内未再观察到")
            page.get_by_label("主机加固处理步骤").get_by_role("button", name="04", exact=False).click()
            page.get_by_label("记录处理状态", exact=True).select_option("resolved")
            page.get_by_label("记录本次说明", exact=True).fill("Reviewed controlled same-host later projection and evidence. Runtime deployment is outside this UI fixture.")
            page.get_by_role("button", name="保存记录", exact=True).click()
            expect(page.locator(".workspace-success")).to_contain_text("记录已保存")
            expect(page.get_by_label("主机加固处理步骤")).to_contain_text("已记录人工关闭")
            assert client.get("/api/cases/" + case_id).json()["status"] == "resolved"
            assert client.get("/api/jobs/" + original["id"]).json() == original
            checks.append("same projected context revision links, compares and closes only after explicit human note without changing original input")
            page.get_by_label("主机加固处理步骤").scroll_into_view_if_needed()
            page.screenshot(path=str(output / "host-journey-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_label("主机加固处理步骤").scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "host-journey-mobile.png"), animations="disabled")
            assert not errors, errors
            assert not ai_requests
            checks.append("desktop/mobile journey has no horizontal overflow, browser error or model request")
        finally:
            browser.close()
    return {"passed": True, "check_count": len(checks), "checks": checks, "jobs": saved,
            "browser_errors": errors, "ai_requests": ai_requests, "target_requests": 0,
            "commercial_inference": False, "linux_collection_verified": False,
            "input_origin": "controlled v1/v2 upload fixtures; downloaded collector is not executed by this test"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with isolated_service(args.base_url, output) as base:
        report = run(base, output, args.browser)
    (output / "host-journey-ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "check_count": report["check_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
