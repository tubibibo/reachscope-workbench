"""Validate two real Web snapshots, their comparison and the production UI.

Start the local workbench first. The fixture serves only this machine; scripts,
forms and external resource URLs are inspected as data and must never be fetched.
Created tasks deliberately remain available in the workbench for inspection.
Requires the optional ``ui`` dependency unless ``--api-only`` is supplied.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

COOKIE_SECRETS = ("DO_NOT_PERSIST_SESSION_VALUE", "DO_NOT_PERSIST_PREFERENCE_VALUE")
FORM_SECRET = "DO_NOT_PERSIST_FORM_DEFAULT"


class FixtureState:
    def __init__(self) -> None:
        self.phase = 1
        self.requests: list[str] = []


def handler_for(state: FixtureState) -> type[BaseHTTPRequestHandler]:
    class FixtureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append(self.path)
            if self.path == "/unavailable" and state.phase == 2:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            title = "Atlas storefront — baseline" if state.phase == 1 else "Atlas storefront — current"
            if self.path == "/new":
                title = '=HYPERLINK("https://example.invalid","external")'
            method = "get" if state.phase == 1 else "post"
            body = f"""<!doctype html><html lang="en"><head><title>{title}</title>
<meta name="description" content="A local fixture for observed page metadata">
<link rel="canonical" href="https://store.example.invalid/catalog">
<link rel="stylesheet" href="/assets/site.css"></head><body>
<h1>Atlas storefront</h1><p>Snapshot {state.phase}</p>
<form action="/session" method="{method}"><input name="username" value="{FORM_SECRET}">
<input type="password" name="password"><button>Continue</button></form>
<a href="/catalog?page=2">Local catalog</a>
<a href="https://docs.example.invalid/help">External documentation</a>
<script src="https://cdn.example.invalid/library.js"></script>
<script>window.webUpgradeFixtureExecuted = true;</script>
</body></html>""".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff" if state.phase == 2 else "invalid")
            self.send_header("Cache-Control", "no-store" if state.phase == 2 else "public, max-age=60")
            if state.phase == 2:
                self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.send_header("Set-Cookie", f"session={COOKIE_SECRETS[0]}; Path=/; Secure; HttpOnly; SameSite=Lax")
                self.send_header("Set-Cookie", f"preferences={COOKIE_SECRETS[1]}; Path=/; Secure; HttpOnly; SameSite=Strict")
            else:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Set-Cookie", f"session={COOKIE_SECRETS[0]}; Path=/; SameSite=None")
                self.send_header("Set-Cookie", f"preferences={COOKIE_SECRETS[1]}; Path=/; Expires=Wed, 21 Oct 2037 07:28:00 GMT")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    return FixtureHandler


def request_json(client: httpx.Client, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(path) if payload is None else client.post(path, json=payload)
    response.raise_for_status()
    value = response.json()
    assert isinstance(value, dict), (path, value)
    return value


def complete_probe(client: httpx.Client, targets: list[str], name: str) -> dict[str, Any]:
    job = request_json(client, "/api/jobs", {
        "module": "web", "name": name,
        "config": {"mode": "probe", "targets": targets, "allow_private": True, "timeout": 3},
    })
    deadline = time.monotonic() + 30
    while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(.1)
        job = request_json(client, "/api/jobs/" + job["id"])
    assert job["status"] == "completed", job
    return job


def by_url(job: dict[str, Any], url: str) -> dict[str, Any]:
    return next(asset for asset in job["result"]["details"]["assets"] if asset["url"] == url)


def ui_acceptance(args: argparse.Namespace, jobs: dict[str, str], output: Path, checks: list[dict[str, Any]]) -> list[str]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(args.browser) if args.browser else None, headless=True,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url + "/#/jobs/" + jobs["current"])
        expect(page.locator(".detail-heading .status-tag")).to_have_text("已完成", timeout=20_000)
        expect(page.locator(".asset-table tbody tr")).to_have_count(3)
        assert page.evaluate("window.webUpgradeFixtureExecuted") is None
        checks.append({"name": "production UI loads the actual current snapshot without executing target scripts", "passed": True})

        web_tabs = page.get_by_role("tablist", name="Web 分析视图")
        web_tabs.get_by_role("tab", name="资产与响应", exact=True).focus()
        page.keyboard.press("End")
        expect(web_tabs.get_by_role("tab", name="历史对比", exact=True)).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Home")
        expect(web_tabs.get_by_role("tab", name="资产与响应", exact=True)).to_have_attribute("aria-selected", "true")
        page.keyboard.press("ArrowRight")
        expect(web_tabs.get_by_role("tab", name="配置检查", exact=True)).to_have_attribute("aria-selected", "true")
        checks.append({"name": "Web tabs support Home, End and arrow-key navigation", "passed": True})

        page.get_by_role("tab", name="配置检查", exact=True).click()
        expect(page.locator(".web-checks")).to_be_visible()
        page.get_by_label("按配置检查状态筛选").select_option("review")
        review_item = page.locator(".web-check").first
        expect(review_item).to_be_visible()
        review_item.locator("summary").first.click()
        assert not any(secret in page.locator("body").inner_text() for secret in COOKIE_SECRETS)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / "web-checks.png"), full_page=True, animations="disabled")
        checks.append({"name": "configuration review filter and cookie value privacy", "passed": True})

        page.get_by_role("tab", name="页面画像", exact=True).click()
        profile_selector = page.get_by_label("选择画像资产")
        expect(profile_selector).to_be_visible()
        inventory_option = profile_selector.locator("option").filter(has_text="/inventory").first
        if inventory_option.count():
            profile_selector.select_option(inventory_option.get_attribute("value"))
        expect(page.locator("main")).to_contain_text("password")
        expect(page.locator("main")).to_contain_text("cdn.example.invalid")
        assert page.evaluate("window.webUpgradeFixtureExecuted") is None
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / "web-page-profile.png"), full_page=True, animations="disabled")
        checks.append({"name": "observed form and external resource profile", "passed": True})

        page.get_by_role("tab", name="历史对比", exact=True).click()
        page.get_by_label("选择比较基线").select_option(jobs["baseline"])
        with page.expect_response(lambda response: "/compare?" in response.url) as response:
            page.get_by_role("button", name="比较快照", exact=True).click()
        assert response.value.ok
        expect(page.locator("main")).to_contain_text("/inventory")
        expect(page.locator("main")).to_contain_text("/retired")
        expect(page.locator("main")).to_contain_text("/new")
        changed_item = page.locator(".comparison-asset").filter(has_text="/inventory").first
        changed_item.locator("summary").first.click()
        expect(changed_item.locator(".diff-table")).to_contain_text("页面标题")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / "web-comparison.png"), full_page=True, animations="disabled")
        checks.append({"name": "real baseline selection and rendered snapshot comparison", "passed": True})

        held: list[Any] = []
        pattern = f"**/api/jobs/{jobs['current']}/compare?baseline={jobs['baseline']}"
        page.route(pattern, lambda route: held.append(route))
        page.get_by_role("button", name="比较快照", exact=True).click()
        deadline = time.monotonic() + 3
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert held, "Expected to hold an actual comparison response"
        page.get_by_label("选择比较基线").select_option("")
        for route in held:
            try:
                actual_response = route.fetch()
                route.fulfill(response=actual_response)
            except PlaywrightError:
                with contextlib.suppress(PlaywrightError):
                    route.abort()
        page.unroute(pattern)
        page.wait_for_timeout(250)
        expect(page.locator(".comparison-assets")).to_have_count(0)
        expect(page.get_by_label("选择比较基线")).to_have_value("")
        checks.append({"name": "late comparison response cannot replace a cleared baseline selection", "passed": True})
        page.get_by_label("选择比较基线").select_option(jobs["baseline"])
        page.get_by_role("button", name="比较快照", exact=True).click()
        expect(page.locator(".comparison-assets")).to_be_visible()

        with page.expect_download() as download:
            page.get_by_role("link", name=re.compile("资产 CSV")).click()
        download.value.save_as(output / "web-assets-ui.csv")
        assert list(csv.DictReader((output / "web-assets-ui.csv").read_text(encoding="utf-8-sig").splitlines()))
        checks.append({"name": "asset CSV download from the production UI", "passed": True})

        page.set_viewport_size({"width": 390, "height": 844})
        deadline = time.monotonic() + 2
        while True:
            sidebar = page.locator(".sidebar").bounding_box()
            if sidebar and sidebar["x"] + sidebar["width"] <= 1:
                break
            assert time.monotonic() < deadline, "Mobile sidebar did not finish closing"
            page.wait_for_timeout(50)
        assert page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / "web-mobile.png"), full_page=True, animations="disabled")
        checks.append({"name": "390px Web comparison layout", "passed": True})
        assert not errors, errors
        checks.append({"name": "no browser execution errors", "passed": True})
        browser.close()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/web-upgrade-validation"))
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--api-only", action="store_true")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = FixtureState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = f"http://127.0.0.1:{server.server_port}"
    checks: list[dict[str, Any]] = []
    record: dict[str, Any] = {"checks": checks, "jobs": {}, "fixture": target}
    try:
        with httpx.Client(base_url=args.base_url, headers={"X-ReachScope-Client": "workbench"}, timeout=15) as client:
            tag = time.strftime("%H%M%S")
            baseline = complete_probe(client, [target + suffix for suffix in ("/inventory", "/retired", "/unavailable")], f"Web升级验收 {tag} · 基线巡检")
            record["jobs"]["baseline"] = baseline["id"]
            before = by_url(baseline, target + "/inventory")
            assert before["page"]["analyzed"]
            assert before["page"]["forms"][0]["method"].lower() == "get"
            assert before["page"]["forms"][0]["password_fields"] == 1
            assert FORM_SECRET not in json.dumps(before["page"])
            assert any(item["external"] for item in before["page"]["scripts"])
            assert any(item["status"] == "review" for item in before["checks"])
            assert len(before["cookies"]) == 2
            assert all(secret not in json.dumps(baseline) for secret in COOKIE_SECRETS)
            checks.append({"name": "baseline page, form, resource and configuration evidence with cookie redaction", "passed": True})

            state.phase = 2
            current = complete_probe(client, [target + suffix for suffix in ("/inventory", "/new", "/unavailable")], f"Web升级验收 {tag} · 当前巡检")
            record["jobs"]["current"] = current["id"]
            after = by_url(current, target + "/inventory")
            assert after["page"]["forms"][0]["method"].lower() == "post"
            assert after["title"] != before["title"]
            assert all(secret not in json.dumps(current) for secret in COOKIE_SECRETS)
            assert sum(item["status"] == "review" for item in after["checks"]) < sum(item["status"] == "review" for item in before["checks"])
            assert not by_url(current, target + "/unavailable")["reachable"]
            checks.append({"name": "second real observation changes configuration and records an unreachable target", "passed": True})

            comparison = request_json(client, f"/api/jobs/{current['id']}/compare?baseline={baseline['id']}")
            record["comparison"] = comparison
            for status in ("added", "removed", "changed", "not_comparable"):
                assert comparison["summary"][status] == 1, comparison
            changed = next(asset for asset in comparison["assets"] if asset["status"] == "changed")
            assert changed["url"] == target + "/inventory"
            assert any(change["field"] == "title" for change in changed["changes"])
            assert changed["before_evidence_ids"] and changed["after_evidence_ids"]
            checks.append({"name": "snapshot comparison distinguishes changed, added, removed and not-comparable evidence", "passed": True})

            response = client.get(f"/api/jobs/{current['id']}/export?format=csv")
            response.raise_for_status()
            content = response.content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(content)))
            assert len(rows) == 3, rows
            formula = next(row for row in rows if row["url"].endswith("/new"))["title"]
            assert formula.startswith("'=HYPERLINK"), formula
            assert all(secret not in content for secret in COOKIE_SECRETS)
            (output / "web-assets.csv").write_bytes(response.content)
            checks.append({"name": "CSV export preserves three assets and neutralizes spreadsheet formulas", "passed": True})

            invalid = client.get(f"/api/jobs/{current['id']}/compare?baseline={'x' * 32}")
            assert invalid.status_code == 400
            checks.append({"name": "comparison rejects malformed baseline IDs", "passed": True})
            assert len(state.requests) == 6 and set(state.requests) <= {"/inventory", "/retired", "/unavailable", "/new"}, state.requests
            checks.append({"name": "exact supplied URLs only, without executing or fetching page resources", "passed": True})

        record["console_errors"] = [] if args.api_only else ui_acceptance(args, record["jobs"], output, checks)
        record["passed"] = len(checks)
        record["total"] = len(checks)
        return 0
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        record["passed"] = len(checks)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        (output / "web-upgrade-validation.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(record, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
