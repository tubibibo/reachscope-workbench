"""场景包发现与校验：恶意包必须被拒绝且不影响其他包。

多因测试逐根断言「恰好一条该错误码的 issue 且包未加载」，
保证任何一条校验单独失效都会让对应测试变红。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from reachscope_workbench.core.scenarios import (
    SCENARIO_DUPLICATE_ID,
    SCENARIO_FORMAT_UNSUPPORTED,
    SCENARIO_INVALID,
    SCENARIO_PATH_ESCAPE,
    SCENARIO_ROOT_MISSING,
    SCENARIO_TOO_LARGE,
    ScenarioLoader,
)

_GOOD_INDEX = b"<html>demo</html>"


def _valid_pack(**overrides: object) -> dict[str, object]:
    """返回一个能通过全部校验的最小包；overrides 只做顶层替换。"""
    route = {"body": "pages/index.html", "status": 200}
    pack: dict[str, object] = {
        "pack_format": 1,
        "id": "demo",
        "title": {"en": "Demo scenario", "zh": "示例场景"},
        "summary": {"en": "A minimal valid pack.", "zh": "最小合法包。"},
        "difficulty": "intro",
        "profiles": {
            "baseline": {"headers": {}, "cookies": [], "routes": {"/": route}},
            "hardened": {
                "headers": {"X-Frame-Options": "DENY"},
                "cookies": [],
                "routes": {"/": route},
            },
        },
        "expectations": [
            {"field": "headers.x-frame-options", "baseline": None, "hardened": "DENY"},
        ],
        "limits": ["仅用于本机教学演示。"],
    }
    pack.update(overrides)
    return pack


def _write_pack(
    root: Path, pack: dict[str, object], files: dict[str, bytes] | None = None
) -> Path:
    """把包写进 root/<id>/；默认附一个 pages/index.html。"""
    pack_dir = root / str(pack["id"])
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "scenario.yaml").write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=True), encoding="utf-8"
    )
    payloads = files if files is not None else {"pages/index.html": _GOOD_INDEX}
    for relative, content in payloads.items():
        target = pack_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return pack_dir


def _assert_rejected(root: Path, code: str) -> None:
    """单个坏根：恰好一条该错误码的 issue，且包未加载。"""
    catalog = ScenarioLoader([root]).discover()
    assert [issue.code for issue in catalog.issues] == [code]
    assert catalog.packs == {}


def test_discovers_minimal_pack_without_code_change(tmp_path: Path) -> None:
    """只写文件（不改任何 .py）即可被发现；目录内容零错误。"""
    _write_pack(tmp_path, _valid_pack())
    catalog = ScenarioLoader([tmp_path]).discover()
    assert catalog.packs["demo"].pack.id == "demo"
    assert catalog.issues == ()


def test_missing_root_reports_issue_and_continues(tmp_path: Path) -> None:
    """坏根产生一条 ROOT_MISSING，好根的包照常加载。"""
    good = tmp_path / "good"
    good.mkdir()
    _write_pack(good, _valid_pack())
    catalog = ScenarioLoader([tmp_path / "missing", good]).discover()
    assert [issue.code for issue in catalog.issues] == [SCENARIO_ROOT_MISSING]
    assert "demo" in catalog.packs


def test_future_pack_format_is_rejected(tmp_path: Path) -> None:
    """pack_format 高于 1 报 FORMAT_UNSUPPORTED，同轮其他包不受影响。"""
    future = dict(_valid_pack(id="future"), pack_format=2)
    _write_pack(tmp_path, future)
    _write_pack(tmp_path, _valid_pack())
    catalog = ScenarioLoader([tmp_path]).discover()
    assert [issue.code for issue in catalog.issues] == [SCENARIO_FORMAT_UNSUPPORTED]
    assert {"demo", "future"} - set(catalog.packs) == {"future"}


def test_invalid_id_and_unknown_field_rejected(tmp_path: Path) -> None:
    """大写 id 与未知顶层字段各被拒绝。"""
    _write_pack(tmp_path / "upper", _valid_pack(id="Demo"))
    _write_pack(tmp_path / "unknown", _valid_pack(unknown_field=1))
    _assert_rejected(tmp_path / "upper", SCENARIO_INVALID)
    _assert_rejected(tmp_path / "unknown", SCENARIO_INVALID)


def test_profiles_must_be_baseline_and_hardened(tmp_path: Path) -> None:
    """缺 hardened 与多出 paranoid 都拒绝。"""
    incomplete = _valid_pack()
    del incomplete["profiles"]["hardened"]  # type: ignore[union-attr]
    extra = _valid_pack()
    extra["profiles"]["paranoid"] = extra["profiles"]["baseline"]  # type: ignore[index]
    _write_pack(tmp_path / "missing", incomplete)
    _write_pack(tmp_path / "extra", extra)
    _assert_rejected(tmp_path / "missing", SCENARIO_INVALID)
    _assert_rejected(tmp_path / "extra", SCENARIO_INVALID)


def test_route_rules(tmp_path: Path) -> None:
    """空 routes、超量、无斜杠键、含 ? 键、越界 status 都拒绝。"""
    hardened = {"routes": {"/": {"body": "pages/index.html"}}}
    cases = {
        "empty": {"baseline": {"routes": {}}, "hardened": hardened},
        "many": {
            "baseline": {"routes": {f"/p{i}": {"body": "pages/index.html"} for i in range(33)}},
            "hardened": hardened,
        },
        "no-slash": {
            "baseline": {"routes": {"no-slash": {"body": "pages/index.html"}}},
            "hardened": hardened,
        },
        "query": {
            "baseline": {"routes": {"/q?": {"body": "pages/index.html"}}},
            "hardened": hardened,
        },
        "status": {
            "baseline": {"routes": {"/": {"body": "pages/index.html", "status": 600}}},
            "hardened": hardened,
        },
    }
    for name, profiles in cases.items():
        root = tmp_path / name
        _write_pack(root, _valid_pack(profiles=profiles))
        _assert_rejected(root, SCENARIO_INVALID)


def test_route_body_traversal_rejected(tmp_path: Path) -> None:
    """body 解析后逃出包根报 PATH_ESCAPE。"""
    _write_pack(tmp_path, _valid_pack(profiles={
        "baseline": {"routes": {"/": {"body": "../../secret.txt"}}},
        "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
    }))
    _assert_rejected(tmp_path, SCENARIO_PATH_ESCAPE)


def test_route_body_missing_and_bad_suffix_rejected(tmp_path: Path) -> None:
    """body 不存在与后缀不允许都拒绝。"""
    hardened = {"routes": {"/": {"body": "pages/index.html"}}}
    _write_pack(tmp_path / "missing", _valid_pack(profiles={
        "baseline": {"routes": {"/": {"body": "pages/missing.html"}}}, "hardened": hardened,
    }))
    _write_pack(tmp_path / "suffix", _valid_pack(profiles={
        "baseline": {"routes": {"/": {"body": "pages/app.js"}}}, "hardened": hardened,
    }))
    _assert_rejected(tmp_path / "missing", SCENARIO_INVALID)
    _assert_rejected(tmp_path / "suffix", SCENARIO_INVALID)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    """符号链接包目录报 PATH_ESCAPE；平台不允许建链接时跳过。"""
    outside = tmp_path / "outside-site"
    _write_pack(outside, _valid_pack())
    root = tmp_path / "packs"
    root.mkdir()
    try:
        os.symlink(outside, root / "evil", target_is_directory=True)
    except OSError:
        pytest.skip("Windows 无符号链接权限")
    catalog = ScenarioLoader([root]).discover()
    assert [issue.code for issue in catalog.issues] == [SCENARIO_PATH_ESCAPE]
    assert catalog.packs == {}


def test_oversize_pack_rejected(tmp_path: Path) -> None:
    """包内文件总字节超过 2 MiB 报 TOO_LARGE。"""
    _write_pack(tmp_path, _valid_pack(files={"pages/index.html": b"x" * (2 * 1024 * 1024 + 1)}))
    _assert_rejected(tmp_path, SCENARIO_TOO_LARGE)


def test_header_allowlist_and_reserved(tmp_path: Path) -> None:
    """白名单外的头与运行时保留头都拒绝；白名单内的头通过。"""
    cases = {
        "foreign": {"X-Powered-By": "nope"},
        "length": {"Content-Length": "5"},
        "reserved": {"X-ReachScope-Lab-Session": "x"},
    }
    for name, headers in cases.items():
        root = tmp_path / name
        _write_pack(root, _valid_pack(profiles={
            "baseline": {"headers": headers, "routes": {"/": {"body": "pages/index.html"}}},
            "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
        }))
        _assert_rejected(root, SCENARIO_INVALID)
    good = tmp_path / "good"
    _write_pack(good, _valid_pack())
    assert ScenarioLoader([good]).discover().issues == ()


def test_header_value_injection_rejected(tmp_path: Path) -> None:
    """值含 CRLF、超 512 字节、含非 ASCII、location 站外路径都拒绝。

    location 的三条边界都要覆盖：`//host` 是协议相对；`/\\\\host` 与 `/<TAB>/host`
    在浏览器 URL 解析里同样会变成 `//host`（反斜杠等价于 /、制表符被整体剔除）。
    """
    cases = {
        "crlf": ("X-Frame-Options", "DENY\r\nEvil: 1"),
        "toolong": ("X-Frame-Options", "A" * 513),
        "nonascii": ("X-Frame-Options", "拒绝"),
        "external": ("Location", "https://evil.example/"),
        "protocol-relative": ("Location", "//evil.example/"),
        "backslash": ("Location", "/\\evil.example/"),
        "tab": ("Location", "/\t/evil.example/"),
    }
    for name, (header, value) in cases.items():
        root = tmp_path / name
        _write_pack(root, _valid_pack(profiles={
            "baseline": {"headers": {header: value}, "routes": {"/": {"body": "pages/index.html"}}},
            "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
        }))
        _assert_rejected(root, SCENARIO_INVALID)
    good = tmp_path / "good"
    _write_pack(good, _valid_pack(profiles={
        "baseline": {"headers": {"Location": "/next"}, "routes": {"/": {"body": "pages/index.html"}}},
        "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
    }))
    assert ScenarioLoader([good]).discover().issues == ()


def test_cookie_grammar(tmp_path: Path) -> None:
    """Domain、超量、非法字符、缺 name=value、越界 Max-Age 都拒绝；合法 Cookie 通过。"""
    cases = {
        "domain": ["sid=abc123; Domain=example.com"],
        "toomany": [f"sid{i}=value{i}" for i in range(5)],
        "charset": ["sid=ab c"],
        "nopair": ["Secure"],
        "maxage": ["sid=abc123; Max-Age=86401"],
    }
    for name, cookies in cases.items():
        root = tmp_path / name
        _write_pack(root, _valid_pack(profiles={
            "baseline": {"cookies": cookies, "routes": {"/": {"body": "pages/index.html"}}},
            "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
        }))
        _assert_rejected(root, SCENARIO_INVALID)
    good = tmp_path / "good"
    _write_pack(good, _valid_pack(profiles={
        "baseline": {
            "cookies": [
                "sid=abc123; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=3600",
                "theme=dark",
            ],
            "routes": {"/": {"body": "pages/index.html"}},
        },
        "hardened": {"routes": {"/": {"body": "pages/index.html"}}},
    }))
    assert ScenarioLoader([good]).discover().issues == ()


def test_duplicate_id_first_root_wins_and_order_is_stable(tmp_path: Path) -> None:
    """两个根下同 id：先者保留、报一条 DUPLICATE；重复 discover 顺序稳定。"""
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_pack(first_root, _valid_pack())
    _write_pack(second_root, _valid_pack(title={"en": "Second", "zh": "第二"}))
    _write_pack(second_root, _valid_pack(id="alpha"))
    loader = ScenarioLoader([first_root, second_root])
    catalog = loader.discover()
    assert set(catalog.packs) == {"demo", "alpha"}
    assert catalog.packs["demo"].pack.title["en"] == "Demo scenario"
    duplicates = [issue for issue in catalog.issues if issue.code == SCENARIO_DUPLICATE_ID]
    assert len(duplicates) == 1
    assert loader.discover() == catalog
    assert list(catalog.packs) == sorted(catalog.packs)
    assert list(catalog.issues) == sorted(
        catalog.issues, key=lambda issue: (issue.source, issue.code, issue.message)
    )


def test_deeply_nested_yaml_is_an_issue_not_a_crash(tmp_path: Path) -> None:
    """深层嵌套 YAML 触发 RecursionError 时必须降级成 issue，不许逃出 discover()。

    PyYAML 逐层递归解析嵌套 flow sequence；4000 层足以越过 Python 默认递归上限。
    这不是理论攻击面：接运行时后，扫描在启动路径上，一个坏文件就是一次启动崩溃。
    """
    deep = "pack_format: 1\npayload: " + "[" * 4000 + "]" * 4000 + "\n"
    pack_dir = tmp_path / "deep"
    pack_dir.mkdir()
    (pack_dir / "scenario.yaml").write_text(deep, encoding="utf-8")
    catalog = ScenarioLoader([tmp_path]).discover()
    assert [issue.code for issue in catalog.issues] == [SCENARIO_INVALID]
    assert catalog.packs == {}


def test_duplicate_headers_differing_only_by_case_rejected(tmp_path: Path) -> None:
    """FIX-09：仅大小写不同的重复响应头名拒绝——两个都会发出去，浏览器取哪个不确定。"""
    routes = {"/": {"body": "pages/index.html", "status": 200}}
    _write_pack(tmp_path, _valid_pack(profiles={
        "baseline": {"headers": {"X-Frame-Options": "DENY", "x-frame-options": "SAMEORIGIN"}, "cookies": [], "routes": routes},
        "hardened": {"headers": {}, "cookies": [], "routes": routes},
    }))
    _assert_rejected(tmp_path, SCENARIO_INVALID)


def test_route_keys_reject_double_slash_backslash_and_control_chars(tmp_path: Path) -> None:
    """FIX-10：路由键与 Location 同口径——拒 // 前缀、反斜杠与控制字符。"""
    hardened = {"routes": {"/": {"body": "pages/index.html"}}}
    for index, bad in enumerate(("//link", "/a\b", "/x\ny")):
        pack = _valid_pack(profiles={
            "baseline": {"headers": {}, "cookies": [], "routes": {"/": {"body": "pages/index.html"}, bad: {"body": "pages/index.html"}}},
            "hardened": hardened,
        })
        root = tmp_path / f"case{index}"
        _write_pack(root, pack)
        _assert_rejected(root, SCENARIO_INVALID)


def test_symlinked_file_counts_toward_size_budget(tmp_path: Path) -> None:
    """FIX-11：包内文件符号链接按跟随后的真实大小计入 2 MiB 预算，不能借链接绕过。"""
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    root = tmp_path / "packs"
    pack_dir = _write_pack(root, _valid_pack())
    try:
        (pack_dir / "linked.bin").symlink_to(outside)
    except OSError:
        pytest.skip("Windows 无符号链接权限")
    _assert_rejected(root, SCENARIO_TOO_LARGE)


def test_scenario_id_pattern_has_single_source() -> None:
    """FIX-12：id 文法单一来源——API 字段模式由 model 的文本拼装，两处不再各写一份。"""
    from reachscope_workbench.api.lab import LabStart
    from reachscope_workbench.core.scenarios.model import ID_PATTERN_TEXT

    pattern = LabStart.model_fields["scenario_id"].metadata[0].pattern
    assert pattern == "^" + ID_PATTERN_TEXT + "$"
