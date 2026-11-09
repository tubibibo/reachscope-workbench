"""Exercise real red/blue evidence, remediation and retest with a loopback fixture."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import expect, sync_playwright

from reachscope_workbench.modules.cloud.sample import demo_document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/redblue-ui"))
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    phase = {"value": 1}
    requests: list[str] = []
    tag = time.strftime("%H%M%S")
    checks: list[str] = []
    errors: list[str] = []
    report: dict[str, Any] = {"checks": checks, "console_errors": errors}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            body = f"<html lang='en'><title>Shared evidence {phase['value']}</title><p>Local review fixture</p></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            if phase["value"] == 2:
                self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'")
                self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    try:
        with httpx.Client(base_url=args.base_url, headers={"X-ReachScope-Client": "workbench"}, timeout=30) as client:
            def request(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
                response = client.get(path) if data is None else client.post(path, json=data)
                response.raise_for_status()
                value: dict[str, Any] = response.json()
                return value

            asset = request("/api/assets", {"kind": "website", "name": f"红蓝协作 {tag} / 本机站点", "source": {
                "profile_id": "website-probe", "mode": "probe", "targets": [f"http://127.0.0.1:{server.server_port}/review"], "allow_private": True}})

            def inspect(name: str, saved_asset: dict[str, Any] | None = None, selected_checks: list[str] | None = None) -> dict[str, Any]:
                job = request(f"/api/assets/{(saved_asset or asset)['id']}/inspections", {"name": name, "checks": selected_checks or ["headers"]})
                until = time.monotonic() + 30
                while job["status"] in {"queued", "running"} and time.monotonic() < until:
                    time.sleep(.1)
                    job = request("/api/jobs/" + job["id"])
                assert job["status"] == "completed", job
                return job

            baseline = inspect(f"红蓝协作 {tag} / 配置基线")
            report.update(asset_id=asset["id"], baseline_job=baseline["id"])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(args.browser) if args.browser else None)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True, reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))

                def screenshot(filename: str) -> None:
                    page.evaluate("scrollTo(0,0)")
                    page.screenshot(path=str(output / filename), full_page=True, animations="disabled")

                page.goto(args.base_url + "/#/engagements")
                page.get_by_role("button", name="新建工作区", exact=True).first.click()
                dialog = page.get_by_role("dialog")
                dialog.get_by_label("工作区名称", exact=False).fill(f"红蓝协作 {tag} / 发布复核")
                dialog.get_by_label("本次目标", exact=False).fill("以同一网站响应为线索，跟踪配置调整和人工复测。")
                dialog.get_by_label("授权与范围说明", exact=False).fill("本机合成站点，仅 GET 已保存地址，不加载资源或执行脚本。")
                dialog.get_by_role("checkbox", name=asset["name"]).check()
                dialog.get_by_role("button", name="建立工作区", exact=True).click()
                page.wait_for_url("**/#/engagements/*")
                workspace_id = page.url.split("/engagements/")[1].split("/")[0]
                report["engagement_id"] = workspace_id
                expect(page.get_by_role("heading", name=f"红蓝协作 {tag} / 发布复核", exact=True)).to_be_visible()
                checks.append("create a real workspace with explicit saved-asset scope and authorization record")
                page.get_by_role("button", name="从检查添加线索", exact=True).click()
                dialog = page.get_by_role("dialog")
                dialog.get_by_label("选择线索检查", exact=True).select_option(baseline["id"])
                source = dialog.locator("article").filter(has=page.get_by_role("heading", name="CSP 基础配置", exact=True))
                expect(source).to_be_visible()
                source.get_by_role("button", name="加入工作区", exact=True).click()
                page.wait_for_url("**/cases/*")
                case_id = page.url.rsplit("/", 1)[1]
                report["case_id"] = case_id
                expect(page.get_by_role("heading", name="CSP 基础配置", exact=True)).to_be_visible()
                assert request("/api/cases/" + case_id)["confidence"] not in {"confirmed", "verified"}
                screenshot("red-evidence.png")
                checks.append("red view promotes a real source candidate without upgrading confidence or losing evidence")

                page.get_by_role("tab", name="蓝队 · 整改复测", exact=True).click()
                page.get_by_label("记录处理状态", exact=True).select_option("in_progress")
                page.get_by_label("记录负责人", exact=True).fill("本地维护负责人")
                page.get_by_label("记录截止日期", exact=True).fill("2026-12-01")
                page.get_by_label("记录本次说明", exact=True).fill("先调整实施型 CSP，再使用同址响应复测。")
                page.get_by_role("button", name="保存记录", exact=True).click()
                expect(page.locator("p.workspace-success")).to_contain_text("记录已保存")
                persisted = request("/api/cases/" + case_id)
                assert persisted["status"] == "in_progress" and persisted["owner"] == "本地维护负责人"
                checks.append("blue view persists ownership, deadline, status and a new manual note")

                concurrent = client.patch("/api/cases/" + case_id, json={
                    "expected_version": persisted["version"], "owner": "另一窗口维护人"})
                concurrent.raise_for_status()
                page.get_by_label("记录负责人", exact=True).fill("旧版本修改")
                page.get_by_role("button", name="保存记录", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("请刷新记录")
                assert request("/api/cases/" + case_id)["owner"] == "另一窗口维护人"
                page.get_by_role("alert").get_by_role("button", name="重试", exact=False).click()
                expect(page.get_by_label("记录负责人", exact=True)).to_have_value("另一窗口维护人")
                checks.append("concurrent edits show a version conflict and refresh rather than overwrite the newer record")

                phase["value"] = 2
                current = inspect(f"红蓝协作 {tag} / 配置复测")
                report["retest_job"] = current["id"]
                page.get_by_role("button", name="刷新历史", exact=True).click()
                expect(page.get_by_label("选择复测检查", exact=True).locator(f"option[value='{current['id']}']")).to_have_count(1)
                page.get_by_label("选择复测检查", exact=True).select_option(current["id"])
                expect(page.locator(".retest-outcome")).to_contain_text("本次范围内未再观察到")
                page.get_by_label("记录本次说明", exact=True).fill("已查看同址后续响应，记录规则匹配结果，等待人工关闭决定。")
                page.get_by_role("button", name="记录本次复测", exact=True).click()
                expect(page.locator("p.workspace-success")).to_contain_text("条目状态没有自动关闭")
                assert request("/api/cases/" + case_id)["status"] == "in_progress"
                checks.append("completed same-asset retest is comparable and recorded without automatic closure")

                page.get_by_label("记录处理状态", exact=True).select_option("resolved")
                page.get_by_role("button", name="保存记录", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("需要本次说明")
                assert request("/api/cases/" + case_id)["status"] == "in_progress"
                page.get_by_label("记录本次说明", exact=True).fill("已核对实施型 CSP 响应证据及本次检查范围，人工复核后关闭此配置条目。")
                page.get_by_role("button", name="保存记录", exact=True).click()
                expect(page.locator("p.workspace-success")).to_contain_text("记录已保存")
                assert request("/api/cases/" + case_id)["status"] == "resolved"
                page.get_by_label("记录本次说明", exact=True).fill("已关闭后补充交接说明，保留原来的复测依据。")
                page.get_by_role("button", name="保存记录", exact=True).click()
                expect(page.locator("p.workspace-success")).to_contain_text("记录已保存")
                assert request("/api/cases/" + case_id)["status"] == "resolved"
                screenshot("blue-retest.png")
                checks.append("resolution requires new manual rationale and the comparable completed retest")
                checks.append("editing a resolved record retains its decision without submitting another closure transition")

                with page.expect_download() as download:
                    page.get_by_role("link", name="导出报告", exact=False).click()
                download.value.save_as(output / "workspace-report.html")
                assert (output / "workspace-report.html").read_text(encoding="utf-8").find("CSP") >= 0
                page.reload()
                expect(page.get_by_role("heading", name="CSP 基础配置", exact=True)).to_be_visible()
                assert page.get_by_label("记录处理状态", exact=True).input_value() == "resolved"
                checks.append("workspace export downloads actual evidence and refresh preserves case state")

                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
                screenshot("redblue-mobile.png")
                page.get_by_role("tab", name="蓝队 · 整改复测", exact=True).focus()
                page.keyboard.press("Home")
                expect(page.get_by_role("tab", name="红队 · 验证线索", exact=True)).to_have_attribute("aria-selected", "true")
                assert not errors, errors
                checks.append("390px layout, keyboard view switching and escaped saved text produce no browser errors")

                def cloud_asset(mitigated: bool) -> dict[str, Any]:
                    document = demo_document()
                    if mitigated:
                        document["planned_values"]["root_module"]["resources"][0]["values"]["ingress"][0]["cidr_blocks"] = ["10.0.0.0/24"]
                    upload = client.post("/api/uploads", files={"file": ("review-plan.json", json.dumps(document).encode(), "application/json")})
                    upload.raise_for_status()
                    return request("/api/assets", {"kind": "cloud", "name": f"红蓝协作 {tag} / {'修订' if mitigated else '原始'}配置", "source": {
                        "profile_id": "cloud-config", "mode": "import", "upload_id": upload.json()["id"], "filename": "review-plan.json"}})

                original, revised_asset = cloud_asset(False), cloud_asset(True)
                original_job = inspect(f"红蓝协作 {tag} / 文件基线", original, ["network"])
                revised_job = inspect(f"红蓝协作 {tag} / 文件复测", revised_asset, ["network"])
                file_workspace = request("/api/engagements", {"name": f"红蓝协作 {tag} / 文件修订", "objective": "离线配置修订与范围核对", "authorization_note": "本地产生的合成配置；没有真实云账号或外部云请求。", "asset_ids": [original["id"]]})
                candidate = next(item for item in request(f"/api/engagements/{file_workspace['id']}/candidates?job_id={original_job['id']}")["items"] if item["category"] == "network.public_sensitive_ports")
                file_case = request(f"/api/engagements/{file_workspace['id']}/cases", {"job_id": original_job["id"], "source_kind": candidate["source_kind"], "source_ref": candidate["source_ref"]})
                assert request(f"/api/cases/{file_case['id']}/retest?job_id={revised_job['id']}")["outcome"] == "not_comparable"
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.goto(args.base_url + f"/#/engagements/{file_workspace['id']}/cases/{file_case['id']}")
                page.get_by_role("tab", name="蓝队 · 整改复测", exact=True).click()
                page.get_by_role("button", name="如何关联修订文件", exact=False).click()
                expect(page.get_by_label("选择修订输入", exact=True).locator(f"option[value='{revised_asset['id']}']")).to_have_count(1)
                page.get_by_label("选择修订输入", exact=True).select_option(revised_asset["id"])
                assert page.get_by_role("button", name="关联修订文件", exact=False).is_disabled()
                page.get_by_label("修订关联说明", exact=True).fill("人工核对为同一合成资源的新 plan；将公网 CIDR 调整为专用网段。")
                page.get_by_role("button", name="关联修订文件", exact=False).click()
                expect(page.locator("p.workspace-success").filter(has_text="修订输入已关联")).to_be_visible()
                expect(page.get_by_label("选择复测检查", exact=True).locator(f"option[value='{revised_job['id']}']")).to_have_count(1)
                page.get_by_label("选择复测检查", exact=True).select_option(revised_job["id"])
                expect(page.locator(".retest-outcome")).to_contain_text("本次使用显式关联的修订输入")
                assert request(f"/api/engagements/{file_workspace['id']}")["asset_ids"] == [original["id"]]
                assert request("/api/cases/" + file_case["id"])["asset_id"] == original["id"]
                screenshot("cloud-revision.png")
                checks.append("offline file revision needs explicit rationale, yields a comparable retest and preserves original scope")

                latest = request("/api/cases/" + file_case["id"])
                for index in range(101):
                    updated = client.patch("/api/cases/" + file_case["id"], json={"expected_version": latest["version"], "owner": f"分页合成记录 {index + 1}"})
                    updated.raise_for_status()
                    latest = updated.json()
                page.reload()
                expect(page.locator(".case-timeline > details")).to_have_count(100)
                page.get_by_role("button", name="载入更多时间线", exact=False).click()
                expect(page.locator(".case-timeline > details")).to_have_count(latest["version"])
                expect(page.get_by_role("button", name="载入更多时间线", exact=False)).to_have_count(0)
                assert not errors, errors
                checks.append("audit timeline loads later real events by cursor without truncating or duplicating the loaded history")
                report.update(revision_engagement=file_workspace["id"], revision_case=file_case["id"], revision_asset=revised_asset["id"], timeline_events=latest["version"])
                browser.close()
            assert requests == ["/review", "/review"], requests
            report.update(passed=len(checks), total=len(checks), fixture_requests=requests)
            return 0
    except Exception as exc:
        report.update(error=f"{type(exc).__name__}: {exc}", passed=len(checks))
        raise
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        (output / "redblue-ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
