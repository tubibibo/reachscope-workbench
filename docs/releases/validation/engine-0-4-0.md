# Validation record — 0.4.0

> 历史记录：正文中的实际执行命令、版本、哈希和证据路径保留当时原样。当前目录与命令见 [仓库结构规范](../../development/repository-layout.md)；路径迁移表见 [path-migrations.json](../../../config/path-migrations.json)。

Observed locally on 2026-11-01 (Asia/Shanghai), Windows, CPython 3.13.15.

## Source checks

`python scripts/check.py` passed:

- ruff: all checks passed.
- mypy: no issues in 47 source files, strict mode.
- pytest: **685 passed, 1 skipped**, coverage **92.30%** (85% required).
- The skipped case requires creating a symbolic link; this Windows session did
  not have that permission. Traversal, corruption and other path checks ran.

Tests include the inherited analysis regressions plus persistent-source identity,
multi-object report normalization, source tampering, invalid schema, path handling,
budgets, concurrent artifact publication, pagination, protocol semantics and
end-to-end query workflows. No model was used to score its own answers. Windows extended-length paths were
exercised with real >260-character paths and Kotlin-style filenames.

## Packaging and installed use

`python -m build` produced a wheel and source distribution. The wheel was installed
in a fresh venv and executed outside the checkout, with `python -I` to exclude the
source tree and user site-packages. The built wheel includes both templates, the
sample catalogue, synthetic Manifest/smali files and license/provenance notices.
The source distribution includes tests, fixtures and the check script. Neither
contains APKs or decoded private scan output.

The installed `doctor` and `demo` commands passed. An installed-wheel test also
created, reopened and read code under a >260-character Windows evidence path. The walkthrough produced five
passing cases, real query/claim traces and source method reads with zero model
calls. Refusing nonempty demo/scan outputs prevents stale evidence from being
mixed with a new run.

## APK pipeline

A locally available synthetic control APK was scanned using Java and Apktool
2.11.1 through the installed wheel. It produced one legacy risk finding. After
the decoder's temporary directory was removed, a fresh CLI invocation reopened
the artifact and returned the bridge's `readFile` method, source hash and physical
line range. The scan used `--no-apkid`; its protection-check omission remains an
explicit warning, rather than an assertion that the APK was unprotected.

A second integration check indexed an existing decoded OVAA sample containing
**7,909 source files and 54,014 methods**. It retained three candidate paths and
zero legacy risk findings. The final installed wheel reopened that artifact and
read the target WebView method with both `getStringExtra` and `loadUrl`. Long
Kotlin filenames were preserved even when their full evidence paths exceeded
260 characters. The snapshot included `apktool.yml` so SDK metadata was retained.

On this machine, snapshotting took 72.53 seconds, analysis 145.84 seconds and
artifact storage 191.67 seconds (**410.04 seconds total**). A subsequent open plus
several Python-session queries took **8.05 seconds**. This exposes the remaining
first-run I/O/indexing cost; it is not a claim of general throughput. This report
contained **2,199 warnings**, and its claim check correctly returned
`UNDECIDABLE / OUTSIDE_COVERAGE` while keeping the candidate-path evidence visible.
The check does not turn a parser's warning-filled result into a verified exploit.
No copy of that APK or its decoded code is included in this release.

## Visual walkthrough

The generated HTML was rendered in headless Microsoft Edge using Playwright.
Desktop 1280×960 and mobile 390×844 had five cards, correct 5/5 metrics, working
disclosures, no horizontal overflow and no page-script errors. Target snippets
are escaped; the page uses no external scripts, fonts or services.

## Small-file profiling

An agent measured 1,001 synthetic source files (110,919 bytes) on this Windows
environment. Before removing redundant metadata checks and oversized read
allocations, artifact open took about 31–36 seconds; afterwards it took
1.36–1.40 seconds. Creation improved from about 85.8 to 17.2 seconds. Source
hashing and per-method revalidation remained enabled. This is a local profiling
sample, not a general throughput benchmark. Creation still pays for small-file
copies and an extra indexing pass.

## Unverified claims deliberately excluded

The Windows/Linux Python 3.11/3.13 GitHub Actions matrix is configured, but no
remote GitHub run is claimed here. Real-world vulnerability precision/recall and
the benefit to an actual AI model have not been measured for 0.4. No public GitHub
or package-index release was performed as part of this local delivery.
