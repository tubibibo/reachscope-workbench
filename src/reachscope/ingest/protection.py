"""保护状态检测（PLAN §4.3 / §11 / TASKS T1.4）。

`apkid` 是**可选依赖**（§9.1）：未安装不阻断主流程，但必须在 stderr 写警告，
且 `Protection.detected` 用 `None`（“未检测”）而不是 `False`（“检测了，没命中”）。

强加固（整体 DEX 加密类 packer 命中）→ `analyzable=False`，主流程短路、退出码 3，
**不得**用空结果冒充“无问题”。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..ir.model import Protection

logger = logging.getLogger("reachscope.ingest.protection")

#: APKiD 标签的类别前缀（形如 `packer::dexguard`，见 fixture 08 的 protection.json）。
LABEL_SEPARATOR = "::"

#: 视为“强加固 / 整体 DEX 加密”的类别与已知加固名，命中即 `analyzable=False`。
STRONG_CATEGORIES = {"packer"}
STRONG_LABELS = {
    "bangcle",
    "secneo",
    "ijiami",
    "qihoo",
    "tencent",
    "baidu",
    "netease",
    "aliprotect",
    "secapp",
    "naga",
    "nqshield",
    "dexguard",
}


def detect_protection(apk_path: str | Path, *, no_apkid: bool = False) -> Protection:
    """检测 APK 的加固/混淆状态。

    三分支：
    1. `--no-apkid` → `detected=False, analyzable=True`（明确“跳过”）
    2. apkid 不可用 → stderr 警告 + `detected=None, analyzable=True`（明确“未检测”）
    3. apkid 命中强加固 → `analyzable=False`（主流程短路，退出码 3）
    """
    if no_apkid:
        logger.info("--no-apkid：跳过加固检测")
        return Protection(
            detected=False, tool=None, labels=[], analyzable=True,
            warnings=["protection: skipped by --no-apkid"],
        )

    labels = _run_apkid(Path(apk_path))
    if labels is None:
        message = "apkid 未安装或调用失败，无法判定保护状态（detected=None）"
        logger.warning(message)
        return Protection(
            detected=None, tool=None, labels=[], analyzable=True,
            warnings=[message],
        )

    detected = bool(labels)
    strong = is_strong_protection(labels)
    warnings: list[str] = []
    if strong:
        message = f"检测到强加固：{', '.join(labels)}，后续分析将跳过（退出码 3）"
        logger.warning(message)
        warnings.append(message)
    else:
        logger.info("保护状态：detected=%s labels=%s", detected, labels or "无")
    return Protection(
        detected=detected,
        tool="apkid" if detected else None,
        labels=labels,
        analyzable=not strong,
        warnings=warnings,
    )


def is_strong_protection(labels: list[str]) -> bool:
    """判断标签集合是否命中“强加固 / 整体 DEX 加密”。"""
    lowered = {label.strip().lower() for label in labels if label.strip()}
    for label in lowered:
        category, _, value = label.partition(LABEL_SEPARATOR)
        if category in STRONG_CATEGORIES and (not value or value in STRONG_LABELS):
            return True
        if value in STRONG_LABELS or label in STRONG_LABELS:
            return True
    return False


def _run_apkid(apk_path: Path) -> list[str] | None:
    """调用 apkid 扫描，返回去重排序的标签列表；apkid 不可用返回 None。

    APKiD 2.x 的 Python API 见其文档；调用失败按“不可用”处理（警告 + 短路），
    绝不让可选依赖把主流程炸掉。
    """
    try:
        from apkid import apkid as apkid_mod
    except ImportError:
        return None

    # “apkid 不可用”由调用方在 detect_protection 统一记 warning；这里只负责返回 None。
    try:
        with apk_path.open("rb") as handle:
            result = apkid_mod.APKID(handle).scan()
    except Exception as exc:  # noqa: BLE001 —— 可选依赖的任何失败都按“不可用”处理
        logger.warning("apkid 调用失败：%s", exc)
        return None

    labels: set[str] = set()
    files = result.get("files") or [] if isinstance(result, dict) else []
    for file_entry in files:
        matches = file_entry.get("matches") or {}
        for category, found in matches.items():
            for item in found:
                labels.add(f"{category}{LABEL_SEPARATOR}{item}")
    return sorted(labels)
