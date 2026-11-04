"""从 apktool 解码产物到 `Report` 的分析管线（T4.3）。

只负责**编排**，每步的能力都在既有模块里：

```
parse_manifest → build_index → resolve_components → 深链/WebView/桥/来源/汇点
→ build_chains → build_evidence → Report
```

不做 I/O（解码由 `ingest.apk` 负责，报告落盘由 `report` 层负责），
因此同一目录两次调用除 `analyzed_at` 外结果逐字段相同（§9.3）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .._version import __version__
from ..extract.bridge import extract_bridges
from ..extract.components import resolve_components
from ..extract.deeplinks import extract_deeplinks
from ..extract.origin import attach_origin_checks, collect_origin_checks
from ..extract.sinks import attach_bridge_sinks
from ..extract.webview import extract_webviews
from ..ingest.apk import MANIFEST_RELPATH, IngestError
from ..ingest.manifest import parse_manifest
from ..ingest.smali import build_index
from ..ir.model import Meta, Protection, Report
from ..ir.validation import IRValidationError
from .chains import build_chains
from .evidence import build_evidence


def analyze_workdir(
    workdir: str | Path,
    *,
    protection: Protection | None = None,
    apk_path: str = "",
    apk_sha256: str = "",
    apktool_version: str | None = None,
    analyzed_at: str | None = None,
) -> Report:
    """分析一个已经由 apktool 解码好的目录，返回完整 `Report`。

    `protection.analyzable=False` 时直接返回空报告（带 protection 与 meta），
    不去解析可能被加固过的产物 —— 与 CLI 的短路语义一致（PLAN §4.3）。
    """
    protection = protection if protection is not None else Protection()
    timestamp = analyzed_at or datetime.now(UTC).isoformat(timespec="seconds")
    root = Path(workdir)

    if not protection.analyzable:
        return Report(
            meta=Meta(
                apk_path=apk_path,
                apk_sha256=apk_sha256,
                analyzed_at=timestamp,
                tool_version=__version__,
                apktool_version=apktool_version,
                warnings=list(protection.warnings),
            ),
            protection=protection,
        )

    manifest = parse_manifest(root / MANIFEST_RELPATH)
    index = build_index(root)
    components = resolve_components(manifest, index)
    deeplinks = extract_deeplinks(components, manifest.package)
    webviews = extract_webviews(index)
    bridge_warnings: list[str] = []
    bridges = extract_bridges(index, bridge_warnings)
    bridges = attach_origin_checks(bridges, collect_origin_checks(index))
    bridges = attach_bridge_sinks(bridges, index, package=manifest.package)
    chains = build_chains(components, index, bridges, webviews, manifest)
    try:
        chains, findings, counter_examples = build_evidence(
            components, manifest, index, bridges, webviews, chains
        )
    except IRValidationError as exc:
        raise IngestError("ambiguous analysis identifiers", "Analysis has ambiguous local identifiers; no report was generated") from exc

    return Report(
        meta=Meta(
            apk_path=apk_path,
            apk_sha256=apk_sha256,
            package=manifest.package,
            version_name=manifest.version_name,
            version_code=manifest.version_code,
            target_sdk=manifest.target_sdk,
            min_sdk=manifest.min_sdk,
            analyzed_at=timestamp,
            tool_version=__version__,
            apktool_version=apktool_version,
            warnings=[
                *protection.warnings,
                *manifest.warnings,
                *index.warnings,
                *bridge_warnings,
            ],
        ),
        protection=protection,
        components=components,
        deeplinks=deeplinks,
        webviews=webviews,
        bridges=bridges,
        chains=chains,
        findings=findings,
        counter_examples=counter_examples,
    )


__all__ = ["analyze_workdir"]
