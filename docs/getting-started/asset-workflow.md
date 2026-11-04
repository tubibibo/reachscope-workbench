# Asset-first inspection workflow

Workbench 0.7 organizes the product around what the operator wants to inspect.
The internal analysis modules remain independent; a user-facing catalogue maps
asset input profiles to those modules and their executable check groups.

## Four steps

1. **Select an asset type or saved asset.** Android application, website, or cloud
   asset. Saved assets retain inputs so subsequent inspections need no repeated upload.
2. **Provide the input.** Select an APK, enter exact HTTP(S) service URLs, upload a
   supported inventory/cloud JSON file, or use a clearly identified offline sample.
3. **Choose checks.** Recommended defaults are selected. Required dependencies are
   explicit and automatically included. Only compatible executable groups are shown.
4. **Review and run.** Review the asset, selected checks and network behavior, then
   create a real job. Results identify completed and unselected/skipped groups.

Users can go back and revise choices before submission. A new asset is persisted
only when the run is submitted; if queue creation fails after saving it, it can
still be selected for another attempt. There is no automatic resubmission that
could duplicate active work.

## Input profiles

| Asset | Input | Execution |
|---|---|---|
| Android | APK or bundled source sample | Manifest only, or manifest plus static code-path/source indexing |
| Website | Exact URL list | HTTP metadata, optional header/Cookie/TLS review, passive page inventory, fingerprint rules |
| Website | Existing inventory or sample | Offline classification and candidate investigation suggestions |
| Cloud | Exact HTTP(S) service URL | The same bounded Web capabilities, attached to a cloud asset |
| Cloud | Supported AWS configuration JSON or sample | Offline network-rule, IAM-policy and storage checks |

A cloud IP/domain cannot supply account configuration. The external profile never
claims to inspect IAM, security groups or internal cloud state. Use the configuration
profile and provide its required data. No port sweep, credentials or account
connection are introduced. Bare addresses, if normalized by the UI, are reviewed
as a concrete HTTP(S) URL before execution.

## Actual execution

Android `manifest` reads the manifest through an isolated worker without static
graph analysis or a method artifact. `code_paths` depends on it and retains the
existing evidence-query workflow. Method queries on a manifest-only result return
`QUERY_UNAVAILABLE` rather than creating analysis after the fact.

Web `http` is the shared required request stage. `headers`, `page` and
`fingerprints` are independently selected processing stages. Unselected parsers,
audits and classification/path generation do not run. Shared request/body metadata
can still be collected to execute the selected stages. Offline import/sample
profiles run only compatible inventory analysis.

Cloud `network`, `iam` and `storage` call only selected rule groups over normalized
static input. Missing applicable resources produces an explicit coverage note,
not proof that a resource class is secure. Unknown values and unsupported types
remain visible. Every module reports `details.execution` with ID, label, status
and reason. See [cloud module](../modules/cloud/configuration-review.md) for supported formats and rules.

## Persistence and contracts

`core.catalog` provides frontend metadata without importing analysis modules.
`core.assets` stores generated asset IDs, kind, display name and normalized source
metadata. Source fields are allowlisted; arbitrary credentials/path dictionaries
are rejected. Asset input records are immutable in this release; changing input
creates a new asset. Check selection belongs to a job, not to an asset.

Database schema v2 adds `assets` and `job_assets` while preserving existing jobs,
events and uploads. Old jobs have no asset association and remain readable.
Creating a linked job and its input snapshot is one transaction. The runner checks
that the asset kind/profile and real input match the task. Retry preserves the
association and selected checks. Snapshots prevent later input metadata from
silently reinterpreting saved evidence.

Maintenance 0.7.1 adds schema v3 request identities and preferred saved-asset
`preflight`/`inspections` endpoints. They centralize input selection on the server
and allow a client to recover accepted writes by operation key. See the current
[API contract](../reference/workbench-api.md) and [reliability review](../releases/reviews/reliability-0-7-1.md).

Asset summaries/history are paged; on-screen subsets must not masquerade as total
workspace counts. Stored input files remain local under the existing retention
policy. No recursive discovery or hidden uploads occur when selecting a saved asset.

## API

- `GET /api/catalog`: kinds, profiles, check IDs, required flags and dependencies.
- `GET /api/assets?kind=cloud&limit=100&offset=0`: inventory with counts and pagination.
- `POST /api/assets`: `{kind,name,source:{profile_id,...input_fields}}`.
- `GET /api/assets/{id}`: one saved asset and run summary.
- `GET /api/assets/{id}/jobs`: immutable inspection history.
- `POST /api/jobs`: optional top-level `asset_id`, plus existing module/name/config.
  `config.checks` controls actual execution; absent checks preserve old API defaults.

All existing local request boundaries apply. Direct legacy API jobs without
asset IDs remain supported. New UI runs use the persistent inventory flow.
