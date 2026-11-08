"""Real isolated host baseline/log UI acceptance; no target or model requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from check_android import isolated_service, no_overflow
from playwright.sync_api import Page, expect, sync_playwright


def baseline(*, hardened: bool = False, host_id: str = "host-ui-01") -> dict[str, Any]:
    return {
        "schema_version": "reachscope-host/1", "host_id": host_id,
        "collected_at": "2026-11-02T00:05:00Z" if hardened else "2026-11-02T00:00:00Z",
        "ssh": {"connection_context": "global", "effective_config": "permitrootlogin " + ("no" if hardened else "yes")
                + "\npasswordauthentication " + ("no" if hardened else "yes")
                + "\npermitemptypasswords no\nmaxauthtries 3\n"},
        "nginx": {"config_dump": "http { server_tokens off; autoindex off; ssl_protocols TLSv1.2 TLSv1.3; "
                  "server { listen 443 ssl; server_name example.test; location / { } } }"},
    }


def prepare(page: Page, profile: str, name: str, raw: bytes, *, host_id: str = "host-ui-01") -> None:
    page.get_by_role("button", name="新建检查", exact=True).first.click()
    page.locator(".asset-kind-picker button").nth(3).click()
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_label("选择检查方式").select_option(profile)
    page.locator('input[type="file"]').set_input_files({"name": name, "mimeType": "text/plain", "buffer": raw})
    page.get_by_label("主机标识", exact=True).fill(host_id)
    page.get_by_role("button", name="下一步", exact=True).click()


def finish(page: Page) -> dict[str, Any]:
    page.get_by_role("button", name="开始检查", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=30_000)
    response = page.request.get("/api/jobs/" + page.url.rsplit("/jobs/", 1)[-1])
    assert response.ok
    return response.json()  # type: ignore[no-any-return]


def run(base: str, output: Path, executable: Path | None) -> dict[str, Any]:
    checks: list[str] = []
    errors: list[str] = []
    model_requests: list[str] = []
    saved: dict[str, str] = {}
    with httpx.Client(base_url=base, trust_env=False, timeout=5,
                      headers={"X-ReachScope-Client": "workbench"}) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(executable) if executable else None)
        context = browser.new_context(base_url=base, viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(12_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: model_requests.append(request.url)
                if request.method == "POST" and "/advisory" in request.url else None)
        try:
            page.goto(base + "/#/modules/host")
            expect(page.get_by_role("heading", name="主机基线与日志复核。")).to_be_visible()
            page.reload()
            expect(page.get_by_role("heading", name="主机基线与日志复核。")).to_be_visible()
            checks.append("host module route and navigation survive refresh")

            template = client.get("/api/host/template")
            template.raise_for_status()
            assert template.json()["schema_version"] == "reachscope-host/1"
            prepare(page, "host-baseline", "host-baseline.json", json.dumps(baseline()).encode())
            page.locator(".wizard-checks input").nth(1).uncheck()
            page.get_by_role("button", name="下一步", exact=True).click()
            preview = page.get_by_label("主机输入预览", exact=True)
            expect(preview).to_be_visible(timeout=20_000)
            expect(preview).to_contain_text("host-ui-01")
            assert client.get("/api/jobs").json()["total"] == 0
            preview.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "host-input-preview-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            preview.scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "host-input-preview-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            checks.append("actual baseline upload is previewed with no job, safe template and mobile layout")

            original = finish(page)
            saved["baseline"] = original["id"]
            assert original["config"]["checks"] == ["ssh"]
            assert all(row["id"].startswith("host.ssh.") for row in original["result"]["details"]["checks"])
            execution = {row["id"]: row["status"] for row in original["result"]["details"]["execution"]}
            assert execution["ssh"] == "completed" and execution["nginx"] == "skipped"
            expect(page.get_by_label("主机防御检查摘要", exact=True)).to_contain_text("操作员提供的配置资料")
            checks.append("only selected SSH rules execute and source is operator-provided rather than live monitoring")

            rows = original["result"]["details"]["checks"]
            for status in ("review", "unknown", "pass", "info", "not_applicable"):
                page.get_by_label("主机检查状态", exact=True).select_option(status)
                expect(page.locator(".host-check")).to_have_count(sum(row["status"] == status for row in rows))
            page.get_by_label("主机检查状态", exact=True).select_option("all")
            check = page.locator('.host-check[data-rule-id="host.ssh.root_login"]')
            check.locator(":scope > summary").click()
            check.locator(".host-manual-guide > summary").click()
            expect(check.locator(".host-guide-grid section")).to_have_count(5)
            check.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "host-baseline-guide-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            check.locator(".host-manual-guide").scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "host-baseline-guide-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            check.get_by_role("button", name="查看保存证据", exact=True).click()
            expect(page.get_by_role("tab", name="证据索引")).to_have_attribute("aria-selected", "true")
            expect(page.locator(".evidence-inspector")).to_contain_text("permitrootlogin")
            checks.append("all states match saved checks; manual guide and original rule evidence are accessible")

            engagement = client.post("/api/engagements", json={"name": "Host UI fixture review",
                "authorization_note": "Controlled exported files only", "asset_ids": [original["asset_id"]]})
            engagement.raise_for_status()
            eid = engagement.json()["id"]
            choices = client.get(f"/api/engagements/{eid}/candidates", params={"job_id": original["id"]})
            choices.raise_for_status()
            candidate = next(row for row in choices.json()["items"] if row["category"] == "host.ssh.root_login")
            response = client.post(f"/api/engagements/{eid}/cases", json={key: candidate[key] for key in ("job_id", "source_kind", "source_ref")})
            response.raise_for_status()
            case = response.json()
            prepare(page, "host-baseline", "corrected-host.json", json.dumps(baseline(hardened=True)).encode())
            page.locator(".wizard-checks input").nth(1).uncheck()
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("主机输入预览", exact=True)).to_be_visible(timeout=20_000)
            corrected = finish(page)
            saved["corrected"] = corrected["id"]
            assessment = client.get(f"/api/cases/{case['id']}/retest", params={"job_id": corrected["id"]})
            assert assessment.json()["outcome"] == "not_comparable"
            page.goto(base + f"/#/engagements/{eid}/cases/{case['id']}")
            page.get_by_role("button", name="配置 / 应用有修订文件？", exact=False).click()
            options = page.get_by_label("选择修订输入", exact=True)
            expect(options.locator(f'option[value="{corrected["asset_id"]}"]')).to_have_count(1)
            options.select_option(corrected["asset_id"])
            page.get_by_label("修订关联说明", exact=True).fill("Same declared host and global SSH context; controlled corrected export.")
            page.get_by_role("button", name="关联修订文件", exact=True).click()
            expect(page.locator(".linked-revisions")).to_contain_text("corrected-host.json")
            retest = page.get_by_label("选择复测检查", exact=True)
            expect(retest.locator(f'option[value="{corrected["id"]}"]')).to_have_count(1)
            retest.select_option(corrected["id"])
            expect(page.locator(".retest-outcome")).to_contain_text("本次范围内未再观察到")
            page.get_by_label("记录处理状态", exact=True).select_option("resolved")
            page.get_by_label("记录本次说明", exact=True).fill("Reviewed same-host corrected export; deployment needs separate administrator verification.")
            page.get_by_role("button", name="保存记录", exact=True).click()
            expect(page.locator(".workspace-success")).to_contain_text("记录已保存")
            closed = client.get(f"/api/cases/{case['id']}").json()
            assert closed["status"] == "resolved"
            assert client.get("/api/jobs/" + original["id"]).json() == original
            saved["closed_case"] = case["id"]
            page.screenshot(path=str(output / "host-retest-closed-desktop.png"), animations="disabled")
            checks.append("same-host revised configuration is linked, compared and manually closed through the real UI without rewriting evidence")

            access = "\n".join(f'192.0.2.9 - PRIVATE_USER [02/Nov/2026:12:00:{i:02d} +0000] '
                               '"GET /login?token=PRIVATE_TOKEN HTTP/1.1" 401 12 "-" "fixture"' for i in range(12)) + "\n"
            prepare(page, "host-access-log", "nginx-access.log", access.encode())
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("主机输入预览", exact=True)).to_be_visible(timeout=20_000)
            logged = finish(page)
            saved["access_log"] = logged["id"]
            sanitized = json.dumps(logged["result"], ensure_ascii=False)
            for private in ("PRIVATE_USER", "PRIVATE_TOKEN", "192.0.2.9", "/login?token="):
                assert private not in sanitized
            alert = next(row for row in logged["result"]["details"]["checks"] if row["id"] == "host.logs.http_auth_burst")
            assert alert["status"] == "review"
            page.get_by_role("tab", name="日志事件", exact=False).click()
            expect(page.locator(".host-events tbody tr")).to_have_count(12)
            expect(page.locator(".host-events")).to_contain_text("client-")
            page.locator(".host-events").scroll_into_view_if_needed()
            page.screenshot(path=str(output / "host-log-events-desktop.png"), animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator(".host-events tbody tr").first.scroll_into_view_if_needed()
            assert no_overflow(page)
            page.screenshot(path=str(output / "host-log-events-mobile.png"), animations="disabled")
            page.set_viewport_size({"width": 1440, "height": 1050})
            checks.append("actual Nginx log analysis has time-window evidence and no raw IP/user/URI/token in results")

            auth = "\n".join(f'Nov  2 12:00:{i:02d} host sshd[1]: Failed password for PRIVATE_USER from 192.0.2.3 port 2222 ssh2' for i in range(6)) + "\n"
            prepare(page, "host-auth-log", "auth.log", auth.encode())
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("主机输入预览", exact=True)).to_be_visible(timeout=20_000)
            unknown = finish(page)
            saved["auth_log"] = unknown["id"]
            assert all(row["status"] == "unknown" for row in unknown["result"]["details"]["checks"])
            page.get_by_role("tab", name="日志事件", exact=False).click()
            expect(page.locator(".host-events")).to_contain_text("时间未知")
            assert all(event["timestamp"] is None for event in unknown["result"]["details"]["log_events"])
            checks.append("yearless auth logs remain unknown rather than using an invented year or clean result")

            count = client.get("/api/jobs").json()["total"]
            prepare(page, "host-baseline", "mismatched-host.json", json.dumps(baseline(host_id="different-host")).encode())
            page.get_by_role("button", name="下一步", exact=True).click()
            expect(page.get_by_label("运行条件检查", exact=True)).to_contain_text("暂时无法开始", timeout=20_000)
            page.get_by_role("button", name="开始检查", exact=True).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            assert client.get("/api/jobs").json()["total"] == count
            checks.append("mismatched host identity blocks inspection without creating a job")
            assert not errors, errors
            assert not model_requests
            checks.append("all checks use isolated local files with zero AI requests and browser errors")
        finally:
            browser.close()
    return {"passed": True, "check_count": len(checks), "checks": checks, "jobs": saved,
            "browser_errors": errors, "model_requests": model_requests, "target_requests": 0, "commercial_inference": False}


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
    (output / "blue-ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "check_count": report["check_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
