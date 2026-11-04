"""Browser acceptance checks for the local, animated ReachScope walkthrough.

This is a delivery verification script, not a unit test or application module.
Generate a demo first, then pass --page. Install the optional ui extra.
Use --browser for an existing Chromium/Edge executable, or install Playwright Chromium.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

CASE_IDS = {"bridge", "cross_component", "wrong_key", "permission", "missing"}
CASE_BUTTONS = "#case-list button[data-case]"


def active_code(page: Page) -> tuple[str, str]:
    return (
        page.locator("#source-path").inner_text(),
        page.locator("#code-content").inner_text(),
    )


def active_step(page: Page) -> int:
    selected = page.locator('#step-list button[data-step][aria-current="step"]')
    assert selected.count() == 1, "Exactly one actual step should be selected"
    return int(selected.get_attribute("data-step"))


def visible_cases(page: Page) -> set[str]:
    return set(page.locator(CASE_BUTTONS + ":visible").evaluate_all(
        "elements => elements.map(element => element.dataset.case)"
    ))


def choose(page: Page, case_id: str) -> None:
    page.locator("#case-search").fill("")
    page.locator('[data-filter="all"]').click()
    page.locator(f'#case-list button[data-case="{case_id}"]').click()


def overflow(page: Page) -> bool:
    return page.locator("body").evaluate(
        "element => Math.max(element.scrollWidth, document.documentElement.scrollWidth) > window.innerWidth + 1"
    )


def record(checks: list[dict[str, object]], name: str, operation: Callable[[], object]) -> None:
    try:
        detail = operation()
    except Exception as error:  # noqa: BLE001 -- Record each acceptance failure and continue.
        checks.append({"name": name, "passed": False, "error": str(error)})
    else:
        checks.append({"name": name, "passed": True, "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", type=Path, default=Path("reachscope-demo/index.html"))
    parser.add_argument("--browser", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("artifacts/validation/legacy-ui"))
    args = parser.parse_args()
    page_path = args.page.resolve()
    if not page_path.is_file():
        raise SystemExit(f"Generated page is missing: {page_path}")
    qa_dir = args.out.resolve()
    qa_dir.mkdir(parents=True, exist_ok=True)
    output = qa_dir / "frontend-qa.json"
    checks: list[dict[str, object]] = []
    errors: list[str] = []
    remote_requests: list[str] = []
    started = time.perf_counter()

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(executable_path=str(args.browser) if args.browser else None, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 960}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: remote_requests.append(request.url)
                if request.url.startswith(("http://", "https://")) else None)
        page.goto(page_path.as_uri(), wait_until="load")
        page.locator(CASE_BUTTONS).first.wait_for(state="attached")
        page.wait_for_timeout(800)

        def initial() -> object:
            ids = set(page.locator(CASE_BUTTONS).evaluate_all(
                "elements => elements.map(element => element.dataset.case)"
            ))
            assert ids == CASE_IDS, ids
            assert not overflow(page), "Desktop document overflows horizontally"
            assert page.locator("#active-title").inner_text().strip()
            return {"cases": sorted(ids), "viewport": [1280, 960]}

        record(checks, "initial render and case catalogue", initial)

        def cases() -> object:
            observed: dict[str, str] = {}
            for case_id, expected in [
                ("bridge", "SUPPORTED"),
                ("cross_component", "SUPPORTED"),
                ("wrong_key", "UNDECIDABLE"),
                ("permission", "REFUTED"),
                ("missing", "UNDECIDABLE"),
            ]:
                choose(page, case_id)
                status = page.locator("#verdict-label").inner_text()
                assert expected in status, (case_id, status)
                observed[case_id] = status
            return observed

        record(checks, "five cases retain their real verdicts", cases)

        def cross_component() -> object:
            choose(page, "cross_component")
            nodes = page.locator("#step-list button[data-step]")
            assert nodes.count() >= 2
            nodes.first.click()
            source = active_code(page)
            assert "putExtra" in source[1], source
            nodes.last.click()
            target = active_code(page)
            assert "getStringExtra" in target[1] and "loadUrl" in target[1], target
            assert source[0] != target[0], "Source and target should be different methods/files"
            return {"source": source[0], "target": target[0]}

        record(checks, "path steps expose actual source and target methods", cross_component)

        def svg_keyboard() -> object:
            choose(page, "cross_component")
            nodes = page.locator("#trace-svg [data-node]")
            assert nodes.count() >= 2
            node_count = nodes.count()
            nodes.first.click()
            assert "putExtra" in active_code(page)[1]
            target = nodes.last
            target.focus()
            assert target.evaluate("element => document.activeElement === element")
            target.press("Enter")
            assert "getStringExtra" in active_code(page)[1]
            page.locator('#case-list button[data-case="permission"]').focus()
            page.keyboard.press("Enter")
            assert "REFUTED" in page.locator("#verdict-label").inner_text()
            return {"svg_nodes": node_count, "keyboard": "Enter activates nodes and case selection"}

        record(checks, "SVG nodes and case controls work by keyboard", svg_keyboard)

        def manual_steps() -> object:
            choose(page, "cross_component")
            page.locator("#step-list button[data-step]").first.click()
            source = active_code(page)
            page.locator("#next-step").click()
            assert "getStringExtra" in active_code(page)[1]
            page.locator("#prev-step").click()
            assert active_code(page) == source
            return "Previous and next navigate the actual two-step path"

        record(checks, "manual path navigation", manual_steps)

        def playback() -> object:
            choose(page, "bridge")
            page.locator("#step-list button[data-step]").first.click()
            initial_step = active_step(page)
            page.locator("#play-trace").click()
            page.wait_for_function(
                "initial => Number(document.querySelector('#step-list [aria-current=step]').dataset.step) !== initial",
                arg=initial_step, timeout=3500,
            )
            advanced_step = active_step(page)
            assert advanced_step > initial_step
            page.locator("#play-trace").click()
            assert page.locator("#play-trace").get_attribute("aria-pressed") == "false"
            paused_step = active_step(page)
            page.wait_for_timeout(1400)
            assert active_step(page) == paused_step, "Path kept advancing after pause"
            return {"initial_step": initial_step, "advanced_step": advanced_step, "paused_step": paused_step}

        record(checks, "playback advances and can be paused", playback)

        def filters() -> object:
            page.locator("#case-search").fill("")
            groups = {
                "supported": {"bridge", "cross_component"},
                "refuted": {"permission"},
                "unknown": {"wrong_key", "missing"},
                "all": CASE_IDS,
            }
            for key, expected in groups.items():
                page.locator(f'[data-filter="{key}"]').click()
                assert visible_cases(page) == expected, (key, visible_cases(page))
            page.locator("#case-search").fill("CrossEntry")
            assert visible_cases(page) == {"cross_component"}, visible_cases(page)
            page.locator("#case-search").fill("not-a-real-case-qa")
            assert not visible_cases(page)
            page.locator("#case-search").fill("")
            assert visible_cases(page) == CASE_IDS
            return "Verdict filtering, entry search and an empty result all work"

        record(checks, "case search and verdict filters", filters)

        def unknown() -> object:
            choose(page, "wrong_key")
            assert "UNDECIDABLE" in page.locator("#verdict-label").inner_text()
            # Observations may be rendered, but no inferred path should be manufactured.
            connected = page.locator('#trace-svg [data-edge][data-connected="true"]').count()
            assert connected == 0, "The wrong-key example claims a connected path"
            return {"connected_edges": connected, "note": "Observation nodes are allowed; proven links are not"}

        record(checks, "unknown example does not invent a connected path", unknown)

        def motion() -> object:
            toggle = page.locator("#motion-toggle")
            before = toggle.get_attribute("aria-pressed")
            assert before in {"true", "false"}, before
            toggle.click()
            after = toggle.get_attribute("aria-pressed")
            assert before != after
            toggle.click()
            assert toggle.get_attribute("aria-pressed") == before
            return {"before": before, "toggled": after}

        record(checks, "global motion toggle", motion)

        def paused_case_changes() -> object:
            toggle = page.locator("#motion-toggle")
            before = toggle.get_attribute("aria-pressed")
            if before != "true":
                toggle.click()
            observed: dict[str, float] = {}
            try:
                for case_id in ("missing", "cross_component", "permission"):
                    choose(page, case_id)
                    opacity = page.locator("#workbench").evaluate(
                        "element => Number(getComputedStyle(element).opacity)"
                    )
                    assert opacity == 1, (case_id, opacity)
                    observed[case_id] = opacity
            finally:
                if before != "true":
                    toggle.click()
            return observed

        record(checks, "case switching stays opaque with all motion paused", paused_case_changes)

        def identity_and_exports() -> object:
            choose(page, "cross_component")
            toggle = page.locator("#identity-toggle")
            toggle.click()
            assert toggle.get_attribute("aria-expanded") == "true"
            assert page.locator("#identity-panel").is_visible()
            artifact_id = page.locator("#artifact-id").inner_text()
            assert len(artifact_id) == 64 and all(letter in "0123456789abcdef" for letter in artifact_id)
            toggle.click()
            assert not page.locator("#identity-panel").is_visible()
            for selector in ("#trace-link", "#claim-link"):
                target = page.locator(selector).get_attribute("href")
                assert target and (page_path.parent / target).is_file(), target
                json.loads((page_path.parent / target).read_text(encoding="utf-8"))
            return {"artifact_id": artifact_id, "local_exports_valid": True}

        record(checks, "evidence identity and real exported files", identity_and_exports)

        def reduced_motion() -> object:
            reduced = browser.new_context(viewport={"width": 1280, "height": 960}, reduced_motion="reduce")
            try:
                reduced_page = reduced.new_page()
                reduced_page.goto(page_path.as_uri(), wait_until="load")
                reduced_page.wait_for_timeout(200)
                assert reduced_page.locator("#motion-toggle").get_attribute("aria-pressed") == "true"
                running = reduced_page.evaluate(
                    "document.getAnimations().filter(animation => animation.playState === 'running').length"
                )
                assert running == 0, f"{running} animations still run with reduced motion"
                return {"running_animations": running, "motion_paused": True}
            finally:
                reduced.close()

        record(checks, "reduced motion is respected by default", reduced_motion)

        def no_javascript() -> object:
            plain = browser.new_context(java_script_enabled=False, viewport={"width": 1280, "height": 960})
            try:
                plain_page = plain.new_page()
                plain_page.goto(page_path.as_uri(), wait_until="load")
                text = plain_page.locator("body").inner_text()
                assert all(word in text for word in ("SUPPORTED", "REFUTED", "UNDECIDABLE"))
                assert all(word in text for word in ("权限", "实现", "参数"))
                return "All verdict classes and case content remain readable without JavaScript"
            finally:
                plain.close()

        record(checks, "no-JavaScript fallback", no_javascript)

        def mobile() -> object:
            mobile_context = browser.new_context(
                viewport={"width": 390, "height": 844}, device_scale_factor=1,
                is_mobile=True, has_touch=True, reduced_motion="reduce",
            )
            try:
                mobile_page = mobile_context.new_page()
                mobile_page.on("pageerror", lambda error: errors.append(str(error)))
                mobile_page.goto(page_path.as_uri(), wait_until="load")
                mobile_page.wait_for_timeout(800)
                for case_id in CASE_IDS:
                    choose(mobile_page, case_id)
                    assert not overflow(mobile_page), f"Mobile overflow for {case_id}"
                choose(mobile_page, "cross_component")
                mobile_page.locator("#step-list button[data-step]").last.click()
                assert "getStringExtra" in mobile_page.locator("#code-content").inner_text()
                mobile_page.locator("#lab").scroll_into_view_if_needed()
                mobile_page.wait_for_timeout(800)
                mobile_page.screenshot(path=str(qa_dir / "mobile-workbench.png"), full_page=False, animations="disabled")
                mobile_page.evaluate("window.scrollTo(0, 0)")
                mobile_page.wait_for_timeout(800)
                mobile_page.screenshot(path=str(qa_dir / "mobile-full.png"), full_page=True, animations="disabled")
                return {"viewport": [390, 844], "cases": 5, "horizontal_overflow": False}
            finally:
                mobile_context.close()

        record(checks, "mobile layout and touch interactions", mobile)

        choose(page, "bridge")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        page.screenshot(path=str(qa_dir / "cover.png"), animations="disabled")
        choose(page, "cross_component")
        page.locator("#step-list button[data-step]").last.click()
        page.evaluate("window.scrollTo(0, document.querySelector('.lab-toolbar').getBoundingClientRect().top + window.scrollY - 36)")
        page.wait_for_timeout(800)
        page.screenshot(path=str(qa_dir / "workbench.png"), animations="disabled")

        def no_errors() -> object:
            assert not errors, errors
            assert not remote_requests, remote_requests
            return {"console_or_page_errors": errors, "remote_requests": remote_requests}

        record(checks, "offline operation and browser errors", no_errors)
        context.close()
        browser.close()

    result = {
        "page": str(page_path),
        "checks": checks,
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
