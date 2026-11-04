# Optional AI / Web advisory

This experiment adds model-assisted prioritization to existing evidence. It does
not replace the scanner, infer permission to test an arbitrary target, or let a
model issue requests, execute commands or close remediation cases.

## Operator flow

1. Open **AI 接口**. Choose DeepSeek, OpenAI-compatible or custom, then set the
   API base, exact model ID and a session key. Saving settings does not call it.
   Diagnose the current unsaved address with a credential-free GET first if needed.
2. Choose **网站 → 网站地址**, enter an authorized HTTP(S) URL, select checks and
   complete the normal inspection.
3. Open **AI 研判**, inspect the minimized envelope and provider, enter the scope
   and purpose, then explicitly confirm sending.
4. The API immediately stores a report ID and returns 202. The UI polls it; leaving
   the page does not resubmit. A new paid attempt requires a new explicit action.
5. Read red manual review themes and blue strengthening suggestions with evidence
   IDs, applicability, verification steps and public references.

## Data and provider boundary

The adapter uses the OpenAI-compatible Chat Completions JSON contract over HTTPS.
Model availability, billing, retention and account permission remain provider
responsibilities. No model ID is invented or silently substituted.

The project label `Ultra` maps to the strongest reasoning variant a saved
configuration advertises, currently `reasoning_effort: "max"`. The model ID is
always the one saved by the operator and is never replaced with a different ID.

Keys submitted in the local password field stay in backend memory. Responses only
say whether a key exists. Nonsecret settings persist; restarting clears the session
key. `REACHSCOPE_AI_API_KEY` may be configured explicitly in the server environment.
Credentials are bound to the selected provider and normalized API base. Changing
either clears a session credential and blocks environment fallback for that run;
the old key is never forwarded to the newly selected endpoint. Environment keys
are bound to the saved startup profile. Clearing the key also blocks environment
fallback until restart. Supply a new explicit key for a different provider.

Public bases cannot include credentials, query strings, fragments or completion
paths. Local loopback requires an explicit option; DNS is checked and pinned,
redirects are not followed, TLS remains enabled, and calls have bounded time and
response sizes without automatic retry.

### Provider capabilities in 0.10

`GET /api/ai/providers` supplies the UI presets. As checked in the official
DeepSeek API documentation on 2026-11-01, the current listed models are
`deepseek-flash` / `deepseek-v4-pro`, with `none/low/high/max` reasoning choices.
The server does not silently replace an operator's existing model.
`reasoning_effort: "default"` omits that parameter rather than forcing GPT's
strongest setting on every provider. Account/model capability still needs a real
provider acceptance; a preset is not proof of model entitlement or quality.

DeepSeek uses `max_tokens`; the OpenAI preset uses `max_completion_tokens`.
Custom compatible endpoints can explicitly choose either field. The application
sets a **4096 output-token request budget**, not the provider's maximum capacity.
This is Chat Completions compatibility, not native Anthropic/Gemini/Ollama support
or a guarantee that every service exposing a similar URL supports JSON output.

`POST /api/ai/diagnose` accepts optional `provider_id`, `base_url`, `allow_local`.
It validates and probes the actual draft address without saving settings, sending
a key/evidence, or calling a model. DNS and connection share a 10-second deadline.
HTTP 401/403/404 can prove a host answered but not that the protocol, authentication,
balance or model works. Redirects, certificate bypass and automatic paid retries
are not used. The original supplied gateway currently fails at the connection
stage even for an unauthenticated GET; successful commercial inference is unverified.

The preview contains task/asset/evidence IDs, URL origins, reachable/status values,
known check IDs/states, execution state and capture completeness. URL paths and
queries, page/body/source content, raw headers, Cookie/form values, upload files,
authorization notes and API keys are excluded. Target data is untrusted data, not
system instructions. The envelope is capped at 64 KiB.

Only completed asset-bound **website probes** with a successful saved response are
eligible. Imported scans, synthetic demos, cloud service-address jobs and Android/
cloud configurations are rejected by this pilot. Future adapters need their own
minimization and acceptance tests.

The model returns only `red` and `blue` arrays of known `control_id`, priority and
known `evidence_ids`. Unknown IDs, arbitrary prose/commands, duplicates, invalid
structures, refusals and tool calls are rejected. The server renders catalogue
text. `web_config` means saved response checks; `manual_review` and
`endpoint_hygiene` remain human topics and are never reported as observed findings.

## Verification labels

Unit tests use deterministic fake providers. Local HTTP/browser acceptance uses a
controlled compatible-protocol fixture and must be labeled as such. No commercial
model is verified until an operator supplies an appropriate key and records a
separate request. See [project status](../../releases/project-status.md),
[public references](../../reference/defense-references.md) and [ADR 0004](../../architecture/adr/0004-ai-evidence-advisory.md).

Protocol references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[DeepSeek request schema](https://api-docs.deepseek.com/api/create-chat-completion/),
[DeepSeek models](https://api-docs.deepseek.com/quick_start/pricing/).


## 0.11 layered checks and deterministic guides

`GET /api/ai/config` includes a nonsecret configuration hash. The separate
`POST /api/ai/diagnose/models` requires `{configuration_sha256, consent:true}`
and snapshots only that matching saved profile/key. It sends one bounded GET /models,
not evidence or inference. Stale settings, missing consent and draft address overrides
are rejected. Only selected-model visibility true/false/null and safe fixed statuses
are exposed; a partial catalogue preserves unknown. A directory response does not prove
actual inference permission, balance, output quality or that a compatible server truly
validated the supplied key. Raw directories/errors are neither returned nor stored.

Successful asset-bound website collections can read `GET /api/jobs/{id}/controls` and
`GET /api/jobs/{id}/controls/{control_id}/guide?environment=generic|nginx` **without AI**.
Only executed checks and known evidence support the list; pass/review/unknown and
not-applicable states are preserved. The guide does not create findings or close cases.
Completed AI reports can access the corresponding selected-control guide through
`GET /api/advisories/{id}/controls/{control_id}/guide` as well.

Manual guides provide prerequisites, evidence links, red review questions, blue steps,
verification, rollback and acceptance. Nginx is an explicit user selection, not detected
stack; the five reviewed snippet types were not deployed against a real Nginx instance.
The local training origin is preserved in context/guides, not presented as production.
See [local lab](../../getting-started/local-lab.md) and [ADR 0005](../../architecture/adr/0005-local-teaching-and-request-contracts.md).
