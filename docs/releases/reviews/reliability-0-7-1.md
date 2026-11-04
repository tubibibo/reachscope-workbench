# Interface and engineering review — Workbench 0.7.1

> 历史记录：正文中的实际执行命令、版本、哈希和证据路径保留当时原样。当前目录与命令见 [仓库结构规范](../../development/repository-layout.md)；路径迁移表见 [path-migrations.json](../../../config/path-migrations.json)。

Reviewed locally on 2026-11-01. This maintenance iteration targets ordinary
operator failures and verifiable defects, not additional scanning breadth.
Passing tests does not prove that arbitrary inputs or environments are bug-free.

## Reproduced defects and fixes

| Trigger | Previous behavior | Change and regression |
|---|---|---|
| Server commits an asset/job but its response is lost | Retry could create a duplicate asset or inspection | Durable request-key tables, normalized request fingerprints and atomic create-or-replay; browser deliberately drops successful responses, then retries |
| Reuse the same key with a different input/check selection | No operation identity contract | Explicit 409 `IDEMPOTENCY_CONFLICT`; no extra record |
| Saved file is deleted, replaced or unreadable | Problem discovered after starting an analysis | Local preflight checks existence, normal file path, size and SHA-256; blocked inputs create no new inspection |
| Original task exists, then its input becomes unavailable | A client preflight could prevent retrying a completed submission | Server replays before readiness; client reuses an already-sent key without a new client-side readiness gate |
| Browser cancels a superseded request | Cancellation became a generic network error | Preserve AbortError/aborted-signal semantics |
| Reuse runner across starts/event loops | Stopping flag and old queued IDs could persist | Reinitialize loop-bound state and restore durable queued rows exactly once |
| Progress callback reports a smaller number | Job row stayed monotonic but journal could regress | Journal and row use the same nondecreasing progress |
| Repeated cancellation after a lost response | Already-cancelled job returned terminal conflict | Cancelled replay returns the same job without another event; completed/failed jobs still reject cancellation |
| Open a future-version workspace | DDL could run before rejecting the version | Inspect metadata before changes; migration runs transactionally and rolls back on failure |
| Start a second server against an owned workspace | Migration could run before the lifespan lock | Acquire a short exclusive lease for initialization/migration, then hold it for the running lifespan |
| Concurrent insert between count and page reads | Count and returned page could describe different snapshots | Consistent SQLite read transaction |
| SQLite waits for another writer | Synchronous HTTP command could block health/progress requests | Threaded database work with event-loop-owned task/queue operations; exercised with an actual competing write transaction |
| Imported status `²00` | `isdigit()` accepted it but `int()` failed | ASCII HTTP status parsing; retain record with explicit import warning |
| Lone Unicode surrogate, duplicate file keys, NaN or excessive nesting | Storage/encoding could fail late or data could be reinterpreted | Bounded request/file contracts and explicit validation/parse errors; validation field locations are sanitized too |
| A Location header exceeds captured-header budget | Followed a truncated URL that the server never sent | Keep captured evidence but stop instead of following an invented destination |
| Compressed HTML plus page inspection | Header checks were incorrectly marked inapplicable when page parsing was skipped | Determine header applicability from response metadata independently of page decoding |
| Invalid/non-text response charset | Could misclassify a received response as a connection failure | Bounded UTF-8 fallback; actual body-incomplete errors remain failures |
| Standalone IAM policy evidence | Pointer referred to an internal wrapper field | Pointer now identifies the uploaded document's real root |

## Interface changes for ordinary use

The preferred command is now
`POST /api/assets/{asset_id}/inspections {checks,name?,options?}`. The server derives
the module and input from the saved asset; a caller cannot accidentally pair the
right asset label with another target configuration. Existing `/api/jobs` callers
remain supported, including their original immutable input binding checks.

`POST /api/assets/{asset_id}/preflight` has the same body but creates no job and
sends no target traffic. It returns readiness, named blocked/warning conditions,
normalized dependencies, network behavior and budgets. APK checks can report
missing Java/Apktool before queueing. Cloud samples need no account or credentials.
Preflight is a readiness observation, not a guarantee of valid file contents,
future file/environment stability or successful network/analysis execution.

`Idempotency-Key` is optional on asset creation, job creation, asset inspection and
retry. It is persisted for the lifetime of the corresponding record/workspace.
Reuse the same key only when retrying the same logical request. New inputs or a
new intended inspection require a new key. The UI preserves keys and successful
upload metadata while recovering within the current wizard session. Closing the
wizard or refreshing the page does not provide a cross-session pending-command
journal; inspect history before intentionally starting another inspection.

Public failures contain a bounded error code/message, `request_id` and `retryable`.
The same request ID is in `X-Request-ID` and server request logs. Request validation
does not echo the submitted body or private input values. Unexpected exceptions
return a generic public failure and retain diagnostics in local logs. SQLite busy
responses use 503 and Retry-After; reuse the original key when retrying a write.

## Engineering assessment

- **Boundaries:** HTTP contracts/errors are separate from the application use case
  (`core.inspections`), persistence and independent analysis modules. No module
  imports the API or another module. Architecture regressions enforce direction.
- **Invariants:** A job binds to actual normalized input; evidence describes the
  selected execution; terminal state does not revert; duplicate commands reuse the
  original operation; unknown cloud values never become invented confirmations.
- **Concurrency:** Database writes are atomic, request replay is tested under
  multiple threads, and queues/coroutine cancellation remain on their owning loop.
  Scope stays a local single-operator service, not a distributed scheduler.
- **Inputs and budgets:** Request/file limits, parser depth, result bounds, target
  restrictions and finite-number/Unicode checks are explicit. They are not an OS
  sandbox or proof against every hostile decoder/file input.
- **Verification:** Focused positive/near-miss/error regressions accompany fixes;
  real browser and installed-package paths supplement type/lint/coverage checks.
  Test counts include the retained engine and do not measure vulnerability accuracy.
- **Maintenance:** Sources, dependencies and notices are retained; built frontend
  assets are generated, source distributions include tests/CI/docs, and releases
  are rebuilt from a clean Git export rather than stale build caches.

The code follows these scoped engineering practices; that is an evidence-backed
assessment, not certification or a blanket claim of production readiness.

The review deliberately extended beyond tests that were already green. A real
database lock reproduced the blocked-health defect before the async fix. Final
regression also surfaced a Windows artifact-directory publish refusal; the fix
uses a short bounded retry for specific transient Windows sharing/access codes,
keeps atomic publication/verification and still reports persistent permission
failures rather than ignoring them.

## Remaining scope and operational limits

The observed test environment is Windows. Windows/Linux CI is configured but no
remote run is claimed. Live public-target HTTPS behavior, large real-world APK
corpora and cloud-account access are not established by local fixture checks.
Unrecoverable disk/database failure can still prevent durable task progress or
completion; no automatic queue supervision or blind re-execution is introduced.
Stop the service, inspect the correlated logs and restore a valid workspace before
retrying such failures. Keep the workspace on a local writable disk with free space.

Uploads and evidence remain local until the operator manages retention. An upload
whose successful response is lost may leave an unassociated file; this release
does not implement resumable/deduplicated upload transport or automatically erase
potentially important operator data. Secrets in original uploads are not erased by
masking result evidence. A configured decoder is trusted local executable code.

The service has no multi-user authentication, public hosting model or live cloud
account connector. Those require separate threat models and acceptance criteria.

## Primary implementation references

- [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Python sqlite3 transaction control](https://docs.python.org/3/library/sqlite3.html#transaction-control)
- [MDN AbortSignal](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal)

These sources informed implementation semantics. No upstream framework source was
copied for these fixes; dependencies retain their own notices.
