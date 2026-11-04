# Case sources and saved-result retesting

The red/blue workspace consumes analysis evidence already saved by the Android,
Web and cloud modules. It does not run an exploit, promote an external claim to a
verified finding or silently close a remediation case.

## Sources are bound to completed inspections

`core.case_sources` is a pure data layer with no HTTP, database or concrete module
imports. `candidates(job)` requires a completed supported job with a saved asset.
Older unassociated records remain readable but need a new asset-bound inspection
before becoming tracked case sources.

Structured candidates precede generic observations:

- Cloud check states `review` and `unknown` become candidates. Their confidence
  remains `static_config`; unknown describes insufficient data, not a finding.
- Web structured `review` checks become `observed_config` candidates. Matching
  derived observations are suppressed so the same response rule is not added twice.
- Generic observations retain their actual confidence. External scanner reports
  remain `imported_unverified`; Android static inference is not runtime verification.
  Fingerprint hints and capture-budget information are not offered as separate cases.
- Android `android_attack_surface` observations may become manual review cases
  when the saved module summary records a positive exported-component count. They
  retain `severity:info` and their original `observed` confidence: exported entry
  configuration is not an exploitable vulnerability. Zero-exported summaries remain
  visible context without generating a risk case. Other informational Android
  categories remain excluded; these entry observations cannot auto-pass a retest.
- Every candidate must reference evidence IDs actually present in its source result.

The source shape includes `source_ref`, `source_kind`, title, severity, confidence,
asset/job IDs, evidence IDs, description, recommendation, category and a locator.
Structured candidates additionally carry their original check status. The reference
is an opaque `src-` plus a SHA-256-derived 32-hex identity. Locators are canonical
JSON, avoiding ambiguities from resource names that contain delimiter characters:

```json
{"type":"cloud_check","resource_id":"aws_security_group.main","check_id":"network.public_sensitive_ports"}
```

Web check locators use the exact saved input URL and stable rule ID. Generic
observations retain their source observation ID/category and an unambiguous saved
URL where available. Callers never parse references or submit a replacement title,
severity or fabricated evidence. `source(job,kind,ref)` reconstructs a current
candidate from the saved result and rejects an unknown/ambiguous source.

## Three retest outcomes

| Outcome | Meaning |
|---|---|
| `still_observed` | The corresponding completed rule still explicitly reports the reviewed condition. |
| `not_observed_in_scope` | The same supported rule did not observe the prior condition under its documented captured/static scope. |
| `not_comparable` | There is insufficient common identity, execution, collection or rule meaning to compare. |

`compare_retest` returns the original and retest job IDs, outcome, reason, matching
rule/record, retest evidence, `input_revision` and limitations. It modifies neither
saved job nor any case state. A human decision and application-level transition
rules remain necessary to resolve a case. Observation absence alone is never a fix.

Common prerequisites are a distinct completed retest, the same module and the same
saved asset. The application separately requires a later inspection timestamp.
The corresponding check group must have completed in both records. Missing groups,
old collector fields, failures, missing evidence and ambiguous matches cannot be
interpreted as success.

### Cloud

Match the original resource address and stable rule ID, with the same known resource
type and supported inventory entry. A resource absent from the next file might be
omitted or replaced; it is not considered remediated. Original `unknown` cases
remain non-comparable: new information is not a before/after observed condition.

A repeated `review` is still observed. `pass` may mean not observed for that rule.
The narrow IAM broad-Allow/trust-principal and S3 policy-principal rules use `info`
for a parsed non-hit, so those known IDs can be not observed in scope. This does
not evaluate effective permissions, external policy intersections, deployment
state or least privilege. Other generic info, unknown and not-applicable states
are not comparable. Remaining unknown statement/rule fields block a success result.

### Web

Match the exact normalized input URL and rule ID, not a job-specific evidence ID or
page title. The retest must obtain a successful response and execute the applicable
header/page group. `review` means still observed; only an explicit `pass` can mean
not observed. Information or inapplicability does not mean the previous condition
was repaired. Incomplete original/new header, Cookie or page capture blocks a
success interpretation; partial evidence can still show a positive repeated hit.

The cleartext-HTTP observation has a small special case: a completed response to
the same original HTTP URL that reaches HTTPS within the existing scope can mean
not observed in scope. A failed, stopped or unrelated redirect cannot. Imported
scanner reports and general Android source observations have no automatic retest
correspondence in this release and stay not comparable.

## Explicit local input revisions

Saved asset input is immutable. A revised local cloud configuration therefore has
another asset ID. The application may explicitly record a same-kind/profile local
file revision, with a reason and audit trail, and pass its authorized IDs through
the keyword `related_asset_ids`. The pure comparator accepts only an explicitly
listed related Android/cloud asset; network/Web targets cannot borrow file-revision
authorization. Stable resource/rule/type prerequisites still apply.

Such an outcome has `input_revision:true`, preserves the actual IDs and says that
the same actual resource identity still needs confirmation. Similar names, addresses
or the mere relationship record do not prove deployment identity. Generic Android
static observations remain not comparable even when a revised APK is linked.

## Boundaries

There are no new network requests or external tool calls in this layer. Source
strings and saved code/response contents remain untrusted evidence, never
instructions. Case workflows preserve immutable source provenance rather than
rewriting old inspection results. Future rule IDs/collector versions must define
their comparability explicitly before gaining a successful retest outcome.
