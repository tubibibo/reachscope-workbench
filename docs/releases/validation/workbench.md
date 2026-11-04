# Workbench validation

> 发布脱敏说明：本副本将机器目录前缀和个人用户目录替换为占位符。其余历史版本、测试结果与证据说明保持原样，未将历史验收视为 2026-11-04 重新执行的结果。

> 历史记录：正文中的实际执行命令、版本、哈希和证据路径保留当时原样。当前目录与命令见 [仓库结构规范](../../development/repository-layout.md)；路径迁移表见 [path-migrations.json](../../../config/path-migrations.json)。

## Workbench 0.14.1 security patch — 2026-11-02

- Complete `python scripts/check.py`: **2,033 passed, 5 skipped, 1 existing upstream
  warning**, **92.43%** coverage, **188.35s**. Ruff and strict mypy **129 files** pass.
  New `tests/security` 55 tests are included, not added again to the total.
- Exact final browser orchestrator passes **8 groups / 76 checks**: onboarding12,
  teaching15, Android9, Web/cloud8, host9, host-journey8, frontend-security7,
  AI-protocol8. Actual OpenAPI drift, full Prettier, TypeScript and build pass.
- Security fixtures demonstrate before/after for credential destination, refreshed
  consent hash, concurrent case decisions, ambiguous file metadata and bounded
  decoder diagnostics. Scope/SSRF/redirect/HTML controls that passed are not counted
  as new vulnerabilities. See the dedicated security test log for precise limits.
- Final clean-export wheel **595,201 bytes**, SHA-256
  `c991473699178f3e2d34d1903aa78b467f326dc526230c8715b85d2530fdeb58`,
  build tree `1b9b20a35388ab998073c0120a0237b24bbf27b3`.
  **157 runtime / 129 Python files**, metadata/licenses and final assets match.
- New outside-checkout environment: isolated imports/version, pip check, five
  installed fail-closed guards, copied four-module/collector/v2/case/teaching smoke,
  plus separately served TCP HTML/JS/CSS/collector bytes all pass. Runtime anyio
  changed in the fresh install, so its actual 21 runtime dependencies were audited
  separately: zero known advisories/skips. No real APK/JAR was executed.
- npm production audit zero; one unresolved minimatch advisory appears as three
  moderate development nodes. Bandit retained and triaged 41 raw alerts, with zero
  parse errors. Toolchain advisory remains OPEN; no scanner zero-warning claim.
- Workspace update kept schema7 and verified 17 original tables, 139 artifact files;
  165 jobs,91 assets,12 cases,4 AI reports,25 uploads. Long backup paths caused one
  incomplete attempt and a brief candidate start; after stopping it, a complete
  short-path backup/hash check matched the original pre-update SQLite rows before
  final start. No demo/security-test records were seeded into the real workspace.
- Five source skips remain explicit (four Linux, one Windows symlink permission).
  Linux is paused. No commercial inference, external target scanning or remote CI.

## Workbench 0.14.0 — 2026-11-02

- Complete `python scripts/check.py`: **1,978 passed, 5 skipped, 1 existing upstream
  warning**, **92.33%** coverage, **179.88s**. Ruff and strict mypy **126 files** pass.
  Four skips require Linux process/permission/symlink behavior; one existing skip
  depends on Windows symlink permission. No skipped check is counted as passed.
- Actual OpenAPI generation/check, full frontend Prettier, TypeScript and production
  build pass. Final assets: `index-DJ_rqD-K.js` / `index-BVwddzM5.css`.
- The exact complete `scripts/browser_checks.py` passes seven isolated groups:
  onboarding 12, teaching 15, Android 9, Web/cloud 8, host 9, host journey 8 and AI
  protocol 8 (**69 total**). Each group uses a private workspace/local fixtures.
  Journey tests include delayed replies after real case creation, stopping wait,
  retaining the same idempotency key, exactly one case, failure/unknown handling,
  incompatible old/new input formats and a human-approved comparable closure.
- Final wheel **590,993 bytes**, SHA-256
  `243793183c8e5c8a3bbb07674f52e959562fa9af7896e64011cfccb540a2a3c8`;
  clean source tree `3d17a7124e18edaed7a94391bd3e3c95ca528c3b`.
  All **154 runtime files / 126 Python files**, README and license metadata,
  collector license and final assets match. The license-aware copied smoke harness
  had a pre-build exact ZIP-entry assertion corrected from six to seven; no product
  runtime changed afterward. Its final targeted Ruff check passes.
- A newly created outside-checkout environment passes `python -I` imports/version,
  `pip check` and the copied installed smoke: four modules, collector/source
  downloads and digests, independent pyz plan with no snapshot/job, actual v2
  failed-capture upload remaining unknown, original host/cloud cases and teaching.
  A separate installed server passes actual loopback HTML/JS/CSS byte checks and
  licensed collector source checks. These do not execute Linux system commands.
- Real existing workspace was backed up while its verified owning process was
  idle/stopped. All 17 tables and 139 artifact files match across 0.13 -> 0.14;
  schema remains **7**. Before update: 165 jobs, 91 assets, 12 cases, four AI reports,
  25 uploads. Authorized same-profile key reload rotates only its revision token;
  the secret remains absent from the database and repository. No records are seeded.
  Read-only live desktop/mobile preparation/result inspection also passes.
- **Actual Linux binary acceptance is NOT executed.** Docker Linux daemon is not
  available; WSL has no Linux distribution and VirtualBox has no running guest.
  The prerequisite-aware `scripts/verify_host_linux.py --required` returns **2**
  and `actual_linux_acceptance:false`. An unrelated unidentified VMware process
  was not used. The harness documents a controlled disposable-container protocol;
  mocks and Windows tests never establish real sshd/nginx, 0600 or dirfd acceptance.
- No commercial inference or remote GitHub CI execution. Existing local protocol
  fixtures remain distinct from account/model/billing tests. No remote command,
  automatic upload, configuration change or remediation operation is introduced.

## Workbench 0.13.0 — 2026-11-02

- Final complete source gate, recorded in `work-013-release-check.log`:
  **1,835 passed, 1 skipped, 1 upstream warning**, **92.54%** coverage,
  pytest **194.27s**. Ruff and strict mypy **118 source files** pass.
- Final host component run: **200 passed in 2.23s**, comprising baseline 105,
  log analysis 57 and independent boundaries 38. These tests overlap the complete
  source gate and are not added to its total. Earlier isolated component coverage
  figures do not represent current full-repository coverage.
- The isolated browser orchestrator in
  `outputs/workbench-0.13/browser-gate/browser-gate.json` passes **six groups,
  61 checks**. This aggregate run occurred **before** the late Nginx truncated-fact
  retention correction. The affected blue-team UI group was then rerun against
  the correction and passes **9/9**, recorded in
  `outputs/workbench-0.13/blue-ui-release/blue-ui-validation.json`. The final
  affected-group rerun is not a claim that all six groups were rerun afterward.
  It covers uploaded baseline/log inputs, preview without job creation, actual
  selected scope, evidence/guidance, privacy, unknown year/timezone and manual
  revised-file case resolution, with zero model requests or browser errors.
- Corrected final wheel: `reachscope_workbench-0.13.0-py3-none-any.whl`,
  **571,545 bytes**, SHA-256
  `ca8f2bb02f3d351b30e03d5cdeab8e76fafba4c874382c429a521b7a566e0807`.
  Its **145 runtime files**, including **118 Python files**, match the clean
  source export. Current assets are `index-DOhXZtvr.js` / `index-CC9jvJG5.css`.
- A fresh environment outside the checkout passes isolated version/import-path
  checks and the corrected wheel's installed smoke: four modules, real uploaded
  controlled host baseline -> preview -> SSH-only run -> explicit revised-file
  relation -> comparable assessment -> human closure -> immutable baseline;
  access/auth `.log` uploads retain privacy and unknown year/timezone. Existing
  cloud remediation and managed loopback teaching workflows remain covered.
  Actual loopback HTTP responses serve the installed JS/CSS bytes correctly.
  These are controlled fixtures; no remote host commands or deployment claims.
- The earlier candidate package is retained separately under
  `validation/candidate-1-before-facts-fix/` and explicitly predates the final
  correction. Final package proof is
  `outputs/workbench-0.13/validation/PACKAGE-ACCEPTANCE.json`; prior candidate
  acceptance is not relabeled as corrected final-wheel acceptance.
- Schema **7** gates the new host semantics. Independent true-v6 fixtures retain
  original rows/JSON/provenance/idempotency, cases/audit and failed AI history;
  future schema 8 is rejected before database-byte or journal changes. Actual
  user-workspace backup, ownership, upgrade and server state are recorded
  separately in PROJECT-STATUS.md, not inferred from these fixtures.
- Real commercial inference remains deferred; no new commercial model request
  or remote GitHub CI execution is claimed. The existing local protocol fixtures
  are distinct from commercial account, model-quality or billing acceptance.
  Real Linux/Nginx service loading, endpoint agents, continuous monitoring,
  field detection/false-positive rates and production multi-user operation remain
  outside this executed acceptance.

## Workbench 0.12.0 — 2026-11-02

- Complete `scripts/check.py`: **1,614 passed, 1 skipped, 1 upstream warning**,
  **92.31%** coverage, pytest **158.63s**. Ruff and strict mypy **111 files** pass.
- Frontend types, full Prettier, build and actual OpenAPI request-contract check
  pass. Final assets: `index-D9xlx_5N.js` / `index-BfJnNPGJ.css`.
- Exact final `scripts/browser_checks.py` passes all five groups: onboarding 12,
  teaching/guides/models 15, Android 9, Web/cloud 8 and AI protocol 8 (**52** total).
  Groups use private workspaces/random ports/local fixtures; no commercial call.
  Android/cloud flows make zero model submissions. Desktop/mobile screenshots viewed.
- Retained failed prior browser gate: one `ERR_NO_BUFFER_SPACE` console event in
  Web/cloud. A standalone group rerun and subsequent complete orchestrator pass
  with browser-error assertions unchanged. Do not erase or count the failed run
  as passing. Separate existing asset-wizard regression passes six checks.
- Actual compiled unsigned synthetic APK acceptance passes manifest-only selected
  execution, revised same-package APK linkage, comparable retest, human closure,
  immutable baseline and full code/configuration parity (one method). No install
  or execution of target APK. This is controlled compatibility, not arbitrary APK
  or real Android-device acceptance.
- Clean-export wheel installed in a fresh outside-checkout venv passes isolated
  imports/version, frontend/modules/cloud cases/teaching and actual served asset
  SHA checks. **138** packaged source/data files match; only two current assets,
  no runtime data/APKs/secrets/node_modules. The compiled-APK proof is tied to
  **135 unchanged non-static files** through the final frontend rebuild.
- Local schema remains **6**. Verified private database backup and preexisting row
  hashes preserve 162 jobs, 87 assets, 1,033 events, 12 cases, four AI reports and
  25 upload records before adding two explicitly synthetic 0.12 review examples.
  A database backup does not replace source-artifact/upload backups.
- The live 0.12 server is ready at 127.0.0.1:8765. Existing provider session key was
  restored only to the same authorized base/model; no new commercial inference.
  Android runtime, live cloud state/effective IAM, real deployment and remote CI
  remain unverified. Local simulated inference is not account/billing acceptance.


## Workbench 0.11.0 — 2026-11-01

- Complete `scripts/check.py`: **1,422 passed, 1 skipped, 1 warning**, **92.14%**
  coverage, pytest **146.95s**. Ruff passed; strict mypy **107 source files** passed.
- Frontend TypeScript/Prettier/build passed. Static assets:
  `index-CTvnKQHr.js` / `index-CZt7Pdb6.css`.
- `scripts/contracts.py` matched actual OpenAPI and generated requests. Deliberate
  snapshot drift failed as intended; original bytes were restored and clean check passed.
- Exact new `scripts/browser_checks.py` release gate passed **three groups**:
  onboarding 12, teaching/guides/models 15, retained AI protocol 8; **35 checks**,
  no browser errors. Each group uses temporary workspace/local fixtures and strips
  AI environment config. The latter two groups each make one deliberately authorized
  simulated inference; those are not paid or commercial calls.
- Real teaching HTTP evidence changes CSP/frame/nosniff/referrer from review to pass,
  with the same URL, immutable baseline, known evidence and human case closure.
  Deterministic guide reading does not require or call AI. Nginx text is explicitly
  confirmed and was not deployed against a real Nginx server.
- Source smoke from outside checkout using existing venv `python -I` passed:
  three modules, existing cloud remediation and the new teaching/guide/retest flow.
  Separately, the clean candidate wheel was installed into a fresh venv outside the
  checkout: isolated imports/version/path, doctor, all three sample modules, saved
  cloud remediation and real Lab/manual-guide/compare/retest/human-close all passed.
  All 134 package source files matched staged blobs; only current frontend assets
  and no runtime SQLite/APKs/node_modules were present.
- Actual idle previous server was stopped; private SQLite backup integrity/counts
  verified. Actual v5→v6 upgrade preserved recorded row counts, old provenance NULL,
  and historical public-probe/failed-AI IDs. New server reports 0.11.0.
- Live saved-profile GET /models returned connection_failed, no HTTP authentication
  response and no new inference. Python and system curl independently reset before
  HTTP. The operator explicitly deferred real inference acceptance this iteration.
- Workflow YAML/read permissions/browser invocation were checked locally. Remote
  GitHub runner execution is not claimed. Existing symlink skip and upstream
  TestClient/httpx warning remain visible.

Local records are under `outputs/workbench-0.11/`: `ui/`, `browser-gate/` and
`validation/`, with screenshots actually viewed. Independent Lab 14/migration 9/
AI combination 149 groups overlap the final count and are not added to it.
No antivirus disablement, certificate bypass, installed proprietary rule access
or commercial model success is part of this acceptance.

## Workbench 0.10.0 — 2026-11-01

Final `.venv/Scripts/python.exe scripts/check.py`: **1,340 passed, 1 skipped,
1 warning**, **91.99%** coverage against the 85% gate; pytest **137.69s**.
Ruff passed across source/tests/scripts; strict mypy passed **105 source files**.
This follows reproduced fixes to Windows JSON encoding and missing frontend-entry
detection; earlier 1,338-case results are superseded rather than added.

- Frontend TypeScript, Prettier and production build passed. Static bundle:
  `index-C8m18Vji.js` / `index-BSVNFeCW.css`.
- `scripts/verify_onboarding_ui.py`: **12/12**, zero browser errors, **zero inference
  calls**. Isolated temporary workspace, synthetic key and one unauthenticated
  loopback diagnostic GET. Covers three asset paths, module routes/reload/back,
  keyboard skip navigation, malformed links, provider capabilities, credential
  isolation, exact unsaved draft diagnosis and 390px layout.
- `frontend/scripts/verify_ai_ui.py`: **8/8**, zero browser errors, exactly **one**
  deliberate `/v1/chat/completions` call to a local protocol fixture. Redaction,
  demo rejection, cloud/source labels, asynchronous persistence, export, refresh
  without resubmission and 390px layout passed. This is not a real-model test.
- Provider/API/architecture targeted group: 58 passed; independent persistence/
  pagination/retest and doctor regressions are included in the final full count.
  Overlapping local groups must not be summed as disjoint suites.
- Actual Windows PowerShell 5.1 parsed the launcher successfully. Old-Python
  handling was statically reviewed; a Python 3.10 installation was not exercised.
- Built wheel/sdist. Wheel inspection found exactly the current frontend assets,
  provider and doctor modules, with no runtime SQLite/APKs/node_modules. A **fresh
  venv outside the checkout** installed the wheel; `python -I` confirmed 0.10.0.
  Read-only doctor, three actual local sample-module runs and saved cloud
  asset→inspection→case→revised-file→retest→manual-resolution all passed.
  Fresh dependency resolution used AnyIO 4.16.0; the validated source environment
  and its lock record 4.15.1. This is not a universal dependency-version matrix.
- Real local server health reports **0.10.0**. The authorized session credential
  was restored without displaying it; the configured model route was unchanged,
  with the strongest advertised reasoning variant.
  A no-key GET diagnostic of that exact base returned `unreachable`,
  `connection_failed`, `stage:connect`. **No new inference was sent.** The earlier
  single AI attempt remains recorded as `AI_NETWORK_ERROR`.

Local evidence: `outputs/workbench-next/ui/onboarding-ui.json`,
`ai-protocol/ai-ui-validation.json`, `validation/installed-smoke.json`, sanitized
logs and `provider-diagnostic.json`. Desktop and mobile screenshots were actually
inspected. No Browser plugin was available, so existing project Playwright/Edge
was used without disabling antivirus or TLS checks. Request assertions cover this
app and its controlled provider fixture, not independently injected host-security
software traffic.

The one skip is the retained Windows symlink-permission condition; the warning is
the existing upstream Starlette TestClient/httpx deprecation. No successful
commercial GPT/DeepSeek inference, multi-user isolation, public-deployment safety
or absence of bugs is claimed. See [independent review](../reviews/workbench-0-11-to-0-14.md).

## Workbench 0.9.0 — 2026-11-01

The Web AI advisory experiment was integrated on the same Windows/Python 3.13.15,
Node 24.14.0, npm 11.9.0 and Edge environment. The commercial provider was not
called; the local protocol fixture is labeled in its report and output.

- Final integrated source check: **1,281 passed, 1 skipped**, coverage **91.65%**
  against the 85% gate. Ruff passed and strict mypy checked **102** files.
- The input-origin audit added **62** profile/import cases and retained Web/module
  regression groups. Website demo now contains **20** explicit synthetic HTTP(S)
  sites; the old mixed 25-row classifier dataset remains a legacy golden fixture.
- AI advisory unit/API coverage contains **21** cases: real probe-only eligibility,
  URL/path/query minimization, 64 KiB budget, endpoint/DNS policy, secret handling,
  consent/hash/idempotency, output allowlists, safe export and interrupted recovery.
- Real local browser/API protocol acceptance passed **8/8**. It created a temporary
  loopback website with path/query secrets, performed one real bounded probe, checked
  that the preview and provider payload were redacted, rejected the synthetic demo,
  kept cloud HTTP labels separate, persisted one asynchronous report, refreshed it
  without another request, and passed the 390px check. `console_errors=[]` and the
  fixture received exactly one `/v1/chat/completions` request. This is protocol/UI
  compatibility evidence, not model quality or provider acceptance.
- AI keys were restored to absent after the fixture; `/api/ai/config` reported
  `enabled:false`, empty model, default provider base and `has_key:false`.
- Current frontend source passed TypeScript, Prettier and production build. The
  generated static assets are `index-Bh8sPqm-.js` and `index-CSUbbZM3.css`.
- The full suite still has the existing Windows symbolic-link permission skip and
  Starlette TestClient/httpx deprecation. No commercial API key, installed Kaspersky
  rule, private signature database or endpoint policy was read.

The 0.9 implementation is still experimental. Android/cloud AI adapters,
commercial-provider validation, public deployment, multi-user authentication,
automated remediation and production security certification remain out of scope.

## Workbench 0.8.0 — 2026-11-01

The red/blue evidence workflow was exercised on Windows, Python 3.13.15,
Node 24.14.0, npm 11.9.0 and headless Edge. It extends the existing local
asset workflow; it does not introduce account roles or offensive execution.

- Final full source check: **1,182 passed, 1 skipped**, coverage **92.25%**
  against the 85% gate. Ruff and strict mypy passed; mypy checked **94** files.
- The added **111** test instances cover transactional scope/case storage,
  provenance, conservative comparisons, API decisions and real Android-module
  integration. Tests retain the old engine and all three module regressions.
- A real Android sample exposed an overly broad info-level filter: exported
  component facts could not enter the review workflow. The fix only admits
  evidence-backed `android_attack_surface` facts with a positive integer exported
  count, preserving `info`/`observed`; zero/unknown counts and unrelated noise stay
  excluded. Eleven regression instances exercise this, including manifest-only
  and full execution. Absence in a later report still cannot close an Android case.
- Actual offline cloud API acceptance passed **28/28** groups: HTTP multipart
  uploads, saved-asset preflight, selected network execution, fixed workspace scope,
  source evidence, idempotency replay, stale-version conflict, explicit revised
  input, missing-resource rejection, record-without-auto-close, manual resolution,
  paging and JSON/escaped HTML export. No cloud account or target was contacted.
- New real-browser acceptance passed **11/11** groups, including source review,
  assignment, comparable Web retest, manual resolution, editing a resolved case,
  CAS conflict, local cloud revision, 103-event pagination, keyboard and 390px UI.
- Retained UI **13/13**, asset wizard **6/6**, response-loss recovery **9/9**,
  expanded Web response/comparison **15/15**, and asset API **8/8** passed.
  The four frontend suites report no page execution errors. The recovery suite
  intentionally holds a response and can emit a Playwright Python cancellation
  callback warning; its assertions pass and this is not hidden as a page error.
- TypeScript, Prettier and production build passed; `pip check` found no broken
  requirements. Official npm registry audit reported **0 known vulnerabilities**
  at validation time. The configured mirror lacks its audit endpoint; that failed
  attempt was retried against the official registry rather than reported as clean.

The existing Windows symbolic-link-permission skip and upstream Starlette
TestClient/httpx deprecation remain. These results do not establish real-world
vulnerability detection accuracy, cross-platform behavior or an absence of bugs.

The live schema-v3 database was backed up before migration to v4. All **93**
pre-migration jobs and **38** saved assets are retained. New checks and examples
add records rather than overwrite those inputs. A combined saved showcase now
contains Android entry facts, an in-progress Web configuration review and a cloud
file condition closed by a human after a comparable revised-file check. These
are explicitly synthetic/local examples, not verified enterprise vulnerabilities.

Source and distribution verification use a clean Git export. The installed-wheel
smoke script now starts its own local frontend/API outside the checkout, exercises
all three modules and actual Android method queries, then uploads supported cloud
JSON and performs the saved-evidence red/blue resolution loop. Release-specific
execution logs and artifact hashes are retained with the local release manifest.
No public GitHub release or remote CI execution is claimed.

## Workbench 0.7.1 — 2026-11-01

The interface/reliability maintenance release was reviewed and exercised on the
same Windows/Python 3.13/Node 24/Edge environment. Reproduced issues and design
assessment are recorded in [engineering review](../reviews/reliability-0-7-1.md).

- Final full suite: **1,071 passed, 1 skipped**, coverage **91.93%** (85% gate).
  Counts include retained engine tests. Strict mypy checked **90** source files;
  ruff includes source, tests, application scripts and frontend browser scripts.
- New regressions include **44** module input/response cases, **32** persistence,
  runner and asynchronous reliability cases, **14** inspection/API cases and
  **10** atomic artifact-publication cases.
- Actual competing SQLite writer transactions verify that command/state waits
  do not block loop heartbeats or health responses. Concurrency tests exercise
  request replay, capacity reservations, cancellation during durable writes,
  ordered thread-origin progress and partial-start cleanup.
- File-readiness cases distinguish missing, altered-size, altered-hash and decoder
  prerequisites. A busy workspace cannot be migrated by another server; future
  metadata is rejected before changes and failed migrations roll back.
- One final regression attempt surfaced a Windows WinError 5 while atomically
  publishing artifact evidence. A bounded Windows-specific retry was added with
  independent transient/permanent/non-Windows/concurrent-winner tests; the final
  full suite above then passed. Persistent faults remain errors.
- The remaining skip needs Windows symbolic-link permission. The reported pytest
  warning is the existing upstream Starlette TestClient/httpx deprecation. Coverage
  subprocess instrumentation also emitted already-imported-module warnings; no
  failing case or coverage gate is hidden by those messages.

Frontend TypeScript, Prettier and production build passed; official npm audit
reported **0 known vulnerabilities** at validation time. Real browser checks:

- **9/9** new recovery groups. Proxy forwards actual asset/inspection/retry writes,
  drops their successful responses, then checks that manual retries return the
  same ID/key with no duplicate history. A held real retry response verifies the
  client waiting deadline, no automatic replay and successful manual recovery.
- **13/13** retained workflows and **6/6** asset UI groups, with no browser errors.
- **15/15** expanded Web response/comparison groups and **8/8** asset HTTP API groups.

The new recovery script deliberately injects blocked-preflight/error-display
responses and uses a browser clock for the client deadline. Those are labeled
UI contract checks, not claims that the underlying disk/clock was altered. Actual
file/environment failures are covered independently through the inspection API.
Scripts: `frontend/scripts/verify_reliability_ui.py`, `verify_ui.py`,
`verify_assets_ui.py`, `scripts/verify_web_upgrade.py`, `verify_asset_flow.py`.

After the final service restart, a real uploaded synthetic `rs-control.apk` ran
through saved-asset preflight and inspection twice: manifest-only produced no code
artifact; full analysis saved methods and returned `readFile`/FileInputStream code.
No APK was installed/executed. Earlier stored jobs/assets remain readable.

The v2 live database was backed up before migration to v3. Final distributions
are rebuilt from a clean Git export, inspected against source and installed into
a separate virtual environment; installed frontend/API, all three modules,
preflight, linked asset execution and Android method querying are exercised from
outside the checkout. No public GitHub release or remote CI run is claimed.

## Workbench 0.7.0 — 2026-11-01

The asset-first Android/Web/cloud release was validated on the same local Windows,
Python 3.13, Node 24 and Edge environment. Checks observe actual backend execution;
frontend selection does not merely filter already-computed results.

- Full Python suite: **971 passed, 1 skipped**, coverage **91.78%** (85% gate).
- ruff and strict mypy passed; mypy checked **87** source files. The existing
  Windows symbolic-link permission skip and upstream TestClient deprecation remain.
- Cloud module: **60** regression cases, including Terraform planned unknowns,
  sensitive/malformed marker shapes, IAM conditions/unsupported expressions,
  security-group ingress direction, S3 unknown flags, duplicate fields and budgets.
- New selection cases instrument unselected functions to fail if called, proving
  that Web HTTP-only skips page/Cookie/audit/classification and that Android
  manifest-only does not run the code graph/indexer.
- A real local synthetic `rs-control.apk` completed manifest-only decoding with
  Apktool 2.11.1; it produced no source artifact or leftover temporary decoder tree.
  The application was never installed or executed.
- Asset tests cover additive migration of a legacy schema-v1 workspace, immutable
  input snapshots, input mismatch rejection, upload metadata/budgets, pagination,
  retry association, reopen persistence and legacy unassociated jobs.

Frontend strict TypeScript, Prettier and production build passed; npm official
audit reported **0 known vulnerabilities** at validation time. Browser regression
passed **13/13** retained workflows. New asset UI acceptance passed **6/6**:
four-step cloud selection, real network-only run/evidence, asset reuse with IAM-only,
two-run asset history, actual website HTTP-only execution, missing-input blocking,
cloud address/configuration distinction, keyboard behavior and 390px layout.
No browser execution errors were observed. Scripts are retained at
`frontend/scripts/verify_ui.py` and `frontend/scripts/verify_assets_ui.py`.
The retained expanded Web response/comparison/browser acceptance also passed
**15/15** against the final 0.7 backend/frontend with no execution errors.

`scripts/verify_asset_flow.py` additionally passed **8/8** actual HTTP API groups:
catalogue discovery, saved cloud network-only/all-check inspections, two-run asset
history, cloud-address Web observation, headers-only dependencies, Android
manifest-only/query scope, uploaded IAM file evidence and mismatched-input rejection.
Only two supplied URLs on its temporary loopback fixture were contacted; referenced
script URLs were never fetched. Cookie/condition secrets were not copied to the
checked outputs. The original uploaded cloud file is retained locally as documented.

The live workspace was backed up before migration. Old saved Android/Web results
remain readable, and schema v2 assets associate only newly created runs. A clean
cloud showcase uses six synthetic resources, five checks, four review observations
and one unsupported resource. These are configuration review examples, not cloud
account inspection, real-world accuracy or exploit validation.

The final release is built from a fresh Git export to exclude stale build assets.
Its installed-wheel smoke starts the real frontend/API and all three modules from
outside the checkout, reads actual Android method code and exercises linked assets
with a selected cloud group. Source/wheel contents include rules, provenance and
frontend notices while excluding workspace state, APKs and dependency directories.
No public GitHub publication or remote CI run is claimed.

## Workbench 0.6.0 — 2026-11-01

Observed on the same Windows/Python 3.13/Node 24/Edge environment described below.
The original projects remain separate. `python scripts/check.py` passed:

- **882 passed, 1 skipped**, coverage **92.01%** (85% gate).
- ruff and strict mypy passed; mypy checked **79** application source files.
- New Web coverage includes 88 response-audit cases, page/Cookie parsing, saved
  comparisons and CSV/API regressions. Counts include the retained engine suite.
- The existing upstream TestClient deprecation and Windows symlink-permission
  skip remain. `pip check` reports no broken requirements.

The cancellation regression now waits for the real request to reach a gated
fixture rather than racing a short timer under Windows scheduler load. An
earlier timer-based attempt failed; after synchronizing pending I/O the final
complete suite above passed. Cancellation in the live UI passed independently.

Frontend TypeScript, Prettier and production build passed. The official npm
audit reported **0 known vulnerabilities** at validation time. Real browser/API
validation passed **15/15 new Web checks** and **13/13 retained workflow checks**,
with no browser execution errors. An additional SPA test confirmed Web view,
asset/filter and baseline state resets when changing tasks without a page reload.

The new fixture made exactly six supplied-URL GETs in two rounds. It verified
Cookie values were absent from saved results, form values absent from the page
inventory, resource references were not fetched, and inline code was not executed.
The comparison distinguished one changed, added, removed and not-comparable URL;
CSV formula neutralization and real UI download were checked. Header and Cookie
capture gaps, old result fields and incompatible body hashes have regression cases.
HTTPS IP-literal HSTS is explicitly not applicable.

Two additional clean showcase tasks captured the same single loopback URL before
and after a configuration change. The current result has one asset, one response,
12 checks, one review item and zero connection failures. Its HTTP password-form
review remains visible. The temporary fixture is stopped; saved evidence remains
readable. These are reproducible synthetic responses, not public-site measurements.

Release validation includes installing the final 0.6 wheel in a separate virtual
environment and running frontend/API + both-module/source-query smoke checks from
outside the checkout. Packaged files are checked against current source; stale
build output, runtime workspaces, APKs and node_modules are excluded. Built assets,
frontend license appendix and isolated rule-module provenance remain included.
No public release, remote CI run or general vulnerability-accuracy claim is made.

## Earlier release: 0.5.0

Observed locally on 2026-11-01 (Asia/Shanghai), Windows, CPython 3.13.15,
Node.js 24.14.0 and Microsoft Edge. The original projects were not overwritten.
The new independent checkout is `<LOCAL_PROJECT_ROOT>/reachscope-workbench`.

## Source and module checks

`python scripts/check.py` passed:

- ruff on application source, tests and scripts.
- strict mypy on 74 Python source files. Isolated copied legacy components are
  explicitly excluded from new-code type/coverage metrics; adapters are checked.
- **767 passed, 1 skipped**, Python coverage **91.61%**, threshold 85%.
- This count includes the retained engine's regression suite as well as new workbench cases.
- The skipped test requires Windows symbolic-link creation permission. Remaining
  traversal, corruption, long-path and workspace/identity checks ran.
- One upstream Starlette TestClient/httpx deprecation warning was observed; it
  did not affect these results. `pip check` reported no broken requirements.

Dedicated new coverage includes 25 Android module cases and 41 Web module cases,
plus task repository/runner/locking, public API and architecture regressions.
Tests validate cancellation, worker descendant cleanup, orphan pipes/timeouts,
interrupted-state recovery, conditional terminal transitions, upload/request
budgets including chunked JSON, invalid IDs, report escaping and live loopback
HTTP responses. Tests do not send probe traffic to public targets.

A local synthetic control APK, `rs-control.apk`, was also supplied through the live
multipart upload API and submitted as an Android job (not just a module invocation).
The isolated worker decoded it with the existing Apktool 2.11.1, produced its report,
and a subsequent method query returned saved `readFile` code with FileInputStream
after temporary decoding was cleaned. No APK was installed or executed. APK files
and runtime artifacts are excluded from distributions.

## Frontend and browser

`npm run check` and `npm run build` passed strict TypeScript and the Vite production
build. Prettier checks passed. The npm lockfile uses exact dependency versions and
official registry records. `npm audit` reported zero known vulnerabilities at the
time of this run; this is a point-in-time dependency check, not an application audit.

The real frontend and latest local API passed **13/13** browser acceptance groups:

1. Dashboard and module discovery from the live API.
2. Submit Android cross-component analysis and read the saved target method.
3. Inspect evidence, persistent event journal and reproducible configuration.
4. Download actual result JSON.
5. Probe a temporary loopback HTTP server and inspect its actual headers/title.
6. Upload and import assets; hostile title strings remain inert text.
7. Run copied classification/transition rules; inspect/search assets and paths.
8. Delay an old task response, switch tasks, and verify it cannot replace the new one.
9. Cancel an actual slow probe.
10. Read persistent task history and search it.
11. Navigate, open/close dialogs and use the layout at 390px mobile width.
12. Refresh a task route and recover its completed result.
13. No browser execution errors.

These are created tasks and observed results, not mocked dashboard data. The
acceptance fixture uses only this machine for active Web requests. It leaves
clearly named verification tasks in the local workspace for inspection. Earlier
cancelled/failed attempts are retained as historical task records.

Repeat with the server running:

```bash
python frontend/scripts/verify_ui.py --base-url http://127.0.0.1:8765 \
  --browser /path/to/chromium-or-edge --out data/ui-validation
```

## Release and scope

The release includes built frontend assets, backend/core, both modules, copied
rules and their MIT/provenance files, tests, source frontend and lockfiles. Source
and wheel contents are inspected to exclude node_modules, virtual environments,
SQLite state, uploads and APKs. `scripts/smoke_installed.py` exercises a fresh
wheel's frontend/API, Web sample, Android worker and actual source query outside
the editable checkout.

GitHub Actions is configured for Windows/Linux with Python 3.11/3.13 and Node 24;
no remote CI run or public repository publication is claimed. HTTPS certificate
and SNI request construction is covered, but live public-target HTTPS accuracy
is not asserted from the loopback checks. Imported scanner findings are never
called verified, rule scores are not calibrated probabilities, and no overall
vulnerability precision/recall or model-effectiveness result is claimed.
