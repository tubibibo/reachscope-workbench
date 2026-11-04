# Web response review and historical comparison

Workbench 0.6 adds useful follow-up work to bounded URL probing. It reuses the
already captured response rather than discovering or requesting more paths.

## Workflow

1. Create a Web URL probe with the exact HTTP(S) URLs to observe.
2. Inspect the asset inventory and select an asset to read its response evidence.
3. Open **配置检查**. Filter by status/asset, expand an item and read its values,
   recommendation and original evidence. A passing item describes that rule only.
4. Open **页面画像** to inspect metadata, forms and resource references. The tool
   neither loads these references nor submits forms or executes inline scripts.
5. Repeat a probe after a deployment or configuration change. Open **历史对比**
   and select the earlier completed URL probe as the baseline.
6. Export JSON for exact structured data, HTML for a saved report, or Web asset CSV
   for inventory review. History/results survive server restart.

Imports and offline examples remain useful inventories, but do not acquire live
response checks or qualify as a historical probe baseline. Older 0.5 results remain
readable; missing new fields are explicitly unavailable rather than reconstructed.

## Response checks

The check contract is a stable rule ID, title, status, severity, description,
recommendation, structured evidence and the source asset's evidence ID. States:

| State | Meaning |
|---|---|
| `pass` | The saved response meets this particular rule's conditions. |
| `review` | The observed configuration warrants review for this application's use. |
| `info` | Information or an evaluation/collection limitation. |
| `not_applicable` | This check does not apply to the captured response. |

Checks cover basic CSP/frame protection, nosniff, referrer policy, HTTPS HSTS,
CORS configuration, Cookie attributes, password forms, mixed content and available
TLS certificate expiry metadata. They are configuration checks with limited context,
not exploit validation, a complete CSP parser or proof of overall safety. A CORS
header's absence is not itself a defect; an external script is an inventory entry,
not automatically a finding. Imported scanner results retain their existing
unverified confidence label.

Header interpretation follows the official references for
[CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy),
[frame-ancestors](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors),
[HSTS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security),
[CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Access-Control-Allow-Origin)
and [Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).
For example, HSTS is not applied to HTTPS IP-literal hosts; a wildcard CORS origin
with credentials is a conflicting browser configuration rather than proof of data leakage.

## Page and Cookie capture

The HTML parser consumes at most the existing 512 KiB captured-body budget. It
does not expand unexpected compressed responses and skips non-HTML/binary content.
It records language, description, canonical/base URLs, form methods/actions,
password-field counts/input names and script/style/image/link references.
HTTP(S) references have userinfo/fragments removed. Other schemes are omitted.

Inventories retain at most 80 entries per resource kind, 30 forms, 40 input names
per form and bounded strings. Counts describe observed markup, not loaded network
resources. Truncation remains explicit. JavaScript-generated DOM, external form
association and full browser parsing semantics are not implemented; absence from
this inventory does not prove absence from the rendered application.

Cookie processing handles separate Set-Cookie fields without splitting Expires
dates on commas. It retains at most 50 Cookie attribute records: name, domain,
path, Secure, HttpOnly, SameSite, Partitioned/prefix and persistence metadata.
Values and raw Set-Cookie headers are not stored. Invalid/over-limit capture is
marked incomplete. Form inventories omit control values; the local raw response
preview is still response evidence and may include other page content.

## Comparison semantics

`GET /api/jobs/{current}/compare?baseline={previous}` reads saved results only.
It aligns exact normalized input URLs, including paths and queries. It compares
status/title/server/IP/final URL, recorded headers and redirects, compatible full
body hashes, TLS metadata, common check statuses and available page/Cookie metadata.

- Added/removed URLs describe the tasks' input sets, not server launch or shutdown.
- A failed request in either round is `not_comparable`, with connectivity changes
  retained as observations rather than interpreted as fixes.
- Partial bodies, differing content encodings and missing hashes are not hash-compared.
- Old fields, new-only rules and incomplete resource/Cookie collections are skipped
  with notes. Resource ordering alone is not a change.
- No change means no difference in the compared fields. Dynamic responses, time,
  load balancing and collector limitations can influence what is observed.

Each row retains evidence IDs from both jobs; current and baseline results remain
unchanged. This is an inspection tool, not a remediation verdict.

## CSV view

CSV has fixed inventory columns and a UTF-8 BOM. All cells are quoted. Text with
common formula prefixes (including normalized full-width forms and leading
whitespace) receives an apostrophe prefix. That transformation is intentional;
the JSON export preserves original strings. Spreadsheet applications can rewrite
these protections on resave, so the view does not promise universal spreadsheet
safety. See the [OWASP CSV Injection guidance](https://owasp.org/www-community/attacks/CSV_Injection).

## Reproduce the workflow

Start the local workbench, install optional `.[ui]` dependencies and run:

```powershell
.venv\Scripts\python scripts\verify_web_upgrade.py --base-url http://127.0.0.1:8765 `
  --browser 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' `
  --out data\web-upgrade-validation
```

The script serves a temporary loopback fixture, creates two real probe jobs and
checks both API data and UI behavior. Tasks stay available for inspection; the
fixture is stopped at the end. Use a development workspace for repeated runs.
