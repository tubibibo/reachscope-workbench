# Blue-team implementation record — 0.13

Started: 2026-11-02. Baseline: 0.12.0, schema 6.

## Approved scope

The operator approved a defensive main workflow: first read-only host configuration
baselines and limited offline log analysis, then evidence review and remediation.
Android, Web and cloud keep their existing inputs and immutable histories.

1. Add an independent host module using the existing saved-asset/task/evidence
   ports. Accept explicit host identities and bounded local input files.
2. Review exported OpenSSH effective configuration and supplied Nginx configuration
   dumps. Unresolved context/includes/defaults remain unknown. Never connect to a
   host, execute its commands or change its settings during import.
3. Parse limited Nginx access and SSH authentication logs. Keep UTC timestamps,
   line references, event classes and actor aliases; exclude raw request targets,
   query tokens and usernames from saved results. Indicators are review tasks,
   not confirmed intrusions or a live monitoring claim.
4. Connect known baseline rules to evidence-bound cases and explicit revised
   file retests. A finite log sample without a match cannot close a case.
5. Verify positive, normal, unknown, malformed and privacy cases; exercise actual
   API/UI workflows, historical compatibility and a clean installed package.

## Boundaries

This iteration adds no remote shell, endpoint agent, automatic blocking, cloud
credentials, commercial model request or production multi-user SOC claim.
The existing real-provider deferral remains in effect. Uploaded originals remain
local inputs; result/export minimization does not make original files anonymous.

## Verification

Implementation is complete for the bounded 0.13.0 scope, with schema 7. The final
complete source gate passes **1,835 tests**, with **1 skipped** and **1 upstream
warning**, at **92.54%** coverage; pytest took **194.27s**. Ruff and strict mypy
over **118 source files** also pass. Component runs overlap this complete gate
and are not added to its total.

The isolated browser orchestrator passed six groups and **61 checks** before the
late Nginx truncated-fact retention correction. After that correction, the affected
blue-team group was rerun and passed all **9 checks**, including actual uploaded
configuration/log inputs, selected execution, privacy, immutable evidence and
manual remediation. This is an affected-group final rerun, not a claim that all
six groups were rerun after the correction. Desktop/mobile evidence is retained
under `outputs/workbench-0.13/` in the delivery workspace.

The corrected final wheel was installed in a fresh environment outside the
checkout. Isolated imports/version, four modules, uploaded host baseline and log
workflows, retained cloud/teaching acceptance and actual loopback HTTP static
bytes all pass. **145 runtime files**, including **118 Python files**, match its
clean source export. The earlier package candidate predates the late correction
and is explicitly not the final artifact. Real commercial inference remains
deferred; no commercial model request or remote GitHub CI run is claimed.
See PROJECT-STATUS.md and WORKBENCH-VALIDATION.md for final evidence and the
separately recorded real-workspace upgrade status.

## First use

Choose 主机防御 in the asset wizard. For a first walkthrough select the explicitly
synthetic demonstration. To review your own host, select a configuration or log
profile, enter a stable host label and upload the relevant local file. Nothing
uses that label as a network target. Keep it identical for related revisions.

The configuration profile accepts UTF-8 JSON (at most 2 MiB), with each embedded
export at most 256 KiB:

```json
{
  "schema_version": "reachscope-host/1",
  "host_id": "srv-web-01",
  "collected_at": "2026-11-02T00:00:00Z",
  "ssh": {
    "connection_context": "global",
    "effective_config": "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"
  },
  "nginx": {
    "config_dump": "http { autoindex off; server_tokens off; server { listen 443 ssl; server_name example.invalid; ssl_protocols TLSv1.2 TLSv1.3; } }"
  }
}
```

This is a format example, not an observed host. The UI downloads this template.
Replace the sample identity, supplied collection time and text with your own
authorized exported material. Do not edit or publish a production private key.
An administrator can obtain effective OpenSSH configuration with the installed
server's `sshd -T`, and a Nginx dump with `nginx -T`; the workbench never runs
these commands. If different `-C` connection contexts are exported, use separate
explicit context labels and do not compare them as the same scope. An omitted
SSH context cannot support an automatic not-observed assessment.

Nginx may reference additional files. Only file sections actually present in the
provided dump can resolve includes. Missing, relative or dynamic includes remain
unknown; no file is read from the workstation by following a target path.

## What the ten rules mean

| Group | Rule | Stated review condition |
|---|---|---|
| SSH | root_login | Provided declaration does not explicitly disable direct root login |
| SSH | password_auth | PasswordAuthentication is explicitly enabled |
| SSH | empty_passwords | PermitEmptyPasswords is explicitly enabled |
| SSH | max_auth_tries | Supplied MaxAuthTries exceeds the local review threshold of four |
| Nginx | autoindex | Directory listing is explicitly enabled in a reviewed context |
| Nginx | server_tokens | The reviewed version-token declaration is not off |
| Nginx | tls_protocols | Reviewed TLS protocol declaration includes a legacy protocol |
| Web log | http_auth_burst | Ten 401/403 events per actor in one fixed UTC five-minute bin |
| Web log | http_5xx_burst | Five 5xx events across the supplied host sample in one bin |
| SSH log | ssh_failure_burst | Five recognized authentication failures per actor in one bin |

These are bounded, original review policies, not a complete standard-compliance
assessment. A missing directive does not automatically mean its unsafe value.
Nginx HTTP contexts without an explicit TLS listener are not treated as observed
TLS endpoints. Valid declaration checks still require real deployment/business
verification. SSH password authentication is distinct from all PAM/interactive
authentication mechanisms.

## Log input and privacy

Use `.log` or `.txt`, at most 2 MiB. Nginx common/combined records and limited
OpenSSH Failed/Accepted messages are supported. Explicit numeric timezone and
year are needed for time-window analysis. RFC3164 records without them can be
recognized but keep unknown timestamps; the tool never fills in the current year.
Custom log formats and unrelated SSH session messages may remain unparsed.

Limits: 10,000 examined lines, 5,000 returned events, 100 alert windows, 200 line
references per window. Duplicate rows, unknown time, invalid address, long lines,
unsupported records and truncation remain in coverage counters. Fixed bins do
not implement a sliding-window or continuous intrusion detector.

Results retain format-qualified event IDs, source line numbers, normalized UTC
time, event class/status and input-scoped actor aliases. Raw IPs, usernames,
request targets/queries, referrers, user-agent strings and original lines do not
enter saved results. Aliases are pseudonyms, not an anonymity guarantee. Original
uploads remain local files and may contain sensitive material; do not commit or
publish them. Logs are not sent to a model by this module.

## Remediation and limits

Only the configuration rules can support a not-observed assessment. A revision
must be explicitly associated, retain the same declared host/context identities,
provide complete evidence and known nondecreasing collection timestamps. These
timestamps and host labels are operator-supplied, not authenticated runtime proof.
The human then records a note and closes the case using the existing CAS/audit
workflow. Log silence, missing contexts, parse failures and unknown fields cannot
stand in for a successful fix.

Schema 7 marks new host semantics and refuses older applications. Before upgrading
a real workspace, stop its owning server and retain a verified backup. For rollback
use the matching older workspace backup, never force a version number downward.
