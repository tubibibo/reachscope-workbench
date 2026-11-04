# ADR 0006: static review, bounded input preview and separate guide eligibility

Date: 2026-11-02. Status: accepted.

## Context

The operator prioritizes useful Android analysis before Web/cloud depth. Existing
candidate code paths cannot represent release configuration, resource variants or
all target/device defaults. Cloud users also need to know whether an input can
cover selected checks before they create a task. Neither problem requires AI.

## Decision

1. Keep manifest/code_paths as actual execution selections. Add a versioned
   `details.security_review` with stable check/resource IDs, four explicit states,
   per-check completeness, bounded source facts/hashes and server-owned guidance.
2. Decode full APK inputs once in an owned worker. Capture bounded configuration
   from actual decoded resources before using the existing immutable code engine.
   Temporary resources are cleaned on completion/cancellation; no APK is executed.
3. Retain the old boolean candidate IR for compatibility. Correct known permission
   and filter/default mistakes, but represent unsupported/device-dependent facts in
   the authoritative review as unknown with an explicit explanation.
4. Compare Android cases only across the same package, versioned rule and resource
   identity, completed manifest scope and known saved evidence. A claimed fix needs
   complete baseline/retest facts, an explicitly related revised file and a later
   human closure. Package equality is not cryptographic signer identity.
5. Define an optional core-owned `LocalInputPreview` port. Cloud implements bounded
   read-only normalization and coverage accounting; the core never imports a module.
   Preflight checks the saved file digest first. Invalid input blocks execution;
   missing/unknown fields remain warnings and do not become successful rule checks.
6. Attach manual cloud guides only to rules actually executed and their evidence.
   Guides never deploy configuration, compute effective permissions or execute tools.
7. Separate deterministic HTTP guide eligibility from paid AI context eligibility.
   A saved cloud-external HTTP probe may receive manual Web guides, but is never
   silently converted into a website asset or included in the AI adapter registry.

## Consequences and limits

No schema change or historical backfill is required. Old results show their actual
missing review rather than invented modern fields. UI responses are still defensive
view models; generated request types alone do not prove every response contract.

Resource references, target/device behavior, backup data classification, signatures,
domain verification and live cloud state remain bounded by available inputs. A pass
is a stated static declaration result, not overall safety or exploitability proof.
Commercial inference, remote CI and real deployment validation stay separate gates.
