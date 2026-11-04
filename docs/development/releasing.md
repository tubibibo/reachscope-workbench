# Workbench release procedure

1. Update the workbench package and frontend versions together. Preserve the
   independent engine and schema versions unless their contracts change.
2. Install development dependencies and run `python scripts/check_all.py`;
   also run `npm run format:check` in `frontend`. Review semantic golden differences.
   The frontend build must precede packaging. With a local server running, exercise
   `tests/browser/check_legacy_ui.py` against local fixtures and inspect its screenshots.
   For asset workflow changes also run `tests/browser/check_assets.py` and
   `scripts/smoke/check_asset_flow.py`. Confirm the saved asset's real input matches each
   linked task, selected groups actually execute and legacy jobs survive migration.
   For request/retry changes, run `tests/browser/check_reliability.py`;
   it deliberately drops committed responses and checks replay rather than
   simulating successful work. Keep simulated preflight-display checks labeled.
   For red/blue changes, run `scripts/smoke/check_red_blue.py` and
   `tests/browser/check_red_blue.py` against the real local API. Verify
   out-of-scope rejection, original evidence, stale versions, explicit revised
   inputs and the human retest-resolution loop.
3. Build: `python -m build --outdir DIST_DIR`.
4. Create a fresh venv outside the source tree, install the wheel and run
   `scripts/smoke/check_installed.py --data NEW_WORKSPACE` with that venv's Python from
   another cwd. It starts the installed server and checks frontend assets, all four
   modules, saved asset association, local preflight, selected cloud execution and Android source
   queries. Also check `reachscope doctor` and the
   retained engine demo if the engine was changed.
5. Verify wheel/sdist include built frontend assets, rules, provenance, templates,
   bundled source-only cases, LICENSE and the bundled frontend license appendix,
   and exclude APKs, private scan output, caches and local environment files.
6. For decoder changes, scan a local synthetic APK with Java/Apktool, reopen its
   artifact and read a method after the decoder's temporary directory is removed.
7. Record commands, versions, pass counts, dependency-audit results and limitations
   in `docs/releases/validation/workbench.md`. Cross-platform CI
   configuration does not substitute for an actual observed CI run.
8. Create a tag and publish only through the maintainer's chosen repository and
   package account. A local validated release is not automatically a public release.

No result should be called an LLM benchmark unless real model calls, baselines,
labels and scoring are available. A release artifact's content hash is not a
cryptographic signature or proof of provenance.
