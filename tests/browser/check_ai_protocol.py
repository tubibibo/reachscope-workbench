"""Verify the opt-in Web advisory UI against a local OpenAI-compatible protocol fixture.

The fixture is intentionally marked as a protocol simulation. It does not claim
model quality or provider compatibility. The test sends one minimized Web context,
checks the asynchronous report lifecycle, and restores the previous AI settings.
"""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/ai-ui-validation"))
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    errors: list[str] = []
    provider_requests: list[dict[str, Any]] = []
    release_provider = threading.Event()
    run_tag = time.strftime("%H%M%S")
    report: dict[str, Any] = {"checks": checks, "console_errors": errors, "protocol_simulation": True}
    headers = {"X-ReachScope-Client": "workbench"}

    class Site(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<html><title>AI fixture BODY_SECRET</title></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            provider_requests.append({"path": self.path, "model": payload.get("model"), "message_count": len(payload.get("messages", [])), "redacted": not any(value in json.dumps(payload) for value in ["PATH_SECRET", "QUERY_SECRET", "BODY_SECRET", "protocol-fixture-key"])})
            evidence = str(payload.get("messages", [{}])[-1].get("content", ""))
            # The fixture uses one known Web control and the evidence ID present
            # in the request. The server validates the shape, while ReachScope
            # remains responsible for IDs, applicability and fixed copy.
            evidence_id = ""
            try:
                parsed = json.loads(evidence)
                stack: list[Any] = [parsed]
                while stack and not evidence_id:
                    value = stack.pop()
                    if isinstance(value, dict):
                        ids = value.get("evidence_ids")
                        if isinstance(ids, list) and ids and isinstance(ids[0], str):
                            evidence_id = ids[0]
                        stack.extend(value.values())
                    elif isinstance(value, list):
                        stack.extend(value)
            except (TypeError, ValueError):
                pass
            if not evidence_id:
                self.send_response(400)
                self.end_headers()
                return
            selection = {"red": [{"control_id": "web.csp", "priority": "medium", "evidence_ids": [evidence_id]}],
                         "blue": [{"control_id": "web.csp", "priority": "medium", "evidence_ids": [evidence_id]}]}
            body = {"choices": [{"message": {"content": json.dumps(selection, ensure_ascii=False)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            release_provider.wait(timeout=15)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_: object) -> None:
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=provider.serve_forever, daemon=True)
    worker.start()
    site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    site_worker = threading.Thread(target=site.serve_forever, daemon=True)
    site_worker.start()
    old_config: dict[str, Any] | None = None
    modified_config = False
    try:
        with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
            old_config = client.get("/api/ai/config").json()
            if old_config.get("has_key"):
                raise RuntimeError("验收前检测到已有 AI 密钥；为保护会话凭据，未覆盖设置")
            asset_response = client.post("/api/assets", headers=headers, json={"kind": "website", "name": f"AI 协议验收 {run_tag}", "source": {"profile_id": "website-probe", "mode": "probe", "targets": [f"http://127.0.0.1:{site.server_port}/review/PATH_SECRET?token=QUERY_SECRET#fragment"], "allow_private": True}})
            asset_response.raise_for_status()
            asset_id = asset_response.json()["id"]
            job_response = client.post(f"/api/assets/{asset_id}/inspections", headers=headers, json={"name": f"AI 协议验收 {run_tag} / Web 基线", "checks": ["headers"]})
            job_response.raise_for_status()
            job_id = job_response.json()["id"]
            deadline = time.monotonic() + 30
            current: dict[str, Any] = {}
            while time.monotonic() < deadline:
                current = client.get(f"/api/jobs/{job_id}").json()
                if current.get("status") not in {"queued", "running"}:
                    break
                time.sleep(0.1)
            if current.get("status") != "completed":
                raise RuntimeError(f"protocol fixture probe failed: {current.get('status')}")
            preview = client.get(f"/api/jobs/{job_id}/advisory/preview").json()
            if not preview.get("eligible"):
                raise RuntimeError(f"真实 probe 不可研判：{preview.get('reason')}")
            assert not any(value in json.dumps(preview["context"]) for value in ["PATH_SECRET", "QUERY_SECRET", "BODY_SECRET"])
            report.update(job_id=job_id, context_sha256=preview["context_sha256"])
            def seed_fixture(kind: str, source: dict[str, Any], selected: list[str]) -> dict[str, Any]:
                asset = client.post("/api/assets", json={"kind": kind, "name": f"AI 协议隔离样例 {run_tag} / {kind}", "source": source})
                asset.raise_for_status()
                response = client.post(f"/api/assets/{asset.json()['id']}/inspections", json={"name": f"AI UI 来源隔离 {run_tag}", "checks": selected})
                response.raise_for_status()
                job = response.json()
                deadline = time.monotonic() + 30
                while job.get("status") in {"queued", "running"} and time.monotonic() < deadline:
                    time.sleep(.1)
                    fetched = client.get(f"/api/jobs/{job['id']}")
                    fetched.raise_for_status()
                    job = fetched.json()
                assert job.get("status") == "completed", job.get("status")
                return job

            cloud_job = next((job for job in client.get("/api/jobs?limit=100&offset=0").json()["items"] if job.get("status") == "completed" and job.get("asset_snapshot", {}).get("kind") == "cloud" and job.get("module") == "web"), None)
            if not cloud_job:
                cloud_job = seed_fixture("cloud", {"profile_id": "cloud-external", "mode": "probe", "targets": [f"http://127.0.0.1:{site.server_port}/cloud-fixture"], "allow_private": True}, ["http"])
            demo_job = next((job for job in client.get("/api/jobs?limit=100&offset=0").json()["items"] if job.get("status") == "completed" and job.get("asset_snapshot", {}).get("kind") == "website" and job.get("asset_snapshot", {}).get("source", {}).get("mode") == "demo"), None)
            if not demo_job:
                demo_job = seed_fixture("website", {"profile_id": "website-demo", "mode": "demo"}, ["fingerprints"])

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(args.browser) if args.browser else None)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True, reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(args.base_url + "/#/")
                page.get_by_role("button", name="分析总览", exact=False).click()
                expect(page.get_by_label("分析记录来源", exact=True)).to_have_value("work")
                page.goto(args.base_url + "/#/assets")
                expect(page.get_by_label("资产来源", exact=True)).to_have_value("work")
                checks.append("dashboard and asset library default to actual inputs while keeping demos in a separate source filter")
                if cloud_job:
                    page.goto(args.base_url + f"/#/jobs/{cloud_job['id']}")
                    expect(page.get_by_text("云服务 HTTP / ANALYSIS RECORD", exact=False)).to_be_visible()
                    checks.append("cloud HTTP service records stay separated from the website source label")
                page.goto(args.base_url + f"/#/jobs/{demo_job['id']}")
                page.get_by_role("tab", name="AI 研判", exact=True).click()
                expect(page.get_by_text("真实 URL", exact=False)).to_be_visible()
                assert not provider_requests
                checks.append("synthetic website demos show an ineligible notice and never reach the AI provider")
                page.goto(args.base_url + "/#/settings/ai")
                expect(page.get_by_label("AI 提供商预设", exact=True)).to_be_visible()
                page.get_by_label("AI 提供商预设", exact=True).select_option("custom")
                page.get_by_label("AI 兼容接口地址", exact=True).fill(f"http://127.0.0.1:{provider.server_port}/v1")
                page.get_by_label("AI 模型标识", exact=True).fill("protocol-fixture-not-a-real-model")
                page.get_by_label("AI API 密钥", exact=True).fill("protocol-fixture-key")
                page.get_by_label("启用 AI 接口", exact=True).check()
                page.get_by_label("推理强度", exact=True).select_option("default")
                page.locator(".ai-advanced summary").click()
                page.get_by_label("允许本机 AI 接口", exact=True).check()
                page.get_by_label("输出预算参数", exact=True).select_option("max_tokens")
                modified_config = True
                page.get_by_role("button", name="保存接口设置", exact=True).click()
                expect(page.locator("p.workspace-success")).to_contain_text("设置已保存")
                checks.append("AI settings keep the key in the session and save no provider call")

                page.goto(args.base_url + f"/#/jobs/{job_id}")
                page.get_by_role("tab", name="AI 研判", exact=True).click()
                expect(page.get_by_text("审阅即将发送的脱敏摘要", exact=False)).to_be_visible()
                expect(page.get_by_text("URL 路径/查询/片段", exact=True)).to_be_visible()
                expect(page.get_by_text("本次可用的受控目录", exact=False)).to_be_visible()
                checks.append("real probe shows a minimized preview, excluded fields and the fixed control catalog")
                page.get_by_label("AI 研判授权说明", exact=True).fill(f"本机合成网站 {run_tag}，仅授权发送本次已完成检查的脱敏摘要，用于流程验收。")
                page.get_by_label("确认发送 AI 摘要", exact=True).check()
                page.get_by_role("button", name="发送摘要并生成研判", exact=True).click()
                expect(page.locator("p.ai-pending")).to_contain_text("等待兼容接口", timeout=5000)
                release_provider.set()
                expect(page.get_by_text("已生成 / 人工待复核", exact=True)).to_be_visible(timeout=15000)
                expect(page.get_by_text("本机协议模拟：用于验证接口与状态流程", exact=False)).to_be_visible()
                expect(page.get_by_text("站点配置 / 来自已执行检查", exact=True)).to_have_count(2)
                checks.append("one explicit confirmation returns a saved asynchronous report with red/blue fixed-copy advice")
                assert len(provider_requests) == 1 and provider_requests[0]["path"] == "/v1/chat/completions" and provider_requests[0]["redacted"]
                with page.expect_download() as download:
                    page.get_by_role("link", name="研判报告", exact=True).click()
                download.value.save_as(output / "ai-advisory-report.html")
                assert (output / "ai-advisory-report.html").read_text(encoding="utf-8").find("Web AI") >= 0
                page.reload()
                page.get_by_role("tab", name="AI 研判", exact=True).click()
                page.get_by_role("button", name="protocol-fixture-not-a-real-model", exact=False).click()
                expect(page.get_by_text("已生成 / 人工待复核", exact=True)).to_be_visible(timeout=5000)
                assert len(provider_requests) == 1
                checks.append("refresh reads the saved report and does not send a second paid request")

                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
                page.screenshot(path=str(output / "ai-mobile.png"), full_page=True, animations="disabled")
                checks.append("390px Web AI view remains within viewport")
                browser.close()
    finally:
        release_provider.set()
        provider.shutdown()
        provider.server_close()
        worker.join(timeout=2)
        site.shutdown()
        site.server_close()
        site_worker.join(timeout=2)
        if old_config is not None and modified_config:
            with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
                restored = client.put("/api/ai/config", json={"enabled": old_config.get("enabled", False), "provider_id": old_config.get("provider_id", "custom"), "base_url": old_config.get("base_url", "https://api.openai.com/v1"), "model": old_config.get("model", ""), "reasoning_effort": old_config.get("reasoning_effort", "default"), "token_limit_field": old_config.get("token_limit_field", "max_tokens"), "allow_local": old_config.get("allow_local", False), "clear_key": True})
                restored.raise_for_status()
        report["provider_requests"] = provider_requests
        report["passed"] = len(checks)
        report["total"] = 8
        (output / "ai-ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
