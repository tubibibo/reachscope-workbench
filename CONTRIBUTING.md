# Contributing

The current product is the local asset-first Android/Web/cloud workbench. Use
`docs/architecture/workbench.md` and `docs/reference/workbench-api.md` for module and transport
contracts. Keep modules independent; business logic must not move into routes or
React components. Task lifecycle changes require cancellation/restart regressions.
Catalogue/check changes must be exercised through the four-step flow and prove
that unselected analysis functions are not invoked. Asset association must match
the normalized input, with old workspace records preserved. Cloud rules require
unknown/sensitive-value cases and must not claim effective access from static files.

Install `.[dev,ui]`, then `npm ci` in `frontend`. Run `python scripts/check_all.py`
for Python lint/types/tests and the strict TypeScript production build. Use the
local fixture service for probes; tests must not contact public target websites.
After packaging, install the wheel in a fresh venv and run
`scripts/smoke/check_installed.py --data TEMP_WORKSPACE` using that venv's Python.

The copied `modules/web/legacy` code is a provenance-preserved integration boundary.
It is excluded from new-code strict mypy/lint/coverage metrics, but its classification
and path behavior is checked through module regression cases. Changes to copied
rules need independent positive and near-miss cases. Do not treat small golden
sets as real-world accuracy. Never overwrite the original projects while integrating.

Start with one reproducible behavior. Include the input (prefer a minimal,
source-only synthetic fixture), expected output, actual output and analysis
limitations. Do not submit proprietary APKs, credentials or live target data.

```bash
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -e ".[dev]"
python scripts/check.py
```

Keep pull requests focused. Describe the concrete behavior change and verification.
New analysis features need a positive case, a near-miss case and a documented scope.
Do not increase reported certainty merely to make a sample pass. Golden snapshots
are regression contracts, not ground truth. Update them only after reviewing the
semantic difference. API responses must preserve pagination, evidence identity,
explicit truncation and structured failure states.

The release checklist is in `docs/development/releasing.md`. Current limitations and open
research questions are in `docs/architecture/roadmap.md`.

## Scope and response

This is a personal project, published as-is and used by its author in real work.
It is not a community project and has no roadmap or response-time commitment.

- **Bug reports with a reproducible case**: welcome. A minimal input, the expected
  result, the actual result and your environment are enough to start.
- **Documentation fixes, typos, ports**: welcome as pull requests.
- **New features, new modules, new dependencies**: please open an issue first.
  Most will be declined — this tool deliberately stays small, local and
  dependency-light. A rejected feature is not a judgement on your work.
- **Security reports**: do not open a public issue. Use the private reporting
  channel described in `SECURITY.md`.

Response is best-effort. Silence is not rejection.

## AI 辅助开发

本项目在开发过程中使用了 AI 编码助手。这不改变验收标准：所有改动
都通过同一套门禁——lint、strict mypy、覆盖率阈值、接口漂移检查、
仓库链接检查和离线测试。判断一次改动是否合格，只看它是否通过了
这些检查，与它由谁、用什么工具写出来无关。

提交说明中不需要声明工具。引用 AI 产出的外部资料时，按普通外部
资料处理，注明来源与核对方式。
