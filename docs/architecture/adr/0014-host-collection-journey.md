# ADR 014 — Read-only host collection and guided remediation

Status: implemented for 0.14; local source/browser/package acceptance passed;
actual Linux binary acceptance remains not executed because prerequisites are absent.
Date: 2026-11-02. Baseline commit: c7ddaa7 (0.13.0).

## Outcome

Make one developer-operated Linux website-server review reproducible: prepare
minimal local configuration evidence, preview it, execute selected rules, follow
the existing case/revision/retest workflow and record an explicit human decision.
Do not add new asset relationships, remote execution or automatic remediation.

## Boundaries and dependency direction

- `collectors/host` owns a stdlib-only local command adapter, bounded capture,
  allowlisted projection, export and reviewable zipapp packaging. It imports
  neither the HTTP API, core use cases nor security-rule modules.
- The collector defaults to a plan. Execution needs an explicit plan-hash-bound
  confirmation. Commands are fixed argument arrays; no shell, automatic sudo,
  network upload or configuration mutation is permitted.
- The host input adapter owns v1/v2 snapshot validation and normalization. The
  baseline engine continues to own deterministic rules and evidence. Capture
  failure or projection ambiguity must not become a passing check.
- HTTP endpoints only deliver the collector/source artifacts. They never run it.
  The composition CLI may expose its entry point; core stays adapter-independent.
- React presents the existing asset/preflight/case APIs. UI helpers may explain
  progress and unknowns, but cannot redefine comparison or closure rules.
- Original task inputs, evidence and case audit records remain immutable. Use
  existing engagement grouping; defer new cross-asset identity models.

## Input and provenance

The versioned `reachscope-host/2` export extends the host snapshot with collector
version, projection identifier, plan digest and bounded component capture states.
The snapshot contains only selected SSH values and supported Nginx context data;
full stdout/stderr, credentials, host names, private paths and raw log records are
not export fields. Unsupported syntax must remain an explicit coverage gap.
Supplied host identity, time and collection metadata remain unverified assertions,
not proof of machine ownership or currently loaded service state.

Version 1 remains accepted. No storage schema migration is planned: v2 uses the
existing immutable file inputs; older readers reject the unknown input version.
Projection identity must be included in v2 comparison scopes so v1/full-text and
v2/projected contexts cannot silently be treated as the same evidence boundary.

The projection parser intentionally accepts a smaller language than the import
review parser. It shares no security-rule execution dependency; differential
contract tests compare supported projections against original rule outcomes,
while unsupported constructs fail closed. The downloadable source includes its
MIT license and has no added runtime dependency.

## Acceptance

Cover capture timeout/limits/errors, restrictive exclusive output, privacy,
unsupported syntax, provenance, preview without rule execution and comparable
retests. Exercise desktop/mobile UI with actual isolated uploaded files. Run
source/contract/frontend gates and fresh installed-package acceptance. Validate
with real Linux binaries only when a suitable isolated environment is available;
mock fixtures are never reported as Linux execution. Record actual blockers and
counts in the release status rather than claiming planned work is complete.
