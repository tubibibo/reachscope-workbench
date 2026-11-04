# Validation record — 0.4.1 walkthrough

> 历史记录：正文中的实际执行命令、版本、哈希和证据路径保留当时原样。当前目录与命令见 [仓库结构规范](../../development/repository-layout.md)；路径迁移表见 [path-migrations.json](../../../config/path-migrations.json)。

Observed on Windows, Python 3.13.15 and Microsoft Edge on 2026-11-01.
The analysis engine and report/protocol/query schemas are unchanged; previous APK
and artifact validation remains recorded in [0.4.0 validation](engine-0-4-0.md).

## Automated checks

`python scripts/check.py` passed lint, strict types and **686 tests**, with one
symbolic-link test skipped because of Windows permissions. Python coverage was
**92.33%**. New tests check safe inline JSON, script-closing payload escaping,
correct source observations for the wrong-key case and no invented negative path.
Golden changes are limited to `meta.tool_version` from 0.4.0 to 0.4.1.

## Browser acceptance

The actual generated local HTML passed **15/15** acceptance groups. The installed
wheel's generated page independently passed the same portable script, 15/15.

- Five cases preserve their recorded verdicts.
- Source and target nodes display the corresponding `putExtra` and
  `getStringExtra`/`loadUrl` method code.
- SVG and step controls support mouse, keyboard and manual previous/next.
- Playback was observed advancing from step 0 to 1; after pausing, it stayed at
  step 1 for another 1.4 seconds.
- Filters, entry search, empty results, evidence identity and local exports work.
- The unknown parameter-key case has no connected edge.
- Pausing ambient motion then switching cases leaves the workbench fully opaque.
- Reduced-motion mode has no running animations by default.
- All five case notes and trace links remain readable without JavaScript.
- Desktop 1280×960 and touch/mobile 390×844 have no horizontal page overflow.
- No console/page errors or HTTP(S) requests were observed.

Desktop cover/workbench and full mobile captures were inspected. No externally
hosted typeface, UI kit, drawing or animation runtime is required.

## Reproducibility

The browser runner is included as `scripts/verify_frontend.py`. It accepts `--page`,
`--browser` and `--out`. These checks cover the saved walkthrough and its keyboard, motion and offline behavior. Playwright
is an optional development extra, not a dependency of the generated HTML.

The wheel and source distribution were rebuilt and the wheel installed into an
isolated environment. Executing the installed package outside the checkout
generated the five-case walkthrough successfully. The presentation is interactive,
but it still reads saved static-analysis evidence; it does not execute APK code
or call a model. No new real-world detection or model-performance claim is made.
