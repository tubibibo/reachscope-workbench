# 内置场景包目录

本目录存放随应用分发的内置场景包，应用启动时与用户传入的 `--scenarios-dir` 根一起被
`core/scenarios/loader.py` 发现与校验。

## 放置方式

每个子目录是一个独立的场景包：

- `scenario.yaml` — 包声明，文法以 `core/scenarios/model.py` 为准（`pack_format` 当前为 1）
- 其余文件 — 各路由 `body` 引用的响应体，只允许 `.html` / `.txt` / `.css`

## 硬约束（作者可感知的部分）

- 响应头只能取 `ALLOWED_HEADERS` 白名单内的名字；`Content-Length`、`Connection`、
  `X-ReachScope-Lab-*` 是运行时保留头，声明即拒绝
- 单包 ≤ 2 MiB、路由 ≤ 32 条、`Set-Cookie` ≤ 4 条
- `profiles` 必须恰好包含 `baseline` 与 `hardened` 两个剖面

加载失败的包会以 issue 形式出现在 `GET /api/lab/scenarios` 的 `issues` 里，不影响其余包。
