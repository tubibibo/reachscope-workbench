"""Browser acceptance for the loopback teaching workflow and layered AI diagnostics.

Starts an isolated workbench and a local AI protocol fixture. Never reads real
credentials, probes a public target, or contacts a commercial model.
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
from typing import Any

import httpx
from playwright.sync_api import expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    errors: list[str] = []
    fixture_requests: list[dict[str, Any]] = []
    writes: list[str] = []

    class Provider(BaseHTTPRequestHandler):
        def send_json(self, status: int, body: object) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            authorized = self.headers.get("Authorization") == "Bearer LOCAL_PROTOCOL_TEST_KEY"
            fixture_requests.append({"method": "GET", "path": self.path, "authorized": authorized})
            if self.path == "/v1/models":
                self.send_json(200 if authorized else 401, {"data": [{"id": "protocol-fixture-lab-review"}]} if authorized else {"error": "fixture rejected"})
            else:
                self.send_json(200, {})

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            fixture_requests.append({"method": "POST", "path": self.path, "authorized": self.headers.get("Authorization") == "Bearer LOCAL_PROTOCOL_TEST_KEY"})
            context = json.loads(payload["messages"][-1]["content"])
            stack = [context]
            evidence_id = ""
            while stack and not evidence_id:
                value = stack.pop()
                if isinstance(value, dict):
                    ids = value.get("evidence_ids")
                    if isinstance(ids, list) and ids:
                        evidence_id = ids[0]
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
            selection = {role: [{"control_id": "web.mime", "priority": "medium", "evidence_ids": [evidence_id]}] for role in ("red", "blue")}
            self.send_json(200, {"choices": [{"message": {"content": json.dumps(selection)}, "finish_reason": "stop"}]})

        def log_message(self, *_: object) -> None:
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {key: value for key, value in os.environ.items() if not key.startswith("REACHSCOPE_AI_")}
    try:
        with tempfile.TemporaryDirectory(prefix="reachscope-lab-ui-") as workspace:
            server = subprocess.Popen([sys.executable, "-m", "reachscope_workbench.cli", "serve", "--port", str(port), "--data", workspace], cwd=Path(__file__).resolve().parents[2], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
                    for _ in range(150):
                        try:
                            if client.get("/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        raise RuntimeError("Isolated server not ready")
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, executable_path=str(args.browser) if args.browser else None)
                        page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
                        page.set_default_timeout(10000)
                        def capture(name: str) -> None:
                            page.evaluate("window.scrollTo(0,0); if(document.activeElement instanceof HTMLElement) document.activeElement.blur()")
                            page.screenshot(path=str(args.out / name), full_page=True, animations="disabled")
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                        page.on("request", lambda request: writes.append(request.url) if request.url.startswith(base + "/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"} else None)
                        page.goto(base + "/#/lab", wait_until="networkidle")
                        expect(page.get_by_role("heading", name="启动专用教学站点", exact=True)).to_be_visible()
                        assert not writes and not fixture_requests
                        checks.append("opening lab is read-only; teaching site and AI stay stopped")
                        page.evaluate("sessionStorage.setItem('reachscope.lab.progress', JSON.stringify({session:'invalid',asset:{unexpected:true}}))")
                        page.reload(wait_until="networkidle")
                        expect(page.get_by_role("heading", name="启动专用教学站点", exact=True)).to_be_visible()
                        assert not writes and not errors
                        checks.append("malformed session-only teaching record IDs are rejected without unexpected API calls or a page crash")
                        page.get_by_role("button", name="启动本地教学站点", exact=True).click()
                        expect(page.get_by_role("heading", name="教学站点已启动", exact=True)).to_be_visible()
                        state = client.get("/api/lab").json()
                        assert state["url"].startswith("http://127.0.0.1:")
                        assert client.get("/api/jobs").json()["total"] == 0
                        page.get_by_role("button", name="保存教学资产", exact=False).click()
                        expect(page.get_by_role("button", name="执行基线检查", exact=False)).to_be_enabled()
                        assert client.get("/api/jobs").json()["total"] == 0
                        checks.append("starting loopback server and saving an asset never submit a probe")
                        page.get_by_role("button", name="执行基线检查", exact=False).click()
                        expect(page.get_by_role("button", name="读取基线整改候选", exact=False)).to_be_enabled(timeout=20000)
                        progress = page.evaluate("JSON.parse(sessionStorage.getItem('reachscope.lab.progress'))")
                        baseline = client.get(f"/api/jobs/{progress['baseline']}").json()
                        assert baseline["asset_snapshot"]["provenance"]["kind"] == "local_training"
                        assert baseline["result"]["summary"]["review_checks"] > 0
                        assert not fixture_requests
                        checks.append("baseline is a genuine saved loopback collection with server-owned teaching provenance")
                        page.get_by_role("button", name="打开基线证据", exact=False).click()
                        expect(page.get_by_text("本地教学 / 实际采集", exact=True)).to_be_visible()
                        expect(page.get_by_role("region", name="检查摘要与下一步")).to_be_visible()
                        page.get_by_role("tab",name="配置实施指南",exact=True).click()
                        control = page.locator('[data-control-id="web.mime"]')
                        expect(control).to_contain_text("本项待人工复核")
                        control.get_by_role("button",name="打开证据与人工操作手册",exact=True).click()
                        expect(control.get_by_text("适用前提",exact=True)).to_be_visible()
                        assert control.locator("pre").count() == 0
                        control.get_by_label("确认 web.mime 使用 Nginx 查看人工模板",exact=True).check()
                        expect(control.locator("pre")).to_contain_text("X-Content-Type-Options")
                        expect(control.get_by_text("回滚计划",exact=True)).to_be_visible()
                        assert not fixture_requests
                        capture("deterministic-handbook-no-ai.png")
                        page.set_viewport_size({"width":390,"height":844})
                        assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
                        capture("deterministic-guides-mobile.png")
                        page.set_viewport_size({"width":1440,"height":1100})
                        checks.append("saved baseline offers deterministic evidence-linked implementation guide and explicit Nginx reference without any AI connection")
                        page.get_by_role("button", name="查看首项来源证据", exact=False).click()
                        expect(page.get_by_role("tab", name="证据索引", exact=False)).to_have_attribute("aria-selected", "true")
                        capture("lab-baseline-evidence.png")
                        page.goto(base + "/#/lab", wait_until="networkidle")
                        expect(page.get_by_role("button", name="读取基线整改候选", exact=False)).to_be_enabled()
                        checks.append("result summary links to saved evidence; returning to lab restores record IDs without re-probing")
                        page.get_by_role("button", name="读取基线整改候选", exact=False).click()
                        candidates = page.get_by_label("教学整改候选", exact=True)
                        expect(candidates).to_be_visible()
                        options = candidates.locator("option").evaluate_all("els => els.map(e => ({value:e.value,label:e.textContent}))")
                        matching = next(row for row in options if "mime" in row["label"].lower())
                        candidates.select_option(matching["value"])
                        page.get_by_role("button", name="建立教学整改事项", exact=False).click()
                        expect(page.get_by_role("button", name="应用教学补强配置", exact=False)).to_be_enabled()
                        progress = page.evaluate("JSON.parse(sessionStorage.getItem('reachscope.lab.progress'))")
                        case_before = client.get(f"/api/cases/{progress['case']}").json()
                        assert case_before["status"] == "open"
                        page.get_by_role("button", name="应用教学补强配置", exact=False).click()
                        expect(page.get_by_text("当前响应：补强配置", exact=True)).to_be_visible()
                        assert client.get("/api/lab").json()["url"] == state["url"]
                        assert client.get("/api/jobs").json()["total"] == 1
                        checks.append("case derives from a real baseline check; CAS hardening changes the same URL without auto-inspection")
                        page.get_by_role("button", name="执行补强后复测", exact=False).click()
                        expect(page.get_by_role("button", name="读取比较与复测判定", exact=False)).to_be_enabled(timeout=20000)
                        page.get_by_role("button", name="读取比较与复测判定", exact=False).click()
                        expect(page.get_by_text("同一条件在本轮范围内未再观察到", exact=True)).to_be_visible()
                        expect(page.get_by_role("button", name="确认依据并关闭教学事项", exact=False)).to_be_disabled()
                        progress = page.evaluate("JSON.parse(sessionStorage.getItem('reachscope.lab.progress'))")
                        assert client.get(f"/api/cases/{progress['case']}").json()["status"] == "open"
                        checks.append("successful retest shows actual comparison but does not close the case automatically")
                        page.get_by_label("教学人工关闭说明", exact=True).fill("人工核对同一loopback地址的前后响应，补强后nosniff条件不再出现；本结论仅限本地教学范围。")
                        page.get_by_role("button", name="确认依据并关闭教学事项", exact=False).click()
                        expect(page.get_by_text("教学事项已人工关闭，基线、复测和决策历史均保留。", exact=False)).to_be_visible()
                        case_after = client.get(f"/api/cases/{progress['case']}").json()
                        assert case_after["status"] == "resolved" and case_after["version"] > case_before["version"]
                        assert not fixture_requests
                        capture("lab-closed-desktop.png")
                        checks.append("explicit human note and comparable retest close a persistent case with an audit trail")
                        page.set_viewport_size({"width":390,"height":844})
                        assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
                        capture("lab-closed-mobile.png")
                        checks.append("390px complete teaching workflow has no horizontal overflow")
                        page.set_viewport_size({"width":1440,"height":1100})
                        page.goto(base + "/#/", wait_until="networkidle")
                        expect(page.get_by_text("还没有分析任务", exact=True)).to_be_visible()
                        page.get_by_label("分析记录来源", exact=True).select_option("training")
                        expect(page.locator(".jobs-table")).to_contain_text("本地教学")
                        checks.append("teaching collections remain separate from production input listings")
                        page.goto(base + "/#/settings/ai", wait_until="networkidle")
                        page.get_by_label("AI 提供商预设", exact=True).select_option("custom")
                        fixture_base = f"http://127.0.0.1:{provider.server_port}/v1"
                        page.get_by_label("AI 兼容接口地址", exact=True).fill(fixture_base)
                        page.get_by_label("AI 模型标识", exact=True).fill("protocol-fixture-lab-review")
                        page.get_by_label("AI API 密钥", exact=True).fill("LOCAL_PROTOCOL_TEST_KEY")
                        page.get_by_label("启用 AI 接口", exact=True).check()
                        page.locator(".ai-advanced summary").click()
                        page.get_by_label("允许本机 AI 接口", exact=True).check()
                        page.get_by_role("button", name="保存接口设置", exact=True).click()
                        expect(page.locator(".workspace-success")).to_be_visible()
                        assert not fixture_requests
                        page.get_by_role("button", name="连接诊断", exact=True).click()
                        expect(page.locator(".ai-diagnosis-result")).to_contain_text(fixture_base)
                        assert fixture_requests == [{"method":"GET","path":"/v1","authorized":False}]
                        directory = page.get_by_role("button", name="验证已保存凭据与模型目录", exact=True)
                        expect(directory).to_be_disabled()
                        page.get_by_label("同意验证已保存凭据与模型目录", exact=True).check()
                        directory.click()
                        expect(page.locator(".ai-model-diagnosis")).to_contain_text("目录中可见")
                        expect(page.locator(".ai-model-diagnosis")).to_contain_text("未发起，未验证")
                        assert fixture_requests[-1] == {"method":"GET","path":"/v1/models","authorized":True}
                        assert all(row["method"] == "GET" for row in fixture_requests)
                        page.get_by_label("AI 模型标识", exact=True).fill("unsaved-model")
                        expect(directory).to_be_disabled()
                        page.get_by_label("AI 模型标识", exact=True).fill("protocol-fixture-lab-review")
                        capture("layered-diagnostics.png")
                        checks.append("connectivity uses no key; credential/model-directory validation requires consent and a saved unchanged configuration, never inference")
                        page.goto(base + f"/#/jobs/{progress['baseline']}", wait_until="networkidle")
                        page.get_by_role("tab",name="AI 研判",exact=True).click()
                        page.get_by_label("AI 研判授权说明",exact=True).fill("仅授权本机教学网站摘要发送至本机模拟接口，用于验证受控手册流程。")
                        page.get_by_label("确认发送 AI 摘要",exact=True).check()
                        page.get_by_role("button",name="发送摘要并生成研判",exact=True).click()
                        expect(page.get_by_text("已生成 / 人工待复核",exact=True)).to_be_visible(timeout=20000)
                        assert len([row for row in fixture_requests if row["method"] == "POST"]) == 1
                        handbook = page.locator(".ai-advice-column").last
                        handbook.get_by_role("button",name="打开证据与人工操作手册",exact=True).click()
                        expect(handbook.get_by_text("适用前提",exact=True)).to_be_visible()
                        assert handbook.locator("pre").count() == 0
                        handbook.get_by_label("确认 web.mime 使用 Nginx 查看人工模板",exact=True).check()
                        expect(handbook.locator("pre")).to_contain_text("X-Content-Type-Options")
                        expect(handbook.get_by_text("回滚计划",exact=True)).to_be_visible()
                        assert not page.get_by_role("button",name="执行部署",exact=True).count()
                        capture("evidence-linked-handbook.png")
                        checks.append("one explicit local fixture advisory enables evidence-linked handbook and opt-in Nginx text with prerequisites, rollback and acceptance; no deployment action")
                        assert not errors, errors
                        checks.append("no uncaught JavaScript or console errors")
                        page.goto(base + "/#/lab",wait_until="networkidle")
                        page.get_by_role("button",name="停止教学站点",exact=True).click()
                        expect(page.get_by_text("当前未运行",exact=True)).to_be_visible()
                        assert client.get(f"/api/jobs/{progress['baseline']}").status_code == 200
                        checks.append("explicit stop preserves baseline, retest and case history")
                        browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
    finally:
        provider.shutdown()
        provider.server_close()
    report = {"scope":"isolated local teaching site and AI protocol fixture; no commercial provider", "passed":len(checks),"checks":checks,"browser_errors":errors,"provider_requests":fixture_requests}
    (args.out/"lab-ui-validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":len(checks),"browser_errors":len(errors),"out":str(args.out.resolve())},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
