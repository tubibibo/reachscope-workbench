# ADR 0004: Evidence-bound AI advisory

- Date: 2026-11-01
- Status: Accepted for the bounded local experiment; commercial inference unverified.
- Scope: 0.9 AI/Web pilot and 0.10 provider/UX reliability iteration.

## Context

The project needs useful explanation and prioritization for red/blue review without
giving a language model authority over scope, probing, evidence or case decisions.
Saved responses, code, imported reports and notes can contain untrusted instructions.
Public endpoint-protection descriptions may inspire review principles but cannot
be treated as a transferable proprietary detection database.

## Decision

Use a deterministic, server-owned defence catalogue with stable control IDs,
original review/action/verification summaries, applicability, limitations and
public attribution links. Allow a model to select/rank known control IDs and
existing evidence IDs only. Render control text from the server catalogue;
model-generated instructions or explanations do not become authoritative UI copy.

Keep any provider adapter outside the core catalogue. The core imports neither
HTTP/API nor a concrete analysis module. The catalogue/context projection reads no
credentials or installed security-product state and performs no network requests.
The application service holds an ephemeral credential for the provider port.
Model-assisted advice does not
create evidence, alter selected checks, invoke tools, expand scope, execute a
payload, submit credentials, change case state or supply a trusted retest outcome.

Preserve unknown/failed/truncated/unverified source states. Validate model output
as bounded data against control/evidence allowlists. Reject unknown IDs and
instructions masquerading as output. A partial or failed provider response must
remain an explicit advisory failure, without promotion to a successful inspection
or a verified security conclusion. Existing deterministic workflows remain usable.

Website response controls, manual application/operations review and endpoint
hygiene have distinct applicability labels. A TLS/CSP observation cannot prove
endpoint protection is configured, and an endpoint overview cannot substantiate
a website finding. Red review topics are authorized high-level manual questions;
the catalogue contains no exploit payloads or attack-chain generation.

## Consequences

- Advice remains traceable to stable controls and saved evidence, and can be
  explained without a model-generated policy database.
- The catalogue is guidance, not a scanner rule engine, WAF, antivirus/EDR,
  effective-permission analysis or a compliance certification.
- Remote provider use, if introduced, needs explicit configuration, bounded
  transport, input-minimization/error handling and a documented data boundary.
  This ADR does not assert those integrations already exist or have been tested.
- Catalogue updates require review of source attribution, applicability, signal
  IDs, schema and regression tests. Model popularity is not a quality measure.
- Existing CAS/audit and manual-resolution requirements stay authoritative.

## Verification and current status

Catalogue tests must check exact fields/stable IDs, uniqueness, defensive copies,
reference allowlists, supported signal mappings and separation of manual/endpoint
items from observed Web checks. Adapter/service tests must independently exercise
unknown IDs, malformed/bounded responses, injected target text and error paths.

The operator supplied a credential and attempted one advisory against saved public
website response evidence. That request failed with `AI_NETWORK_ERROR`; subsequent
credential-free GET diagnostics also failed at the connection layer. No successful
commercial inference or DeepSeek account acceptance is established. Component and
local-protocol fixtures remain separately labeled in [project status](../../releases/project-status.md).

In 0.10 a pure provider capability registry supplies presets without an SDK
dependency. Concrete transport remains in `integrations/`, assembled by the API,
and an architecture regression prevents core imports of concrete integrations.
Provider-specific parameters are explicit, default reasoning is omitted, keys are
scoped to provider/base, and draft diagnostics send neither key nor business data.
