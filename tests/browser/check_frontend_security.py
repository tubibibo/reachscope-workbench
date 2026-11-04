"""Bounded frontend security checks against new private loopback workspaces.

Synthetic keys and strings are test markers, never operator credentials. This
script does not accept a service URL and never touches the default user service.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from check_android import isolated_service
from playwright.sync_api import Route, expect, sync_playwright


def run(base: str, output: Path, executable: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    model_requests: list[str] = []
    outbound: set[str] = set()
    directory_calls: list[dict[str, Any]] = []
    first_key, second_key = "synthetic-first-key-never-real", "synthetic-second-key-never-real"
    payload = '<img src=x onerror="window.__reachscope_xss=true">'

    def handler(destination: str) -> type[BaseHTTPRequestHandler]:
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/v1/models":
                    authorization = self.headers.get("Authorization", "")
                    directory_calls.append({"destination": destination,
                                            "first_draft_key": authorization == "Bearer " + first_key,
                                            "new_endpoint_key": authorization == "Bearer " + second_key})
                    body = json.dumps({"data": [{"id": "protocol-fixture-security"}]}).encode()
                    kind = "application/json"
                else:
                    body = ("<html><title>" + payload + "</title></html>").encode()
                    kind = "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                pass
        return Fixture

    first = ThreadingHTTPServer(("127.0.0.1", 0), handler("first"))
    second = ThreadingHTTPServer(("127.0.0.1", 0), handler("second"))
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (first, second)]
    for thread in threads:
        thread.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(executable) if executable else None)
        page = browser.new_page(base_url=base, viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(5000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: model_requests.append(request.url)
                if request.method == "POST" and request.url.endswith("/advisory") else None)
        def boundary(route: Route) -> None:
            parsed = urlsplit(route.request.url)
            if parsed.scheme in {"http", "https"} and parsed.netloc != urlsplit(base).netloc:
                # Endpoint protection may inject scripts into the browser. Do
                # not disable it; block external requests in this private test.
                outbound.add(parsed.scheme + "://" + parsed.netloc)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", boundary)
        page.add_init_script("window.__reachscope_xss = false;")
        try:
            page.goto(base + "/#/settings/ai")
            expect(page.get_by_label("AI API 密钥", exact=True)).to_be_visible()
            page.get_by_label("AI 提供商预设", exact=True).select_option("custom")
            endpoint = page.get_by_label("AI 兼容接口地址", exact=True)
            key = page.get_by_label("AI API 密钥", exact=True)
            endpoint.fill(f"http://127.0.0.1:{first.server_port}/v1")
            key.fill(first_key)
            endpoint.fill(f"http://127.0.0.1:{second.server_port}/v1")
            cleared = key.input_value() == ""
            page.get_by_label("启用 AI 接口", exact=True).check()
            page.get_by_label("AI 模型标识", exact=True).fill("protocol-fixture-security")
            page.locator(".ai-advanced summary").click()
            page.get_by_label("允许本机 AI 接口", exact=True).check()
            if cleared:
                # Native required validation must block saving a new destination
                # with an empty key; then enter a distinct synthetic key.
                page.get_by_role("button", name="保存接口设置", exact=True).click()
                assert key.evaluate("input => !input.validity.valid")
                key.fill(second_key)
            page.get_by_role("button", name="保存接口设置", exact=True).click()
            expect(page.locator(".workspace-success")).to_contain_text("设置已保存")
            page.get_by_label("同意验证已保存凭据与模型目录", exact=True).check()
            page.get_by_role("button", name="验证已保存凭据与模型目录", exact=True).click()
            expect(page.locator(".ai-model-diagnosis .ai-diagnosis-result")).to_be_visible(timeout=15_000)
            leaked_to_second = any(call["destination"] == "second" and call["first_draft_key"] for call in directory_calls)
            correct_second_key = any(call["destination"] == "second" and call["new_endpoint_key"] for call in directory_calls)
            checks.append({"id": "SEC-UI-01", "name": "changing a draft endpoint clears its unsaved credential",
                           "passed": cleared and not leaked_to_second and correct_second_key,
                           "first_draft_reached_second_fixture": leaked_to_second,
                           "new_key_reached_explicit_second_fixture": correct_second_key,
                           "impact": "requires manual destination edit, explicit save and explicitly consented model-directory request; no inference"})
            storage = page.evaluate("() => ({local: {...localStorage}, session: {...sessionStorage}})")
            no_secret = all(value not in json.dumps(storage) for value in (first_key, second_key))
            page.reload()
            expect(page.get_by_label("AI API 密钥", exact=True)).to_have_value("")
            checks.append({"id": "SEC-UI-02", "name": "draft keys are neither persisted in Web Storage nor restored after reload",
                           "passed": no_secret})
            with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
                response = client.get("/")
                csp = response.headers.get("Content-Security-Policy", "")
                safe_script_policy = "script-src 'self'" in csp and "'unsafe-eval'" not in csp
                checks.append({"id": "SEC-UI-03", "name": "actual built shell has same-origin script CSP",
                               "passed": safe_script_policy, "observed_csp": csp})
                sources = re.findall(r'<script[^>]+src="([^"]+)"', response.text)
                same_origin_scripts = bool(sources) and all(source.startswith("/assets/") for source in sources)
                published_maps = list((Path(__file__).resolve().parents[2] / "src/reachscope_workbench/static").rglob("*.map"))
                downloaded = client.get("/api/host/collector")
                attachment = "attachment;" in downloaded.headers.get("Content-Disposition", "")
                html_report_checks: dict[str, Any] = {"same_origin_built_scripts": same_origin_scripts,
                    "published_source_maps": len(published_maps), "collector_attachment": attachment,
                    "collector_executed": False}

            # The normal worker handles a bounded local site. Only the advisory
            # GET responses below are deliberately hostile browser fixtures;
            # they do not claim arbitrary AI text can enter server-owned guides.
            with httpx.Client(base_url=base, trust_env=False, timeout=10,
                              headers={"X-ReachScope-Client": "workbench"}) as client:
                created = client.post("/api/assets", json={"kind": "website", "name": payload,
                    "source": {"profile_id": "website-probe", "mode": "probe", "allow_private": True,
                               "targets": [f"http://127.0.0.1:{first.server_port}/fixture"]}})
                created.raise_for_status()
                inspected = client.post(f"/api/assets/{created.json()['id']}/inspections",
                                        json={"name": payload, "checks": ["headers", "page"]})
                inspected.raise_for_status()
                job_id = inspected.json()["id"]
                deadline = time.monotonic() + 30
                while True:
                    job = client.get("/api/jobs/" + job_id).json()
                    if job["status"] not in {"queued", "running"}:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("Local website fixture did not complete")
                    time.sleep(.05)
                assert job["status"] == "completed"
                exported = client.get(f"/api/jobs/{job_id}/export", params={"format": "html"})
                html_report_checks["report_attachment"] = "attachment;" in exported.headers.get("Content-Disposition", "")
                html_report_checks["report_sandbox"] = "sandbox" in exported.headers.get("Content-Security-Policy", "")
                html_report_checks["report_title_escaped"] = payload not in exported.text and "&lt;img" in exported.text
                checks.append({"id": "SEC-UI-08", "name": "built sources and generated downloads do not publish active uploads or source maps",
                               "passed": same_origin_scripts and not published_maps and attachment
                                   and html_report_checks["report_attachment"] and html_report_checks["report_sandbox"]
                                   and html_report_checks["report_title_escaped"], **html_report_checks})
                page.goto(base + "/#/jobs/" + job_id)
                page.get_by_role("tab", name="AI 研判", exact=True).click()
                consent = page.get_by_label("确认发送 AI 摘要", exact=True)
                expect(consent).to_be_visible()
                page.get_by_label("AI 研判授权说明", exact=True).fill("Synthetic local context consent only; no inference is authorized by this test.")
                consent.check()
                original_hash = client.get(f"/api/jobs/{job_id}/advisory/preview").json()["context_sha256"]
                changed = client.put("/api/ai/config", json={
                    "enabled": True, "provider_id": "custom", "base_url": f"http://127.0.0.1:{first.server_port}/v1",
                    "model": "protocol-fixture-security", "reasoning_effort": "default",
                    "token_limit_field": "max_tokens", "allow_local": True, "api_key": first_key,
                })
                changed.raise_for_status()
                changed_hash = client.get(f"/api/jobs/{job_id}/advisory/preview").json()["context_sha256"]
                assert original_hash != changed_hash
                page.get_by_role("button", name="刷新记录", exact=True).click()
                expect(page.locator(".ai-provider-state")).to_contain_text(f"127.0.0.1:{first.server_port}")
                rebound = not consent.is_checked()
                disabled = page.get_by_role("button", name="发送摘要并生成研判", exact=True).is_disabled()
                checks.append({"id": "SEC-UI-06", "name": "explicit advisory consent is bound to the reviewed provider/context hash",
                               "passed": rebound and disabled, "preview_hash_changed": True,
                               "consent_cleared_after_changed_preview": rebound, "inference_submitted": False})
            bad_references = [
                {"title": "SEC-UI-javascript", "url": "javascript:window.__reachscope_xss=true", "kind": "fixture"},
                {"title": "SEC-UI-data", "url": "data:text/html,<svg onload=alert(1)>", "kind": "fixture"},
                {"title": "SEC-UI-http", "url": "http://example.invalid/plaintext", "kind": "fixture"},
                {"title": "SEC-UI-userinfo", "url": "https://public-fixture:NOT_A_SECRET@example.invalid/docs", "kind": "fixture"},
                {"title": "SEC-UI-whitespace", "url": "https://example.invalid/\tcontrol", "kind": "fixture"},
                {"title": "SEC-UI-allowed", "url": "https://example.invalid/allowed", "kind": "fixture"},
            ]
            report_id = "a" * 32
            advice = {"control_id": "web.csp", "priority": "medium", "evidence_ids": [], "title": payload,
                      "applicability": "manual_review", "basis": "manual_review", "category": "fixture",
                      "actions": [payload], "verification": [payload], "limitations": [payload], "references": bad_references}
            report = {"id": report_id, "job_id": job_id, "module": "web", "status": "completed", "mode": "ai_api",
                      "provider": {"base_url": "https://example.invalid/v1", "model": "protocol-fixture-security"},
                      "context_sha256": "b" * 64, "created_at": "2026-11-02T00:00:00Z", "error": None,
                      "red": [], "blue": [advice], "limitations": [payload], "usage": {},
                      "disclosure": {"fields": [], "excluded": [], "bytes": 0}}
            guide = {"guide_version": "security-fixture", "job_id": job_id, "control_id": "web.csp",
                     "title": payload, "applicability": "manual_review", "environment": "generic", "observed_stack": None,
                     "requires_environment_confirmation": True, "evidence_ids": [], "signal_statuses": [],
                     "preconditions": [payload], "red_review": [payload], "blue_steps": [payload], "verification": [payload],
                     "rollback": [payload], "acceptance": [payload], "templates": [], "references": bad_references,
                     "limitations": [payload]}

            def respond(route: Route) -> None:
                if "/controls/" in route.request.url:
                    data: dict[str, Any] = guide
                elif "/advisories?" in route.request.url:
                    data = {"items": [report], "total": 1, "limit": 25, "offset": 0}
                else:
                    data = report
                route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

            page.route(f"**/api/jobs/{job_id}/advisories?*", respond)
            page.route(f"**/api/advisories/{report_id}**", respond)
            page.goto(base + "/#/jobs/" + job_id)
            page.reload()
            expect(page.locator(".detail-heading h1")).to_have_text(payload)
            page.get_by_role("tab", name="AI 研判", exact=True).click()
            expect(page.get_by_label("AI 研判报告")).to_be_visible()
            page.locator(".ai-advice-card > details > summary").click()
            page.get_by_role("button", name="打开证据与人工操作手册", exact=True).click()
            expect(page.locator(".control-handbook-body")).to_be_visible()
            expect(page.locator(".handbook-group")).to_have_count(6)
            references = page.locator(".ai-references a")
            hrefs = references.evaluate_all("links => links.map(link => link.getAttribute('href'))")
            only_safe = len(hrefs) == 2 and all(href == "https://example.invalid/allowed" for href in hrefs)
            checks.append({"id": "SEC-UI-04", "name": "public advisory and handbook references require HTTPS without userinfo or controls",
                           "passed": only_safe, "fixture_reference_count": len(hrefs),
                           "classification": "defense in depth for server-owned references; not a demonstrated model-controlled XSS"})
            escaped = page.locator('img[src="x"]').count() == 0 and page.evaluate("window.__reachscope_xss === false")
            expect(page.locator(".ai-advice-card h4")).to_have_text(payload)
            checks.append({"id": "SEC-UI-05", "name": "stored inspection name and hostile advisory/guide strings remain inert React text",
                           "passed": escaped})
            page.screenshot(path=str(output / "security-xss-text-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator(".ai-advice-card").scroll_into_view_if_needed()
            assert page.evaluate("Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1")
            page.screenshot(path=str(output / "security-xss-text-mobile.png"), animations="disabled")
        finally:
            browser.close()
            for server in (first, second):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)
    return {"passed": all(check["passed"] for check in checks) and not errors and not model_requests,
            "checks": checks, "browser_errors": errors, "model_requests": model_requests,
            "blocked_browser_external_origins": sorted(outbound), "provider_directory_calls": directory_calls,
            "commercial_inference": False, "scope": "private temporary workspace and two synthetic local fixture destinations; no external target or inference"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    phase_output = output / args.phase
    phase_output.mkdir(exist_ok=True)
    with isolated_service(None, phase_output) as base:
        report = run(base, phase_output, args.browser)
        report["phase"] = args.phase
        # Preserve the actual test outcome even if Windows endpoint protection
        # temporarily holds a private workspace file during teardown.
        (output / f"frontend-security-{args.phase}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
