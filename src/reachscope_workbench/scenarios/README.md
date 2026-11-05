# 内置场景包目录

本目录存放随应用分发的内置场景包，应用启动时与用户传入的 `--scenarios-dir` 根一起被
`core/scenarios/loader.py` 发现与校验。

## 当前内置包

| 目录 | 难度 | 一句话说明 | 核心教学点 |
|---|---|---|---|
| `missing-headers` | intro | 同一页面，一次不带安全响应头，一次带上四个常见安全头。 | 安全响应头是"默认缺失"的，必须显式声明 |
| `cookie-flags` | intro | 同一个会话 Cookie，一次裸奔，一次带上 HttpOnly、Secure、SameSite=Lax。 | 四个 Cookie 属性各自防什么 |
| `csrf-token` | intermediate | 同一 `/transfer` 路径，一次无任何校验返回 200，一次返回 403。 | 状态变更型 GET 的 CSRF 面 |

每个包一个目录，只含三类文件：`scenario.yaml`（场景定义）、`pages/*.html`（静态响应体，
UTF-8、无脚本、不加载任何外部资源）、`walkthrough.md`（面向学习者的中文讲义）。全部是数据
文件，不含任何可执行代码；每个场景都是"同一路径，两种配置"的对照。后续批次会补充更多内置包。

## 使用方式

1. 在 ReachScope 实验室页面选择场景包与剖面（baseline / hardened）并启动。
2. 对**同一条 URL** 分别在两个剖面下访问/采集，对照各包 `walkthrough.md` 第 1 节的表格核对差异。
3. 操作细节与延伸观察方法见各包 `walkthrough.md` 第 2 节。

## 共同边界

- 场景包只描述"演示用的固定响应"，不包含可利用漏洞，不是漏洞靶场。
- 页面不加载任何外部资源、不含脚本；页面内容在两个剖面下完全相同，差异只来自响应配置。
- 实验室只监听 `127.0.0.1` 的随机端口、只支持 `GET`；地址只在本机有效。

## 放置方式与硬约束

- `scenario.yaml` 文法以 `core/scenarios/model.py` 为准（`pack_format` 当前为 1）
- 响应头只能取 `ALLOWED_HEADERS` 白名单内的名字；`Content-Length`、`Connection`、
  `X-ReachScope-Lab-*` 是运行时保留头，声明即拒绝
- 单包 ≤ 2 MiB、路由 ≤ 32 条、`Set-Cookie` ≤ 4 条
- `profiles` 必须恰好包含 `baseline` 与 `hardened` 两个剖面

加载失败的包会以 issue 形式出现在 `GET /api/lab/scenarios` 的 `issues` 里，不影响其余包。
