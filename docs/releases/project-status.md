# Project status

> 公开源码说明：文中的历史提交号属于公开导出前的开发记录；本副本不携带该私有 Git 历史。提交号仅用于来源标识，不代表新仓库中存在对应提交。

Updated: 2026-11-06. Current source and live local service: **0.15.0**.
Workspace schema remains **7**. Local entry: `http://127.0.0.1:8765/`.

## 0.15.0 — Scenario packs

Teaching scenarios became data: a `scenario.yaml` plus static pages, loaded from
built-in roots (`missing-headers`, `cookie-flags`, `csrf-token`) or repeatable
`--scenarios-dir` roots. New `GET /api/lab/scenarios`; `POST /api/lab/start` accepts
an optional `scenario_id`. Lab provenance records `scenario_id` additively —
**workspace schema remains 7**, no migration. Validation refuses path escapes,
symlinks, oversize packs and unknown fields; bad packs surface as issues without
taking the service down.

## Security patch

The 0.14.1 security acceptance below records the frozen security delivery at
`ceb525a`. A subsequent repository-only layout refactor keeps version/API/schema
unchanged; its separate verification is recorded under "Repository layout" below.

The operator requested a comprehensive project security test, fixes and a dedicated
log. See [the security log](../security/security-test-log-2026-11-02.md) for scope, prerequisites, reproduced
before/after behavior, exact remaining dependency risk and operational retries.

Nine confirmed issues are fixed (eight Medium, one Low), with two additional Low
hardening items. These cover credential draft destination, reviewed-hash consent,
case decision concurrency, cloud sensitive/unknown metadata, manifest ambiguity,
bounded decoder output, report identity ambiguity and log display controls.
No RCE, privilege escalation or real credential exposure is claimed.

A minimatch development-toolchain advisory remains OPEN (one advisory propagated
through three moderate dependency nodes); production npm and actual runtime Python
audits are separate. No incompatible forced override or blanket suppression was
used to obtain a zero-warning result. Bandit retains all 41 raw alerts with manual
triage; its ratings are not the product's vulnerability findings.

## Executed verification

- Complete source gate: **2,033 passed, 5 skipped, 1 existing upstream warning**,
  **188.35s**, **92.43%** coverage. Ruff and strict mypy **129 source files** passed.
- New Python security tests: **55**, already included in the source total.
- Exact complete browser orchestrator: **eight groups, 76 checks passed**, including
  seven new frontend security checks. Fixed local fixture protocols are separate
  from commercial provider acceptance. TypeScript, Prettier, build and actual
  OpenAPI/request-contract generation/check passed.
- A genuinely new external environment installed the final wheel: `python -I`
  import/version, `pip check`, five installed fail-closed security checks, all four
  modules, collector/v2-unknown/cases/cloud/teaching smoke and actual loopback HTTP
  static/collector source-and-license checks passed.
- **157 runtime files, 129 Python files**, README/license metadata and final assets
  match the clean frozen source. JS `index-BXXmnpWf.js`, CSS `index-BVwddzM5.css`.
  Wheel **595,201 bytes**, SHA-256
  `c991473699178f3e2d34d1903aa78b467f326dc526230c8715b85d2530fdeb58`.
- Runtime Python closure: 21 packages audited, no known advisory or skipped package.
  Fresh installation changed anyio; its actual 21-package set was independently
  audited too. This does not establish safety for all historical versions allowed
  by broad version constraints or unknown future advisories.

## Existing workspace preservation

The exact owning idle service was checked before stopping. The first full-file
backup attempt exceeded the Windows destination path limit; its incomplete copy
was not accepted. A brief idle candidate start was stopped, a short private path
was used, and all 17 tables were verified equal to the initial pre-update SQLite
copy. A complete SQLite backup and all **139 job/upload files** were hash-verified
before the final 0.14.1 start. The retry is retained, not rewritten as first-pass
success; see workspace-backup-reference.json in the local delivery proofs.

The final workspace retains **165 jobs, 91 assets, 12 cases, four AI reports and
25 uploads**. No release demo records or malicious fixtures were inserted there.
Only the previously authorized matching AI key was restored to backend memory;
its saved profile revision token rotates by design while other profile fields
remain equal. No provider/model request was made, and the key is absent from the
current tracked files and database. Live JS/CSS bytes match the final wheel.

## Product scope and deferred work

The modular local Android/Web/cloud/host workbench and existing evidence/case
workflow remain. Host projected input v2 and old input v1 keep their existing
versioned semantics; ambiguous legacy report identities now fail closed instead
of silently binding evidence to the wrong object. Normal historical IDs and
reports remain compatible; ambiguous old files are not automatically rewritten.

The operator explicitly paused Linux work. Its prior actual-binary acceptance
remains unexecuted; four Linux-specific skips and one Windows symlink-permission
skip are not counted as passes. No actual target APK/JAR, Android runtime,
commercial AI inference, third-party target scanning, production multi-user SOC
or remote GitHub CI execution is included in this acceptance.

GitHub blue-team report integrations remain research only; none was added by this
security patch. The 0.14 scope remains the independent host collector and its existing review workflow.
Detailed record: [security log](../security/security-test-log-2026-11-02.md) and
[validation](validation/workbench.md). Local security proof directory: outputs/workbench-0.14.1.

## Repository layout

The subsequent directory-only refactor keeps version 0.14.1 and schema 7. It moves
95 tracked paths into documented responsibility groups, archives local outputs
without deleting evidence, and centralizes new tool caches. Private state and
legacy data stay in place. See the [layout review](reviews/workbench-0-11-to-0-14.md)
and [repository rules](../development/repository-layout.md).

Its own source gate completed with **2,033 passed, 5 skipped, 1 existing upstream
warning, 92.44% coverage, 211.57s**; strict mypy still covers 129 source files.
TypeScript, formatting, contract generation/check and production build passed.
After correcting five renamed sibling imports, the complete eight-group browser
gate passed all 76 checks. The initial failure is retained separately. Final JS/CSS
bytes are unchanged from the security release. Tool-only follow-up checks passed;
the same tests are not counted twice. Independent installed-wheel and sdist proof
is kept separately in outputs/repository-layout-2026-11-02/package-acceptance.json.
