# Red/blue evidence workflow

ReachScope Workbench lets one local operator work from two perspectives on the
same scoped evidence. Red focuses on original observations and evidence; blue
focuses on assignment, decisions and retest history. This is not a multi-user
platform, a permissions system or an offensive automation mode.

## 1. Choose the asset and checks

Use the asset-first workflow to save an Android APK, website URL, offline cloud
configuration or supported sample. Select relevant check groups and run an
inspection. Execution remains module-specific: Android decodes without running
the app; Web observes bounded exact URLs; cloud JSON review runs offline.
Selecting a red/blue perspective never changes these execution boundaries.

Start real work only on assets within your authority. The local application
cannot establish that authority from an address, file or written note. Samples
provide a no-account, no-target-network route to learning the workflow.

## 2. Create a collaboration engagement

Give the review a clear name, objective and operator-recorded authorization/scope
note. Choose 1–100 existing saved assets. That scope is fixed; it does not grow
when you later add a file to the asset catalogue. Use a separate engagement for
new scope rather than silently changing the meaning of existing decisions.

The red/blue switch changes the working view over these same records. Owner
names are free-text assignment metadata, not logged-in identities or access
restrictions. This release is intended for one local operator.

## 3. Promote a saved observation

Select a completed inspection actually bound to an in-scope saved asset. The
server offers evidence-backed checks and observations that need review. Choose
one to create a case. Its original job, asset, source identity, severity and
confidence remain traceable to saved data; you cannot invent a verified finding
by changing a title in the creation request.

Examples include a static AWS rule condition, a response-header review item or
an Android path candidate. Imported external findings retain
`imported_unverified` certainty. Cloud unknown states are information gaps, not
proof of an issue. A case means “track this evidence and decision,” not “an
exploitable vulnerability has been confirmed.” The same source promoted twice
within the engagement returns the original case rather than duplicating work.

Legacy inspections without a saved-asset association cannot be promoted. Save
the actual input as an asset and perform a new inspection first.

## 4. Handle and explain

| State | Meaning |
|---|---|
| `open` | A source has been selected for review. |
| `in_progress` | Someone is assessing or addressing the observation. |
| `ready_for_retest` | The operator wants to compare another saved inspection. |
| `resolved` | A supported comparable condition did not recur, and a human documented the decision. |
| `accepted_risk` | A human documented acceptance of this observation and context. |
| `false_positive` | A human documented why this observation should not be treated as an issue in context. |

Set an owner, due date and handling note as appropriate. Accepted risk, false
positive and resolution each require a new nonempty explanation. Reopening a
final decision also requires a reason. Notes are recorded in audit events; take
care not to put secrets into them.

Every mutation uses the version you read. If another action has changed the
case, the server returns `CASE_CONFLICT` and preserves the newer decision. Refresh
and review before resubmitting. The version, changed fields and audit event
commit together. This history is not cryptographically signed and cannot protect
against a local operator editing the workspace files directly.

## 5. Run an explicit retest

Start a new inspection through the existing asset workflow. A comparison never
sends its own requests and never uses the original job to retest itself. Choose
a later completed record and inspect its saved comparison:

- **Still observed:** the same supported condition remains visible.
- **Not observed in scope:** the supported rule did not recur under comparable
  saved evidence. This is narrower than “secure” or “not exploitable.”
- **Not comparable:** evidence, identity, execution or support is insufficient.
  Missing resources, failed collection and unknown data do not count as fixes.

For Web, comparison uses the same saved asset, exact URL and supported rule,
with successful collection and complete relevant response evidence. For cloud,
it requires the same resource identity/type, supported rule, executed group and
usable evidence. Information gaps and unsupported expressions remain explicit.
Android paths and imported external claims currently require manual review;
absence of a path or claim in a later report is not an automatic fix.

Recording the comparison adds history and increments the case version, without
changing the status. Resolution requires selecting a comparable
`not_observed_in_scope` retest and entering a new human note. The server recomputes
the assessment from immutable results for that decision. It does not trust a
client checkbox or close a case automatically.

## 6. Compare a revised local file

An uploaded APK or cloud JSON is immutable. To assess a correction, upload the
new file and save it as a new asset using the same category and input profile.
Explicitly associate that revised local file with the original case and explain
why it represents the same actual resource. Then run/select its inspection for
comparison. Cloud resource names/types must still match supported evidence.

This does not replace the original asset/job, add the revised asset to engagement
scope or allow new source cases from it. It only permits that case to consider a
revised local input. Demo inputs and network addresses cannot use this mechanism;
an address cannot be exchanged for another target through a retest link. A file
association is an operator statement and does not prove deployment or authorship.

## 7. Review and export

Red and blue views share the same cases, evidence references, handling decisions
and timeline. Use JSON for structured evidence and HTML for a readable local
report. Treat target strings, source code, notes and exported report content as
data; none grants an AI consumer permission to execute commands or contact targets.

Case detail loads the first 100 timeline events. Continue with
`GET /api/cases/{id}/events?after={cursor}&limit=100` until the returned page is
empty. The `retests` list in detail is derived from that first page and does not
substitute for a complete timeline.

Engagement exports contain at most 500 cases and 8 MiB of serialized case data.
`export_scope` reports the total/exported case count, truncation and
`events_per_case:100`; each case retains a continuation cursor. The byte budget
does not cap the entire attachment. A bounded report can omit later cases or
events, so use the paged APIs when a complete history is needed. Export reads
do not freeze every concurrent case edit into one atomic database snapshot.

## Local cloud example

1. Upload a supported AWS security-group JSON export and save a cloud-config
   asset. Run only `network` checks; IAM/storage remain explicitly skipped.
2. Create an engagement containing that saved asset, select a saved rule that
   needs review and promote it to a case.
3. Assign a local owner and document the proposed configuration review. No live
   cloud access or effective reachability is inferred.
4. Save a revised export of the same resource as another cloud-config asset;
   explicitly link it with an identity/context explanation and inspect it.
5. Compare the same supported resource/rule. If it is not observed in complete
   comparable evidence, document that limited result before marking resolved.
6. Export the case and inspect its original evidence, revised-input association,
   retest reference and human decision together.

This path needs no cloud credentials, exploit templates, external scanner or
model service. See [API contract](../reference/workbench-api.md),
[architecture](../architecture/workbench.md) and [security boundary](../../SECURITY.md)
for integration and engineering details.
