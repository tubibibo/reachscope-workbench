# Security model

## Security assessment records

The 2026-11-02 review and fixes are recorded in
[`docs/security/security-test-log-2026-11-02.md`](docs/security/security-test-log-2026-11-02.md).
It separates reproduced application defects, dependency advisories, hardening,
passing controls and unexecuted scope. Public fixtures use isolated workspaces
and synthetic data; detailed private logs must never include operator secrets.
No scan or test result establishes absence of unknown vulnerabilities.

## Workbench local service (0.9.0)

The application binds to 127.0.0.1 and is intended for one local operator. There
is no account or public-service deployment model. Host validation, same-origin
write validation and `X-ReachScope-Client` protect the browser-to-local boundary;
they do not authenticate another process running as the operator. Do not expose
this port through a public reverse proxy.

Web probe mode sends bounded GET requests to explicitly supplied HTTP(S) URLs.
It validates/pins DNS results, preserves Host/TLS SNI, disables proxy environment
variables, enforces redirect scope, validates certificates and caps concurrency,
deadlines and captured bodies. Private ranges require an explicit setting;
metadata/link-local and other excluded endpoints remain blocked. File imports
and samples do not send probes. Missing response headers and rule paths are
observations, not proof of a vulnerability.

Response inspection parses only the bounded body already captured. It does not
load scripts, styles, images, links or submit forms. Cookie analysis records
attributes without Cookie values or raw Set-Cookie headers. Form inventories omit
control values; the existing local raw response preview can still contain page
text. Historical comparisons read saved data only and preserve failed/partial
collection states. CSV export quotes fields and neutralizes common formula
prefixes; spreadsheets can transform this text on resave, so JSON is the exact
data format rather than a spreadsheet security guarantee.

Upload names are metadata; storage uses server-generated IDs. Body/upload budgets
apply and accepted formats are restricted. SQLite state, uploads, logs, artifacts
and generated results are local and may contain sensitive code or response text.
No automatic data-retention deletion is performed. Stop the server before backing
up or deleting a workspace. Only one server can own it at a time.

Saved assets contain normalized input metadata, not credentials. Jobs bind the
asset to their real input and preserve an immutable snapshot. Choosing fewer
checks changes execution rather than merely hiding findings. Offline cloud review
accepts only supported bounded JSON and never calls cloud APIs or runs Terraform.
Relevant evidence fields are allowlisted, Terraform sensitive values are replaced
and unknown values remain unknown. Original uploads still remain local; masking
result evidence does not erase sensitive data from the uploaded source file.

Request identities prevent duplicate creation when a caller reuses the same key
and input; they are not authentication or protection against intentional new
requests. Preflight performs local file/hash/environment readiness only. It sends
no target traffic and cannot eliminate file/environment changes after the check.
Public failures carry request IDs, omit submitted values and hide unexpected
exception details; local diagnostic logs remain operator-controlled data.

Android analysis runs in a bounded worker process; cancellation and timeout kill
its process tree. It decodes but never executes APK code. A configured Apktool JAR
is trusted local executable code and must come from the operator's trusted source.
OS-level disposable environments remain appropriate for hostile binary inputs.

Frontend target strings use React text escaping and report exports escape all data.
The workbench uses local frontend assets and does not require a model account or
external analytics. Inherited engine-specific security details follow.

## Red/blue collaboration boundary

The red and blue views are local workflow perspectives, not authentication,
separate users or access-control roles. Owner names and authorization/scope notes
are operator-entered metadata. A recorded authorization note does not prove legal
authority; scope remains the explicitly selected, immutable saved assets. Another
local process with API/filesystem access can act as the same operator.

Cases are selected from evidence-backed sources in completed, asset-bound jobs.
Missing response headers, static paths, configuration rules and imported scanner
claims remain observations with their original certainty. Promotion to a case
does not verify a vulnerability. Collaboration adds no exploit execution,
credential access, cloud API calls, target discovery or autonomous retesting.

Case updates require an expected version and commit an audit event atomically;
conflicts cannot silently overwrite a newer decision. This is local application
history, not a signed or tamper-proof record against someone controlling the data
directory. Decision notes, names, dates and exported histories can contain
sensitive information and follow the same local retention boundary as evidence.

A resolution requires a human note and a server-computed comparable
`not_observed_in_scope` saved retest. A failed request, missing resource, skipped
check, unknown/truncated value or unsupported comparison is not a fix. Accepted
risk and false-positive states are explicit human decisions, not technical proof.
The tool never automatically closes a case or labels an entire asset secure.

Revised inputs are limited to explicitly linked same-category, same-profile local
APK/JSON files for that case. Links retain original evidence and scope; the
operator must explain the relationship to the same actual resource. They do not
authenticate file authorship, prove deployment or permit substituting network
targets. Case detail/export includes only the first 100 timeline entries with a
cursor; engagement exports declare their 500-case/8-MiB case-data budget and
truncation. Consumers must follow event pagination before treating a history as
complete. See [red/blue workflow](docs/getting-started/red-blue-workflow.md).

ReachScope is a local inspection tool. It does not install or execute target APKs,
send telemetry or contact analyzed hosts unless the operator explicitly starts a
bounded Web probe. Optional AI advisory calls are separate, manual and currently
limited to minimized saved website-probe evidence; they require configured provider
settings, a preview hash, an authorization note and an idempotency key. APK input invokes a
locally installed Java/Apktool decoder. Use a current decoder; archive checks are
not a sandbox. For untrusted samples, run the entire tool in a disposable OS
environment with appropriate resource limits.

Saved evidence contains application code and may contain secrets from that code.
Store it locally with appropriate filesystem permissions. Artifacts are not a
credential store. Content hashes detect mismatches and corruption; they are not
signatures and do not authenticate an artifact supplied by another party.

Input code and strings remain untrusted data. An AI consuming results must never
treat comments, URLs, or other target content as instructions. Tool output is
evidence, not permission to execute suggested commands or contact a target.

AI provider keys are accepted only in backend session memory or the explicit
`REACHSCOPE_AI_API_KEY` environment variable. They are not stored in SQLite,
browser storage, exports or logs. The preview excludes URL paths/queries, page
content, raw headers, Cookie/form values, uploads, source code and authorization
notes. The provider adapter pins validated addresses, rejects metadata/private
targets unless explicitly allowed loopback, disables proxy variables and bounds
time/response size. Model output is allowlisted control/evidence IDs; it cannot
create findings, expand scope, invoke tools, alter inspection selections or close
cases. Failed/interrupted reports are retained and never automatically replayed.

The artifact store bounds file counts and bytes, rejects path traversal and
symbolic links/reparse points, and validates saved content. Code reads recheck
hashes. An artifact's report is a bounded static-analysis result, not proof of
exploitability or completeness. The tool does not resolve all branches, dynamic
loading, reflection, native code or asynchronous execution.

For a vulnerability in ReachScope itself, use the repository's private security
advisory feature if enabled. Otherwise contact the maintainer using the contact
method published on their profile. Do not post exploit details with private APK
data or credentials in a public issue. No private reporting service or response
SLA is claimed by this project.
