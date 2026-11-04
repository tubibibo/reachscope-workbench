# Changelog

## Workbench 0.14.2 — 2026-11-04

- Add a version-consistency test locking the pyproject version, the Python
  package `__version__`, the frontend package version and the OpenAPI contract
  version together; any drift now fails the unit suite.
- Upgrade the CI actions to their current majors (checkout, setup-python,
  setup-node and upload-artifact to v7) so the workflows keep running after the
  Node 20 runner deprecation.
- Pin the CI runners explicitly to ubuntu-24.04 and windows-2025 (browser:
  ubuntu-24.04) ahead of the ubuntu-latest image migration to Ubuntu 26.
- Restrict CI triggers to branch pushes, pull requests and manual dispatch;
  tag pushes no longer re-run the full check set.
- Remove the English README's "What it is not" section; the same boundaries
  remain documented in SECURITY.md and README.zh-CN.md.
- State at the top of both READMEs that the repository is a one-time public
  export of a privately developed history; no earlier version was published here.

## Unreleased — repository organization

- Group documentation by audience and responsibility, with lowercase filenames,
  an index and a historical path map. Keep dated acceptance commands intact.
- Consolidate browser checks in tests/browser, engineering gates in scripts/quality,
  smoke checks in scripts/smoke and benchmark execution in scripts/benchmark.
- Group shared frontend modules under lib and global CSS under styles; preserve
  component names, application behavior, package names and public API contracts.
- Archive root-level local logs without deleting evidence, centralize tool caches
  under .cache and direct new local outputs to artifacts.
- Add an offline repository-layout/link gate and update CI, sdist manifests,
  developer entry points and naming conventions. Version/schema remain unchanged.

## Workbench 0.14.1 — 2026-11-02

- Bind AI draft credentials to the edited destination and consent to the reviewed
  context hash; preserve original preview/idempotency on ambiguous submissions.
- Bind case decision validation to the caller's exact version before the existing
  final transactional CAS, closing a concurrent-reopen/reclose validation gap.
- Reject ambiguous cloud change identities, Android manifest singletons, Windows
  ZIP path aliases and report-local component/chain identities instead of taking
  first/last declarations or silently overwriting evidence.
- Bound legacy decoder/version diagnostic capture; discard unused worker decoder
  logs and preserve owned Windows process-tree cancellation through one adapter.
- Escape decoded request paths in logs and consolidate safe public-reference URL
  policy. Keep exploitability assertions separate from defensive hardening.
- Add isolated security regression tests, a browser security group and a dedicated
  security test log with before/after evidence and dependency/SAST triage.
- Preserve the known minimatch development-only advisory as unresolved; production
  npm/runtime Python audits are recorded separately. Do not force incompatible
  generator dependency majors or equate audit failure with zero vulnerabilities.
- Keep schema 7, Linux pause and commercial-inference deferral; no new scanning,
  response automation or third-party report integration is introduced.

## Workbench 0.14.0 — 2026-11-02

- Add a standalone, reviewable stdlib host collector with plan-bound explicit
  execution, fixed local command arrays, bounded capture and allowlisted exports.
- Accept versioned projected host inputs without trusting producer metadata;
  failed/partial captures stay unknown and projection identity bounds retests.
- Deliver collector/source downloads through a dedicated HTTP adapter. Downloads
  do not execute commands or create inspection jobs.
- Guide existing host evidence, engagement/case, revised-file and human closure
  workflows without adding a parallel state machine or asset relationship model.
- Align first-use host documentation and add an explicitly disposable Linux
  acceptance harness. Actual Linux execution is prerequisite-gated and must be
  reported separately from Windows/mocked fixtures and remote CI configuration.
- Keep schema 7 and original inputs/history; no remote shell, service reload,
  automatic remediation or commercial model request is introduced.

## Workbench 0.13.0 — 2026-11-02

- Center the local workflow on defensive hardening, evidence review and human
  remediation verification while retaining Android, Web and cloud modules.
- Add an independent host module: bounded SSH/Nginx exported configuration
  baselines, Nginx access/OpenSSH authentication log inputs, templates and previews.
- Add seven configuration rules with context-aware unknowns, actual evidence and
  manual review/hardening/verification/rollback guidance; execute only selected groups.
- Add three explicit fixed-window log indicators with coverage gaps, UTC times,
  input-line references and per-input aliases; exclude raw private log values.
- Preserve synthetic source labels through checks/events/evidence and qualify
  merged log event IDs by input format. Finite log silence never proves a fix.
- Bind host revisions to declared host, rule, resource, complete context and known
  nondecreasing supplied collection times; closure retains CAS/audit and human notes.
- Gate new asset semantics with schema 7, retain original v6 rows/JSON/provenance,
  and reject future v8 before writes. Downgrade requires the matching old backup.
- Fix parser date/quote/context edge cases and retain actual review facts when a
  large configuration exceeds its evidence budget. Add isolated UI/installed gates.
- Commercial inference, live endpoint collection, automatic response, mature-tool
  connectors and production SOC operation remain explicitly unverified or unimplemented.

## Workbench 0.12.0 — 2026-11-02

- Deepen Android with eight bounded static configuration reviews, real XML resource
  evidence, platform-aware unknown states and deterministic manual red/blue guides.
- Decode full APKs once for resource/configuration and existing code-path analysis;
  retain manifest-only selection, owned worker cleanup and strict output validation.
- Correct inherited application permissions, legacy Provider defaults and merged
  intent-filter data semantics; preserve limits and unsupported runtime conditions.
- Add Android review navigation/search and evidence-bound same-package rule retests
  over explicitly related revised APKs; unknown or partial data cannot close cases.
- Preview offline cloud input coverage before task execution through a core-owned
  optional port, and attach manual guides to all seven existing cloud rule IDs.
- Extend deterministic HTTP configuration guides to saved cloud-service probes,
  without broadening the separately consented website-only paid AI policy.
- Harden malformed saved-evidence boundaries and add isolated Android/APK/cloud/UI
  regression acceptance. Schema stays 6; real commercial inference stays unverified.

## Workbench 0.11.0 — 2026-11-01

- Add an opt-in loopback teaching site and explicit baseline→hardening→retest→human
  case-resolution flow through the real saved-asset/evidence APIs.
- Preserve server-owned local-training provenance in schema 6 asset/job snapshots,
  keep legacy origins unknown and retain immutable history across restart.
- Add AI-independent evidence-linked implementation guides, manual Nginx references,
  rollback/acceptance criteria and layered result summaries.
- Separate no-key draft connectivity, hash-bound consented model-directory GET and
  independently authorized inference; never treat model visibility as paid-call success.
- Generate request types from actual OpenAPI with pinned openapi-typescript 7.13.0;
  gate drift and add isolated browser CI plus extended installed-wheel smoke.
- Fix runtime case creation payload serialization, teaching retries, stale-response
  guards and session-record validation; retain strict server schemas and manual closure.
- Real commercial inference remains blocked by the supplied gateway connection reset;
  local protocol fixtures are separately labeled.

## Workbench 0.10.0 — 2026-11-01

- Define an asset-driven evidence/remediation workbench with optional provider
  adapters; record product scope, developer tools and GitHub reference decisions.
- Add an actionable getting-started guide, asset-specific wizard entry points,
  source labels, skip navigation and persistent per-module routes.
- Add DeepSeek/OpenAI-compatible/custom provider metadata, provider-aware reasoning
  and token-budget parameters, and credential-free diagnostics of unsaved drafts.
- Bind keys to provider/base; preserve old-client same-endpoint configuration,
  and fix cancellation consistency plus advisory acceptance/shutdown races.
- Move upload copy/SQLite commit together off the event loop; preserve committed
  files after response cancellation and clean up failed submissions.
- Reject overflowing SQLite pagination inputs; require retest collection to start
  after the original job completed and validate recorded time intervals.
- Add local read-only `doctor` checks, a quickstart and version-aware launcher
  installation; strengthen the core/integration dependency test.
- Add independent regressions and isolated browser acceptance. Model-provider
  protocol fixtures remain distinct from unverified commercial inference.

## Workbench 0.9.0 — 2026-11-01

- Add an opt-in, provider-neutral AI advisory path. Only completed real website
  URL probes are currently eligible; Android and cloud adapters remain planned.
- Preview a minimized origin/check/status envelope and bind consent to its hash.
  Credentials stay in backend memory or an explicit environment variable.
- Persist asynchronous reports with idempotent replay, bounded concurrency,
  failures and interrupted recovery; ambiguous paid requests are never retried.
- Validate model output against 14 server-owned public-guidance control IDs and
  saved evidence IDs. Advice cannot create findings, execute tools or close cases.
- Separate website configuration, manual application/operations review and endpoint
  hygiene; attribute OWASP and public Kaspersky overviews without reading or
  copying installed proprietary rules.
- Restrict website demos to synthetic HTTP(S) sites and visibly preserve source
  origin across real, imported and demo records.

## Workbench 0.8.0 — 2026-11-01

- Add scoped evidence workspaces with red-team review and blue-team remediation
  views over the same Android, Web and cloud inspection sources.
- Derive cases only from saved in-scope observations/checks and known evidence;
  preserve original confidence, uncertainty, source identity and historical inputs.
- Add ownership, deadlines, six explicit decision states, versioned updates and
  atomic append-only audit events. Stale writes fail instead of overwriting work.
- Compare completed retests conservatively and require an explicit human note and
  a comparable not-observed result before resolving. Missing data is not success.
- Link same-profile local revised files explicitly without replacing the original
  asset or allowing network-target scope changes; retain actual input/job IDs.
- Add paginated timelines/retest selection and bounded JSON/escaped HTML exports.
- Migrate supported workspaces additively to schema v4. Red/blue views remain
  local workflows, not account authentication, attack execution or cloud API access.

## Workbench 0.7.1 — 2026-11-01

- Add saved-asset inspection and local preflight commands; separate application
  input/readiness use cases from HTTP contracts and error presentation.
- Persist idempotency keys for asset creation, job submission and retry; replay
  lost responses without duplicate work and reject conflicting key reuse.
- Move database waits off the HTTP/worker event loop while preserving loop-owned
  queues, ordered progress, cancellation and accepted-submission finalization.
- Fix runner restart/partial-start cleanup, progress journal monotonicity,
  repeated cancellation, consistent pagination and transactional schema migration.
- Acquire workspace ownership before migration, and reject future schemas before writes.
- Add structured failure correlation IDs, readiness diagnostics, client waiting
  deadlines and input-preserving recovery without automatic write retries.
- Fix Unicode/JSON/import status parsing, charset fallback, truncated redirects,
  compressed-HTML header applicability and standalone IAM source pointers.
- Document reproduced bugs, engineering practices, local verification and limits;
  no blanket bug-free or production-certification claim is made.

## Workbench 0.7.0 — 2026-11-01

- Replace the input form with a four-step asset/input/check/review wizard.
- Persist normalized Android, website and cloud assets; bind immutable job input
  snapshots and retain each asset's inspection history and retry association.
- Add an explicit catalogue of compatible profiles and check dependencies.
- Execute genuinely selected Android/Web check groups; manifest-only skips code
  indexing, and Web skips unselected parsers/audits/fingerprint rules.
- Add bounded offline AWS Terraform Plan, IAM, security-group and S3 configuration
  review with source pointers, sensitive/unknown markers and limited-rule evidence.
- Keep cloud service-address observations distinct from account configuration review.
- Migrate the local workspace additively to schema v2 and preserve legacy jobs.
- Extend the frontend with asset reuse/history, cloud resource/check views and
  visible execution/skip status, while preserving existing Web result workflows.

## Workbench 0.6.0 — 2026-11-01

- Add structured Web response configuration checks with per-asset evidence,
  explicit pass/review/info/not-applicable states and explanations.
- Extract bounded HTML page metadata, forms, script/style/link inventories and
  mixed-content observations from captured responses without crawling or execution.
- Record Cookie attribute metadata while omitting Cookie values and raw Set-Cookie.
- Compare saved probe jobs by exact normalized URL, distinguishing changed fields,
  changed input sets, failed collection and unavailable legacy fields.
- Add Web inventory CSV export with quoted cells, UTF-8 BOM and common spreadsheet
  formula-prefix neutralization; lossless JSON remains available.
- Extend the real frontend with check filtering, page/resource views, baseline
  selection, field-level differences and CSV download.

## Workbench 0.5.0 — 2026-11-01

- Create a separate local Android/Web workbench with a React/TypeScript frontend.
- Add shared module contracts, explicit registry, persistent SQLite jobs/events,
  bounded execution, cancellation, retry and interrupted-job recovery.
- Adapt APK/sample analysis and source evidence to isolated cancellable workers.
- Add exact-URL HTTP probing with pinned DNS, Host/TLS SNI, scoped redirects,
  body/deadline limits and response evidence.
- Integrate fingerprint rules, rule-based investigation paths and asset import
  with retained license/provenance. Support httpx/Nuclei JSONL as unverified data.
- Add same-origin local API, bounded uploads, structured errors and JSON/HTML export.
- Retain the existing engine and standalone walkthrough as secondary interfaces.
- Provide architecture, API, development, source attribution and installed-wheel
  checks; original source projects remain separate.

## 0.4.1 — 2026-11-01

- Redesign the offline walkthrough as an editorial evidence reading room.
- Add a native SVG instrument, case search/filters, selectable candidate steps,
  synchronized source reading, bounded path playback and clipboard support.
- Preserve separate source observations for unmatched parameter keys; missing or
  blocked paths do not acquire invented connections or simulated execution.
- Support keyboard navigation, motion pause, reduced-motion preferences, mobile
  layouts and a complete no-JavaScript fallback.
- Split HTML, CSS and controller templates while keeping the generated page
  self-contained, dependency-free and usable directly from a local file.
- Keep report/protocol/query schemas and the underlying analyzer unchanged.

## 0.4.0 — 2026-11-01

- Persist content-addressed Android analysis artifacts and method locations.
- Add bounded Python/JSON query APIs for entries, candidate chains, source methods,
  report-derived gaps and claim consistency checks.
- Keep code facts, inferred paths and risk rules distinct in query responses.
- Change protocol output to 0.2; accept 0.1 claims/answers. Reachability checks no
  longer require bridge-specific risk rules. Missing paths/step mismatches are
  inconclusive; only direct manifest access conditions allow scoped refutation.
- Require report schema 0.1 when reading report files. Internal IR golden changes
  are restricted to the tool version; the analysis engine is retained.
- Add source snapshots, integrity and input-budget checks, structured errors,
  an offline five-case walkthrough and a local static HTML report.
- Add license, provenance notes, contributor docs, architecture checks that resolve
  relative imports, cross-platform CI, and installed-wheel smoke verification.

This release does not claim improved real-world vulnerability detection or
measured gains for any model. The demo is a regression walkthrough, not an LLM
benchmark. Real-APK historical results remain historical under `docs/development/benchmarking.md`.

## Earlier releases

Existing v0.1–v0.3 analysis work and the M1 cross-component refinement are recorded
in `docs/dev/` and historical benchmark documents. They are background, not the
current contributor or product contract.
