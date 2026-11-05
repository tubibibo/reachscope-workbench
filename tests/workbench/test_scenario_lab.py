"""场景包接入运行时：按包提供路由、状态码、响应头与 Cookie 的端到端行为。

场景数据全部写入 ``tmp_path``，仓库内不创建任何场景目录。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError
from reachscope_workbench.core.scenarios.loader import ScenarioLoader
from reachscope_workbench.integrations.local_lab import LocalLab

HEADERS = {"X-ReachScope-Client": "workbench"}

_ALPHA_INDEX = "<!doctype html><html lang='en'><title>alpha</title><p>alpha home</p>"
_BETA_INDEX = "<!doctype html><html lang='en'><title>beta</title><p>beta home</p>"
_NOTES = "alpha notes for the notes route\n"

_ALPHA_MANIFEST = """\
pack_format: 1
id: alpha-pack
title:
  en: Cookie Flags
  zh: Cookie 标志
summary:
  en: Compare cookie attributes on a fixed page.
  zh: 在固定页面上对比 Cookie 属性。
difficulty: intro
profiles:
  baseline:
    headers:
      X-Content-Type-Options: nosniff
      Referrer-Policy: no-referrer
    cookies:
      - session=student; HttpOnly; SameSite=Lax
      - theme=dark; Path=/; Max-Age=600
    routes:
      /:
        body: pages/index.html
        status: 200
      /notes.txt:
        body: pages/notes.txt
        status: 404
  hardened:
    headers:
      X-Frame-Options: DENY
      Content-Security-Policy: "default-src 'none'"
    cookies:
      - session=student; Secure
    routes:
      /:
        body: pages/index.html
        status: 200
      /notes.txt:
        body: pages/notes.txt
        status: 404
"""

_BETA_MANIFEST = """\
pack_format: 1
id: beta-pack
title:
  en: Header Order
  zh: 响应头顺序
summary:
  en: A second pack to exercise switching.
  zh: 用于练习场景切换的第二个包。
difficulty: intermediate
profiles:
  baseline:
    headers:
      X-Frame-Options: SAMEORIGIN
    cookies: []
    routes:
      /:
        body: pages/index.html
        status: 200
  hardened:
    headers:
      X-Frame-Options: DENY
    cookies: []
    routes:
      /:
        body: pages/index.html
        status: 200
"""

_NO_BODY_MANIFEST = """\
pack_format: 1
id: no-body-204
title:
  en: Bodyless statuses
  zh: 无响应体状态码
summary:
  en: A 204 route must not carry a body.
  zh: 204 路由不得携带响应体。
difficulty: advanced
profiles:
  baseline:
    headers: {}
    cookies: []
    routes:
      /:
        body: pages/index.html
        status: 200
      /empty:
        body: pages/empty.html
        status: 204
  hardened:
    headers: {}
    cookies: []
    routes:
      /:
        body: pages/index.html
        status: 200
      /empty:
        body: pages/empty.html
        status: 204
"""

_BROKEN_MANIFEST = "pack_format: 99\nid: broken-pack\n"


def _write_pack(packs_root: Path, pack_id: str, manifest: str, bodies: dict[str, str]) -> Path:
    pack_dir = packs_root / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    for relative, content in bodies.items():
        target = pack_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    (pack_dir / "scenario.yaml").write_text(manifest, encoding="utf-8")
    return pack_dir


def _make_lab(packs_root: Path) -> LocalLab:
    """发现一次、构造一次，与 create_app 的启动时装配语义一致。"""
    return LocalLab(catalog=ScenarioLoader([packs_root]).discover())


def test_scenario_serves_route_status_and_body(tmp_path: Path) -> None:
    """T2：两个路由分别按声明返回不同状态码与不同响应体字节。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        assert started["status"] == "running"
        assert started["scenario"] == {"id": "alpha-pack", "title": {"en": "Cookie Flags", "zh": "Cookie 标志"},
                                       "difficulty": "intro", "limits": []}
        with httpx.Client(trust_env=False, timeout=2) as client:
            home = client.get(started["url"])
            notes = client.get(started["url"].rstrip("/") + "/notes.txt")
        assert home.status_code == 200 and home.content == _ALPHA_INDEX.encode("utf-8")
        assert notes.status_code == 404 and notes.content == _NOTES.encode("utf-8")
    finally:
        lab.stop()


def test_scenario_headers_and_cookies(tmp_path: Path) -> None:
    """T3：剖面响应头逐个出现且值相等；每条 Cookie 以独立 Set-Cookie 出现。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        with httpx.Client(trust_env=False, timeout=2) as client:
            baseline = client.get(started["url"])
            changed = lab.configure(started["generation"], "hardened")
            hardened = client.get(changed["url"])
        baseline_wire = baseline.headers.multi_items()
        baseline_items = dict(baseline_wire)
        assert baseline_items["x-content-type-options"] == "nosniff"
        assert baseline_items["referrer-policy"] == "no-referrer"
        assert baseline_items["content-type"] == "text/html; charset=utf-8"
        assert baseline_items["cache-control"] == "no-store"
        assert baseline_items["connection"] == "close"
        assert baseline_items["x-reachscope-lab-session"] == started["session_id"]
        assert baseline_items["x-reachscope-lab-generation"] == started["generation"]
        assert baseline_items["x-reachscope-lab-profile"] == "baseline"
        assert [name for name, _ in baseline_wire].index("x-content-type-options") \
            < [name for name, _ in baseline_wire].index("referrer-policy"), "作者头必须按 YAML 声明顺序发送"
        assert [value for name, value in baseline_wire if name == "set-cookie"] == [
            "session=student; HttpOnly; SameSite=Lax", "theme=dark; Path=/; Max-Age=600",
        ]
        hardened_items = dict(hardened.headers.multi_items())
        assert hardened_items["x-frame-options"] == "DENY"
        assert hardened_items["content-security-policy"] == "default-src 'none'"
        assert "x-content-type-options" not in hardened_items, "切换剖面后不得残留另一剖面的作者头"
        assert [value for name, value in hardened.headers.multi_items() if name == "set-cookie"] == [
            "session=student; Secure",
        ]
    finally:
        lab.stop()


def test_scenario_unknown_path_404_and_methods_405(tmp_path: Path) -> None:
    """T4：未声明路径 404（含 query 与百分号路径，不做解码或剥离）；非 GET 全部 405。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert client.get(started["url"].rstrip("/") + "/undeclared").status_code == 404
            assert client.get(started["url"] + "?profile=hardened").status_code == 404, "query 不剥离"
            assert client.get(started["url"].rstrip("/") + "/%6Eotes.txt").status_code == 404, "路径不做百分号解码"
            for method in ("POST", "PUT", "DELETE", "HEAD"):
                assert client.request(method, started["url"]).status_code == 405
        assert lab.status()["profile"] == "baseline"
    finally:
        lab.stop()


def test_scenario_host_check_still_applies(tmp_path: Path) -> None:
    """T5：场景模式下 Host 不是 127.0.0.1:<port> 依旧 421。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert client.get(started["url"], headers={"Host": "outside.example"}).status_code == 421
    finally:
        lab.stop()


def test_start_unknown_scenario_keeps_existing_server(tmp_path: Path) -> None:
    """T6：legacy 运行中用未知 id 启动 → LAB_SCENARIO_NOT_FOUND 且旧站点原样可用。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start()
        with pytest.raises(WorkbenchError) as failure:
            lab.start("nope")
        assert failure.value.code == "LAB_SCENARIO_NOT_FOUND"
        assert lab.status()["session_id"] == started["session_id"]
        assert lab.status()["scenario"] is None
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(started["url"])
        assert response.status_code == 200 and "not a production target" in response.text
    finally:
        lab.stop()


def test_switch_scenario_restarts(tmp_path: Path) -> None:
    """T7：运行中切到另一场景 → 新 session/generation、新端口可访问、旧端口拒绝连接。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    _write_pack(packs_root, "beta-pack", _BETA_MANIFEST, {"pages/index.html": _BETA_INDEX})
    lab = _make_lab(packs_root)
    try:
        first = lab.start("alpha-pack")
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert "alpha home" in client.get(first["url"]).text
        second = lab.start("beta-pack")
        assert second["scenario"]["id"] == "beta-pack"
        assert second["session_id"] != first["session_id"]
        assert second["generation"] != first["generation"]
        assert second["url"] != first["url"]
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert "beta home" in client.get(second["url"]).text
            with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
                client.get(first["url"])
    finally:
        lab.stop()


def test_missing_body_after_start_is_503(tmp_path: Path) -> None:
    """T8：启动后响应体文件被删 → 该路由 503 且服务器不崩，其余路由与 stop 正常。"""
    packs_root = tmp_path / "packs"
    pack_dir = _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                           {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        (pack_dir / "pages" / "index.html").unlink()
        with httpx.Client(trust_env=False, timeout=2) as client:
            broken = client.get(started["url"])
            intact = client.get(started["url"].rstrip("/") + "/notes.txt")
        assert broken.status_code == 503 and not broken.content
        assert intact.status_code == 404 and intact.content == _NOTES.encode("utf-8")
        assert lab.status()["status"] == "running"
    finally:
        assert lab.stop()["status"] == "stopped"


def test_scenarios_endpoint_lists_packs_and_issues(tmp_path: Path) -> None:
    """T9：API 按 id 升序列出已加载包，坏包只出现在 issues 里且排序稳定。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "beta-pack", _BETA_MANIFEST, {"pages/index.html": _BETA_INDEX})
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    _write_pack(packs_root, "broken-pack", _BROKEN_MANIFEST, {})
    app = create_app(tmp_path / "workspace", scenarios_dirs=(packs_root,))
    with TestClient(app) as client:
        payload = client.get("/api/lab/scenarios").json()
    # create_app 同时装配内置根：三个真实内置包与测试包按 id 混排。
    expected_ids = sorted({"alpha-pack", "beta-pack", "missing-headers", "cookie-flags", "csrf-token"})
    assert [pack["id"] for pack in payload["packs"]] == expected_ids
    assert payload["packs"][0]["title"] == {"en": "Cookie Flags", "zh": "Cookie 标志"}
    assert payload["packs"][0]["difficulty"] == "intro"
    assert len(payload["packs"][0]["summary"]) == 2
    assert payload["packs"][0]["limits"] == []
    assert [issue["source"] for issue in payload["issues"]] == ["broken-pack"]
    assert payload["issues"][0]["code"] == "SCENARIO_FORMAT_UNSUPPORTED"
    assert payload["issues"][0]["message"]


def test_api_start_with_scenario_id(tmp_path: Path) -> None:
    """T10：端到端——不带 id 启动为 legacy；带 id 启动场景并切换；未知 id 得 404 且不动现有站点。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    app = create_app(tmp_path / "workspace", scenarios_dirs=(packs_root,))
    with TestClient(app, headers=HEADERS) as client:
        legacy = client.post("/api/lab/start").json()
        assert legacy["status"] == "running" and legacy["scenario"] is None
        started = client.post("/api/lab/start", json={"scenario_id": "alpha-pack"}).json()
        assert started["scenario"]["id"] == "alpha-pack"
        assert started["session_id"] != legacy["session_id"] and started["url"] != legacy["url"]
        again = client.post("/api/lab/start", json={"scenario_id": "alpha-pack"}).json()
        assert again["session_id"] == started["session_id"], "同场景重复 start 必须幂等"
        missing = client.post("/api/lab/start", json={"scenario_id": "nope"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "LAB_SCENARIO_NOT_FOUND"
        assert client.get("/api/lab").json()["scenario"]["id"] == "alpha-pack", "未知 id 不许停掉现有场景"


def test_provenance_includes_scenario_id(tmp_path: Path) -> None:
    """T11：provenance 加性——场景模式含 scenario_id，legacy 保持 0.14 的三键形状。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        legacy = lab.start()
        legacy_provenance = lab.provenance_for(legacy["url"])
        assert legacy_provenance == {"kind": "local_training", "label": legacy["source"]["label"],
                                     "session_id": legacy["session_id"]}
        assert "scenario_id" not in legacy_provenance
        scenario = lab.start("alpha-pack")
        provenance = lab.provenance_for(scenario["url"])
        assert provenance is not None
        assert provenance["scenario_id"] == "alpha-pack"
        assert provenance["kind"] == "local_training"
        assert provenance["session_id"] == scenario["session_id"]
    finally:
        lab.stop()


def test_status_204_sends_no_body(tmp_path: Path) -> None:
    """T12：声明 204 的路由——头部照发、无响应体、Content-Length 为 0。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "no-body-204", _NO_BODY_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/empty.html": "<p>never served</p>"})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("no-body-204")
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(started["url"].rstrip("/") + "/empty")
            home = client.get(started["url"])
        assert response.status_code == 204 and response.content == b""
        assert response.headers["content-length"] == "0"
        assert response.headers["X-ReachScope-Lab-Profile"] == "baseline"
        assert home.status_code == 200 and home.content == _ALPHA_INDEX.encode("utf-8")
    finally:
        lab.stop()


def test_response_plan_is_coherent_across_profile_switch(tmp_path: Path) -> None:
    """FIX-02：一次取锁的应答计划——profile、响应头与 generation 同源，切换剖面不产生杂交响应。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        started = lab.start("alpha-pack")
        lab.configure(started["generation"], "hardened")
        plan = lab.response_for("/")
        assert plan is not None and plan["ready"] and plan["status"] == 200
        headers = dict(plan["headers"])
        assert headers["X-ReachScope-Lab-Profile"] == "hardened"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-ReachScope-Lab-Generation"] == lab.status()["generation"]
        assert lab.response_for("/undeclared") is None
        lab.stop()
        assert lab.response_for("/") == {"ready": False}
    finally:
        lab.stop()


def test_scenario_status_metadata_reflects_routes_and_title(tmp_path: Path) -> None:
    """FIX-03：场景模式下 limits.paths 是当前剖面路由键排序、资产名含场景标题；legacy 一字不动。"""
    packs_root = tmp_path / "packs"
    _write_pack(packs_root, "alpha-pack", _ALPHA_MANIFEST,
                {"pages/index.html": _ALPHA_INDEX, "pages/notes.txt": _NOTES})
    lab = _make_lab(packs_root)
    try:
        legacy = lab.start()
        assert legacy["limits"]["paths"] == ["/"]
        assert legacy["asset_template"] is not None
        assert legacy["asset_template"]["name"] == "本地教学站点 / HTTP 响应头补强"
        scenario = lab.start("alpha-pack")
        assert scenario["limits"]["paths"] == ["/", "/notes.txt"]
        assert scenario["asset_template"] is not None
        assert scenario["asset_template"]["name"] == "Cookie 标志 / baseline"
        hardened = lab.configure(scenario["generation"], "hardened")
        assert hardened["limits"]["paths"] == ["/", "/notes.txt"]
        assert hardened["asset_template"] is not None
        assert hardened["asset_template"]["name"] == "Cookie 标志 / hardened"
    finally:
        lab.stop()


def test_builtin_csrf_token_serves_and_reports(tmp_path: Path) -> None:
    """FIX-03 验收（真实 csrf-token 包）：limits.paths 含 /transfer，资产名含场景标题；/transfer 可服务。"""
    from reachscope_workbench.api.app import BUILTIN_SCENARIOS
    from reachscope_workbench.core.scenarios.loader import ScenarioLoader

    lab = LocalLab(catalog=ScenarioLoader([BUILTIN_SCENARIOS]).discover())
    try:
        started = lab.start("csrf-token")
        assert started["scenario"] is not None and started["scenario"]["id"] == "csrf-token"
        assert "/transfer" in started["limits"]["paths"]
        assert started["asset_template"] is not None
        assert "CSRF" in started["asset_template"]["name"] or "csrf" in started["asset_template"]["name"]
        assert started["asset_template"]["name"].endswith("/ baseline")
        plan = lab.response_for("/transfer")
        assert plan is not None and plan["ready"] and plan["status"] in {200, 403}
        hardened = lab.configure(started["generation"], "hardened")
        after = lab.response_for("/transfer")
        assert after is not None and after["ready"]
        assert dict(after["headers"])["X-ReachScope-Lab-Profile"] == "hardened"
        assert hardened["limits"]["paths"] == ["/", "/transfer"]
    finally:
        lab.stop()
