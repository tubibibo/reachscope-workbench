# CLI and Python query contract

`reachscope index DECODED --store STORE` creates a retained artifact.
`reachscope scan APK --apktool JAR --out OUTPUT` additionally decodes an APK and
writes legacy reports. Scan and demo require a new or empty output directory.
`reachscope artifacts --store STORE` lists validated completed artifacts.

`reachscope query ID TOPIC --store STORE` supports:

| Topic | Arguments | Python call |
|---|---|---|
| overview | None | `session.overview()` |
| entries | `--search`, `--offset`, `--limit` | `session.entries(query, offset=0, limit=50)` |
| chains | `--entry`, `--offset`, `--limit` | `session.chains(entry=None, offset=0, limit=20)` |
| chain | `--id` | `session.chain(chain_id)` |
| methods | `--search`, `--offset`, `--limit` | `session.methods(query, offset=0, limit=50)` |
| method | `--ref`, `--offset`, `--limit` | `session.method(ref, offset=0, limit=80)` |
| check | `--claim FILE.json` | `session.check(claim_dict)` |
| questions | None | `session.questions()` |

CLI list/method default limit is 50; Python method default is 80. Query page size
is 1–100. Offsets are nonnegative. Large chain/check/gap details have explicit
caps and `detail_limits`; method reads over the response character budget return
`OUTPUT_LIMIT` so callers can reduce the line limit. Missing result, unsupported
operation, invalid argument and unavailable/corrupted evidence are distinct states.

New query responses use this envelope (additional fields may be added):

```json
{
  "schema_version": "1.0",
  "artifact_id": "64-character-content-identity",
  "scope": "static_analysis_report",
  "limitations": ["..."],
  "warning_count": 0,
  "data": [],
  "pagination": {
    "offset": 0, "limit": 50, "total": 0,
    "truncated": false, "next_offset": null
  }
}
```

Pagination is present on lists and method reads. Single-object operations return
an object in `data`. Check responses contain `data.verdict` and an interpretation
of report consistency. See [protocol](evidence-protocol.md) for claim schema 0.2.

References such as `ARTIFACT_ID:chain:LOCAL_ID` and
`ARTIFACT_ID:method:Lpkg/Type;->method()V` bind an object to its evidence snapshot.
An unqualified local ID is accepted within the explicitly opened session. A
reference for another artifact is rejected. Source locations use physical smali
lines; they must not be confused with Java `.line` debug metadata.

Operational errors for the new commands are JSON:

```json
{"error": {"code": "METHOD_NOT_FOUND", "message": "..."}}
```

Exit 0 means the operation succeeded, including a returned REFUTED or UNDECIDABLE
verdict. Exit 2 means caller/input/evidence error; legacy scan also uses 3 for an
unanalyzable protected APK and 4 for unexpected internal failure. Argument-parser
usage errors and legacy commands retain their existing textual stderr behavior.
Logs go to stderr. No model vendor-specific schema or SDK is required.

## Versions

The Python package is 0.4.1, report schema remains 0.1, artifact schema is 1,
query schema is 1.0 and claim protocol output is 0.2. These versions describe
different contracts. Unsupported persisted schemas are rejected instead of
silently decoded. Protocol 0.1 claim/answer inputs are accepted; new output is
0.2. Missing report schema is rejected with regeneration guidance.

## Retrieving gaps

Questions are derived from warnings, absent implementations, incomplete steps
and uncertain judgments. An AI's answer does not fill the source snapshot or
prove the answer true. Additional code inspection or external independently
recorded evidence is needed; the current checker treats answers as assumptions.
