# ReachScope Workbench frontend

A local React / TypeScript application for Android, Web, cloud configuration and
offline host review. It does not substitute sample records for API results. The
production bundle is served by the Python application's same-origin HTTP server.

## Development

```bash
npm ci
npm run dev
```

Start the Python workbench on `127.0.0.1:8765`. Vite proxies `/api` to that server;
the proxy preserves the browser's host/origin relationship. Production use needs
only the Python server, because the compiled assets are included in its package.

```bash
npm run check
npm run format:check
npm run build
```

Build writes to `../src/reachscope_workbench/static`. Do not edit built files by
hand. No runtime CDN, font server, analytics or frontend API key is needed.

## Boundaries

- `src/lib/api.ts`: shared HTTP transport and structured error handling. Mutations identify the
  local client through `X-ReachScope-Client: workbench`.
- `src/lib/types.ts`: shared response types and guards for module-specific result data.
- `src/lib/inspection-source.ts`: inspection origin classification and source filters.
- `src/lib/local-lab.ts`: typed client contracts for the local teaching workflow.
- `src/lib/security.ts`: shared public-reference URL policy; no rendering or credentials.
- `src/ai/`: AI-specific API client and contracts; uses the shared transport in `lib/`.
- `src/generated/`: generated API contracts; update through the repository contract generator.
- `src/hooks/`: polling, late-response guards and modal focus management.
- `src/components/NewJob.tsx`: input modes, uploads and local task creation.
- `src/components/Assets.tsx`: persisted asset inventory, source reuse and per-asset history.
- `src/components/NewJob.tsx` consumes `/api/catalog` for a four-step flow: choose an
  asset, provide input, select checks, then confirm. Required dependencies are
  selected automatically. Check choices are submitted to the backend and do not
  merely filter rendered results. Saved sources retain no per-run check selection.
- `src/components/results/Execution.tsx`: shared completed/skipped execution scope;
  `CloudResult.tsx`: resources, rule outcomes, uncertainty and source evidence.
- `src/components/results/`: separate Android paths, source reader, Web assets,
  investigation steps, observations and raw evidence views.
- `src/App.tsx`: navigation, task history and task-detail composition.
- `src/styles/index.css`: the global CSS entry, imported once by `src/main.tsx`.
  The other files in `src/styles/` contain the paper/ink visual system, feature
  layouts and responsive/reduced-motion rules. Styles owned by a result component
  remain beside that component.

### Directory and naming conventions

Keep `src/main.tsx` as the browser entry and `src/App.tsx` as application composition.
Put reusable non-component modules in `src/lib/`, using lowercase names and
hyphenated multiword names such as `inspection-source.ts` and `local-lab.ts`.
React component files retain PascalCase, for example `NewJob.tsx`; hooks retain
the existing `useName.ts` convention. Global styles use lowercase feature names,
for example `styles/detail.css`, with `styles/index.css` preserving import order.
Keep domain-specific contracts in `src/ai/` and generated files in `src/generated/`;
do not move components into `lib/` or hand-edit generated contracts. Use relative
module imports that resolve to the owning directory; directory cleanup must not
change exported names, API routes or runtime behavior.

Task detail requests cannot overwrite a newer route after returning late. Active
task polling avoids overlapping requests and stops when a task reaches a terminal
state. History is loaded in pages of 100, with explicit loaded/total counts and a
load-more action; on-screen aggregate counts apply only to the loaded records.
Source text and imported titles are rendered as text, never as executable HTML.
Imported status codes are marked as historical observations, not current liveness.

## Web response workspace

Web results have four views: asset responses, structured configuration checks,
page inventory and saved-snapshot comparison. Asset filters include HTTP status
classes, request errors and items needing review. CSV export downloads the
server-generated inventory; JSON remains the lossless result format.

Configuration checks expose their response evidence and recommendations. Page
inventory displays form actions/field names and resource URLs as inert text;
the workbench never loads those resources, executes target scripts or submits
forms. Cookie tables contain names and attributes, never cookie values.
Older results without these fields show an explicit unavailable state rather
than fabricated checks or counts. Import/demo records are not active probes.

Comparison baselines are loaded from real completed HTTP probe tasks in pages
of 100, with the loaded/total scope shown. Changing the baseline aborts the
previous comparison; leaving the view also cancels outstanding requests.
Added/removed target labels describe input-set differences, while unchanged
means only that comparable captured fields match. Each skipped comparison
retains the server's explanation. No status implies that a vulnerability was
fixed or that a site is safe. The Web view tabs support arrow/Home/End keyboard
navigation in addition to pointer input.

## Real browser acceptance

### Inspection readiness and response-loss recovery

The confirmation step calls the asset-scoped preflight API before an inspection.
It checks saved input availability and local prerequisites without contacting a
target. A blocked result stays in the wizard and explains what must be restored;
the saved asset/upload and selected checks remain available for retry. New runs
use `POST /api/assets/{id}/inspections`, so server-side stored input is the source
of truth instead of a second client copy of module/source configuration.

Asset creation, inspection submission and job retry have separate operation keys.
A lost response can be retried within the same UI operation without duplicating a
server-side record. Changing the logical inputs/checks/name creates a new request
key. Keys are retained while the view remains open; reopening/reloading starts a
new user operation. Upload response loss can still leave an unassociated local
upload, and successful upload responses are reused during subsequent submission
attempts. No uploaded user data is silently removed to hide this case.

Aborted reads keep their cancellation semantics. Structured API failures can show
an optional request reference for diagnostics; the primary message stays concise.
JSON requests stop waiting after 30 seconds, uploads after 120 seconds. A client
timeout does not cancel a server-side task and never triggers an automatic
mutation retry; the same pending operation key is reused when the user retries.

Run the maintained entry points from the repository root:

```bash
python scripts/check_all.py
python scripts/quality/check_browser.py --browser /path/to/edge-or-chromium \
  --out artifacts/validation/browser
```

`check_all.py` runs repository/backend/contracts/frontend checks and creates the
production build. The browser gate runs the checks in `tests/browser/`, using
private temporary workspaces and loopback fixtures rather than the operator's
normal service. If Playwright Chromium is already installed, `--browser` is
optional. Screenshots and validation records belong under `artifacts/validation/`.
Do not point an individual mutation test at a production workspace; backend tests
separately cover missing/corrupted inputs, dependency failures and scope checks.
