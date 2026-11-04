"""APK 输入与 apktool 调用层。

对外只暴露：:class:`IngestError`、:class:`ApkInput`、:class:`WorkDir`、
:func:`resolve_apktool`、:func:`check_apktool_version`、:func:`run_apktool`。

不联网、不执行目标 APK（只调用 apktool 解码，不安装/运行）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType

from ..exitcodes import ExitCode
from .bounded_process import CommandLimitError, run_bounded

logger = logging.getLogger("reachscope.ingest.apk")

#: PLAN §11：apktool 最低版本，低于只警告不阻断。
MIN_APKTOOL_VERSION = (2, 9, 0)

#: apktool 默认超时（秒），PLAN §9.2。
DEFAULT_TIMEOUT = 300

#: 版本检查的超时（秒），远小于解码超时。
VERSION_TIMEOUT = 30

#: 环境变量：指向 apktool jar（PLAN §9.1 / TASKS T1.1）。
APKTOOL_JAR_ENV = "APKTOOL_JAR"

#: APK 必须包含的 zip 条目（D-017）。
MANIFEST_ENTRY = "AndroidManifest.xml"

#: apktool 解码后的产物布局（PLAN §5.1）。
MANIFEST_RELPATH = "AndroidManifest.xml"
SMALI_DIR_PREFIX = "smali"

_CHUNK_SIZE = 1 << 20
MAX_APK_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100_000
MAX_ARCHIVE_PATH_NODES = 200_000


class IngestError(Exception):
    """结构化的输入错误。

    `reason` 用英文规范取值（便于断言与 `expected.json` 对齐），
    `detail` 放人类可读的补充信息，CLI 只负责把 `exit_code` 映射成进程退出码。
    """

    def __init__(
        self,
        reason: str,
        detail: str = "",
        exit_code: ExitCode = ExitCode.INPUT_ERROR,
    ) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.exit_code = exit_code

    def to_message(self) -> str:
        """给 CLI 用的一行错误信息。"""
        return f"{self.reason} — {self.detail}" if self.detail else self.reason


@dataclass(frozen=True)
class ApkInput:
    """校验通过的 APK 输入。"""

    path: Path
    sha256: str
    size: int

    @classmethod
    def load(cls, path: str | Path) -> ApkInput:
        """校验并计算摘要。任一步失败抛 :class:`IngestError`（退出码 2）。"""
        apk_path = Path(path)

        if not apk_path.exists():
            raise IngestError("file not found", str(apk_path))
        if not apk_path.is_file():
            raise IngestError("not a regular file", str(apk_path))
        if apk_path.stat().st_size > MAX_APK_BYTES:
            raise IngestError("input limit", "APK exceeds the 256 MiB input budget")
        if not zipfile.is_zipfile(apk_path):
            raise IngestError("not a zip archive", str(apk_path))
        _require_manifest(apk_path)

        return cls(path=apk_path, sha256=_sha256(apk_path), size=apk_path.stat().st_size)

    @property
    def name(self) -> str:
        """文件名，用于日志。"""
        return self.path.name


def _require_manifest(apk_path: Path) -> None:
    """zip 条目里必须有 `AndroidManifest.xml`，否则不是 APK（D-017）。"""
    try:
        with zipfile.ZipFile(apk_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise IngestError("input limit", "Too many APK archive entries")
            if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise IngestError("input limit", "APK expanded size exceeds the 512 MiB budget")
            seen: set[str] = set()
            portable_names: dict[tuple[int, str], tuple[str, int, bool]] = {}
            for entry in entries:
                # ZipInfo.filename normalizes backslashes on Windows. Inspect the
                # original central-directory name before platform normalization.
                name = entry.orig_filename.rstrip("/")
                path = PurePosixPath(name)
                parts = name.split("/")
                if (
                    not name or len(name) > 4096 or len(parts) > 64 or "\x00" in name or "\\" in name or ":" in name or path.is_absolute()
                    or ".." in path.parts or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.flag_bits & 1
                    or any(part in {"", ".", ".."} or part.rstrip(" .") != part
                           or any(ord(char) < 32 or ord(char) == 127 or char in '<>"|?*' for char in part)
                           or re.fullmatch(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])",
                                           part.split(".")[0], re.IGNORECASE) for part in parts)
                ):
                    raise IngestError("unsafe archive entry", entry.filename)
                # A portable decoder cannot safely preserve two ZIP paths that
                # collapse onto the same case-insensitive Windows destination.
                parent = 0
                for index, part in enumerate(parts):
                    alias = (parent, part.casefold())
                    directory = index < len(parts) - 1 or entry.is_dir()
                    existing = portable_names.get(alias)
                    if existing is not None:
                        if existing[0] != part or existing[2] != directory:
                            raise IngestError("unsafe archive entry", "Archive paths have platform-dependent aliases")
                        parent = existing[1]
                    else:
                        if len(portable_names) >= MAX_ARCHIVE_PATH_NODES:
                            raise IngestError("input limit", "APK archive path structure exceeds its node budget")
                        parent = len(portable_names) + 1
                        portable_names[alias] = (part, parent, directory)
                if name in seen:
                    raise IngestError("duplicate archive entry", name)
                seen.add(name)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        raise IngestError("not a zip archive", f"{apk_path} ({exc})") from exc
    if MANIFEST_ENTRY not in names:
        raise IngestError(
            f"missing {MANIFEST_ENTRY} in archive",
            f"{apk_path}（共 {len(names)} 个条目）不是 APK",
        )


def _sha256(path: Path) -> str:
    """分块计算 sha256，避免大 APK 占用过多内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WorkDir:
    """apktool 工作目录：`tempfile.mkdtemp()` 创建，退出时清理（PLAN §5.1）。"""

    def __init__(self, keep: bool = False, prefix: str = "reachscope-") -> None:
        self._keep = keep
        self._prefix = prefix
        self._path: Path | None = None

    @property
    def path(self) -> Path:
        """当前工作目录；进入上下文后才可用。"""
        if self._path is None:
            raise RuntimeError("WorkDir 尚未创建，请先进入 with 块")
        return self._path

    def __enter__(self) -> Path:
        self._path = Path(tempfile.mkdtemp(prefix=self._prefix))
        logger.info("工作目录：%s", self._path)
        return self._path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._path is None:
            return
        if self._keep:
            logger.info("--keep-workdir：保留工作目录 %s", self._path)
            return
        shutil.rmtree(self._path, ignore_errors=True)
        logger.debug("已清理工作目录：%s", self._path)


def resolve_apktool(explicit: str | None = None) -> list[str]:
    """确定 apktool 的调用命令。

    优先级：`--apktool` 参数 > 环境变量 `APKTOOL_JAR` > PATH 中的 `apktool`。
    """
    if explicit:
        return ["java", "-jar", explicit] if explicit.lower().endswith(".jar") else [explicit]

    jar = _env(APKTOOL_JAR_ENV)
    if jar:
        return ["java", "-jar", jar]

    found = shutil.which("apktool")
    if found:
        return [found]

    raise IngestError(
        "apktool not found",
        f"请安装 apktool ≥ {_version_text(MIN_APKTOOL_VERSION)}，或用 --apktool / {APKTOOL_JAR_ENV} 指定",
    )


def check_apktool_version(base: list[str], timeout: float = VERSION_TIMEOUT) -> str | None:
    """检查 apktool 版本；低于最低版本或解析失败只写 warning，不阻断。"""
    try:
        completed = run_bounded([*base, "-version"], timeout=timeout)
    except CommandLimitError as exc:
        if str(exc) == "output_limit":
            raise IngestError("apktool output limit", "Version diagnostics exceeded the bounded output budget") from None
        logger.warning("无法获取 apktool 版本：%s", str(exc))
        return None
    except OSError as exc:
        logger.warning("无法获取 apktool 版本：%s", exc)
        return None

    raw = f"{completed.stdout or ''}{completed.stderr or ''}"
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    if match is None:
        logger.warning("无法解析 apktool 版本输出：%s", raw.strip()[:200])
        return None

    version = tuple(int(group) for group in match.groups())
    text = match.group(0)
    if version < MIN_APKTOOL_VERSION:
        logger.warning(
            "apktool 版本 %s 低于要求的 %s，解码结果可能不一致",
            text,
            _version_text(MIN_APKTOOL_VERSION),
        )
    return text


def run_apktool(
    apk: ApkInput | str | Path,
    workdir: str | Path,
    *,
    apktool: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """解码 APK 到 `workdir`，返回工作目录。

    失败（apktool 缺失 / 返回码非 0 / 超时）一律抛 :class:`IngestError`，不静默降级。
    """
    base = resolve_apktool(apktool)
    check_apktool_version(base)
    workdir_path = Path(workdir)
    cmd = [*base, "d", "-f", "-o", str(workdir_path), str(_apk_path(apk))]
    logger.info("运行 apktool：%s", " ".join(cmd))

    try:
        completed = run_bounded(cmd, timeout=timeout)
    except CommandLimitError as exc:
        if str(exc) == "output_limit":
            raise IngestError("apktool output limit", "Decoder diagnostics exceeded the bounded output budget") from None
        if str(exc) == "timeout":
            raise IngestError("apktool timeout", f"超过 {timeout}s 已终止") from None
        raise IngestError("apktool failed", "Decoder diagnostic stream could not be read") from None
    except OSError:
        raise IngestError("apktool failed", "Unable to start the configured decoder") from None

    if completed.returncode != 0:
        raise IngestError(
            "apktool failed",
            f"returncode={completed.returncode} {_tail(completed.stderr or completed.stdout)}",
        )
    return workdir_path


def manifest_path(workdir: str | Path) -> Path:
    """解码后的 manifest 路径（PLAN §5.1）。"""
    return Path(workdir) / MANIFEST_RELPATH


def smali_dirs(workdir: str | Path) -> list[Path]:
    """解码后的 smali 目录列表：`smali/`、`smali_classes2/` …，稳定排序。"""
    root = Path(workdir)
    dirs = [path for path in root.glob(f"{SMALI_DIR_PREFIX}*") if path.is_dir()]
    return sorted(dirs, key=lambda path: (len(path.name), path.name))


def _apk_path(apk: ApkInput | str | Path) -> Path:
    """取 APK 路径，兼容 `ApkInput` 与裸路径。"""
    if isinstance(apk, ApkInput):
        return apk.path
    return Path(apk)


def _env(name: str) -> str | None:
    """读环境变量，空串视为未设置。"""
    value = os.environ.get(name)
    return value or None


def _tail(text: str, limit: int = 500) -> str:
    """取尾部片段，避免日志/错误过长。"""
    return text.strip()[-limit:]


def _version_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)
