"""场景包发现与加载：只读数据、逐包隔离失败、绝不抛出。

``discover()`` 的任何错误都以 :class:`ScenarioIssue` 报告；
单个坏包只影响自己，其余包照常加载。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import (
    SCENARIO_DUPLICATE_ID,
    SCENARIO_FORMAT_UNSUPPORTED,
    SCENARIO_INVALID,
    SCENARIO_PATH_ESCAPE,
    SCENARIO_ROOT_MISSING,
    SCENARIO_TOO_LARGE,
)
from .model import ALLOWED_BODY_SUFFIXES, MAX_PACK_BYTES, PACK_FORMAT, ScenarioPack

_PACK_FILE = "scenario.yaml"


@dataclass(frozen=True)
class ScenarioIssue:
    """一个坏包的一条诊断；绝不携带文件内容。"""

    source: str
    code: str
    message: str


@dataclass(frozen=True)
class LoadedScenario:
    """一个通过全部校验的场景包。"""

    pack: ScenarioPack
    root: Path


@dataclass(frozen=True)
class ScenarioCatalog:
    """一轮发现的稳定结果：包按 id 升序，问题按 (source, code, message) 升序。"""

    packs: Mapping[str, LoadedScenario]
    issues: tuple[ScenarioIssue, ...]


class ScenarioLoader:
    """按根目录顺序发现场景包；同 id 先到者赢。"""

    def __init__(self, roots: Sequence[Path]) -> None:
        self._roots: tuple[Path, ...] = tuple(roots)

    def discover(self) -> ScenarioCatalog:
        packs: dict[str, LoadedScenario] = {}
        issues: list[ScenarioIssue] = []
        for root in self._roots:
            self._discover_root(root, packs, issues)
        return ScenarioCatalog(
            packs=dict(sorted(packs.items())),
            issues=tuple(sorted(issues, key=lambda issue: (issue.source, issue.code, issue.message))),
        )

    def _discover_root(
        self, root: Path, packs: dict[str, LoadedScenario], issues: list[ScenarioIssue]
    ) -> None:
        if not root.is_dir():
            issues.append(ScenarioIssue(
                source=str(root), code=SCENARIO_ROOT_MISSING, message="场景根目录不存在或不是目录",
            ))
            return
        for entry in sorted(root.iterdir(), key=lambda path: path.name):
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            if entry.is_symlink():
                issues.append(ScenarioIssue(
                    source=entry.name, code=SCENARIO_PATH_ESCAPE,
                    message="包目录是符号链接，拒绝加载",
                ))
                continue
            if not entry.is_dir() or not (entry / _PACK_FILE).is_file():
                continue
            self._load_pack(entry, packs, issues)

    def _load_pack(
        self, pack_dir: Path, packs: dict[str, LoadedScenario], issues: list[ScenarioIssue]
    ) -> None:
        pack_issues: list[ScenarioIssue] = []
        self._check_size(pack_dir, pack_issues)
        if pack_issues:
            issues.extend(pack_issues)
            return
        raw = self._read_yaml(pack_dir / _PACK_FILE, pack_issues)
        if raw is None:
            issues.extend(pack_issues)
            return
        if not self._check_pack_format(raw, pack_issues):
            issues.extend(pack_issues)
            return
        pack = self._validate(raw, pack_issues)
        if pack is None:
            issues.extend(pack_issues)
            return
        self._check_bodies(pack, pack_dir, pack_issues)
        if pack_issues:
            issues.extend(pack_issues)
            return
        if pack.id in packs:
            issues.append(ScenarioIssue(
                source=pack_dir.name, code=SCENARIO_DUPLICATE_ID,
                message=f"scenario id {pack.id!r} 已由先前的根加载，丢弃后者",
            ))
            return
        packs[pack.id] = LoadedScenario(pack=pack, root=pack_dir.resolve())

    def _check_size(self, pack_dir: Path, pack_issues: list[ScenarioIssue]) -> None:
        total = 0
        for path in pack_dir.rglob("*"):
            # rglob 不递归目录符号链接；文件符号链接按 stat()（跟随链接）计入预算，
            # 否则包内链接可以指向外部大文件绕过 2 MiB 上限。
            if path.is_file():
                total += path.stat().st_size
        if total > MAX_PACK_BYTES:
            pack_issues.append(ScenarioIssue(
                source=pack_dir.name, code=SCENARIO_TOO_LARGE,
                message=f"包内文件总字节超过 {MAX_PACK_BYTES} 上限",
            ))

    def _read_yaml(self, pack_file: Path, pack_issues: list[ScenarioIssue]) -> dict[str, Any] | None:
        try:
            raw = yaml.safe_load(pack_file.read_text(encoding="utf-8"))
        # RecursionError：深层嵌套 YAML 会让 PyYAML 递归解析爆栈。它属于"坏包"，
        # 必须降级成 issue——否则一个坏文件能在启动扫描时直接崩掉服务。
        except (OSError, yaml.YAMLError, UnicodeDecodeError, RecursionError) as exc:
            pack_issues.append(ScenarioIssue(
                source=pack_file.parent.name, code=SCENARIO_INVALID,
                message=f"scenario.yaml 读取或解析失败：{type(exc).__name__}",
            ))
            return None
        if not isinstance(raw, dict):
            pack_issues.append(ScenarioIssue(
                source=pack_file.parent.name, code=SCENARIO_INVALID,
                message="scenario.yaml 顶层必须是映射",
            ))
            return None
        return raw

    def _check_pack_format(self, raw: dict[str, Any], pack_issues: list[ScenarioIssue]) -> bool:
        if "pack_format" not in raw:
            pack_issues.append(ScenarioIssue(
                source=_pack_source(raw), code=SCENARIO_INVALID, message="缺少 pack_format",
            ))
            return False
        declared = raw["pack_format"]
        if type(declared) is not int:
            pack_issues.append(ScenarioIssue(
                source=_pack_source(raw), code=SCENARIO_INVALID, message="pack_format 必须是整数",
            ))
            return False
        if declared > PACK_FORMAT:
            pack_issues.append(ScenarioIssue(
                source=_pack_source(raw), code=SCENARIO_FORMAT_UNSUPPORTED,
                message=f"pack_format {declared} 高于本应用支持的 {PACK_FORMAT}，格式过新",
            ))
            return False
        return True

    def _validate(self, raw: dict[str, Any], pack_issues: list[ScenarioIssue]) -> ScenarioPack | None:
        try:
            return ScenarioPack.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first["loc"]) or "<root>"
            pack_issues.append(ScenarioIssue(
                source=_pack_source(raw), code=SCENARIO_INVALID,
                message=f"{location}: {first['msg']}",
            ))
            return None

    def _check_bodies(
        self, pack: ScenarioPack, pack_dir: Path, pack_issues: list[ScenarioIssue]
    ) -> None:
        resolved_root = pack_dir.resolve()
        for profile_name in sorted(pack.profiles):
            routes = pack.profiles[profile_name].routes
            for route_key in sorted(routes):
                body = routes[route_key].body
                target = (pack_dir / body).resolve()
                relative = f"{pack_dir.name} [{profile_name}]{route_key}"
                if not target.is_relative_to(resolved_root):
                    pack_issues.append(ScenarioIssue(
                        source=pack_dir.name, code=SCENARIO_PATH_ESCAPE,
                        message=f"{relative} 的 body 解析后逃出包根",
                    ))
                    continue
                if not target.is_file():
                    pack_issues.append(ScenarioIssue(
                        source=pack_dir.name, code=SCENARIO_INVALID,
                        message=f"{relative} 的 body 不存在或不是文件",
                    ))
                    continue
                if target.suffix not in ALLOWED_BODY_SUFFIXES:
                    pack_issues.append(ScenarioIssue(
                        source=pack_dir.name, code=SCENARIO_INVALID,
                        message=f"{relative} 的 body 后缀不在允许集合",
                    ))


def _pack_source(raw: dict[str, Any]) -> str:
    """issue 的 source 只取包 id 声明；绝不携带文件内容。"""
    declared = raw.get("id")
    return declared if isinstance(declared, str) and declared else "<unnamed>"
