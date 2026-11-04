# 主机资料采集与整改：0.14

这条路径服务于“维护一台 Linux 网站服务器，核对配置并跟踪修复”的场景。
采集器、输入解释、规则判断和人工整改分别由独立组件负责。

## 准备资料

在“新建分析 → 主机防御 → 配置基线”下载 `reachscope-host-collector.pyz`。
“可审阅源码”下载的是相同字节的 ZIP，可用归档工具打开逐个检查 Python 源文件。
下载操作不执行脚本、采集命令或模型调用。目标 Linux 环境需要 Python 3.11+。

请自行指定一个不会随配置调整变化的主机标识，例如 `srv-web-01`。先在要检查的
Linux 环境展示计划；下述 `snapshot.json` 是新文件，不能覆盖已存在的资料：

```sh
python3 reachscope-host-collector.pyz --host-id srv-web-01 --ssh-context global --output snapshot.json
```

核对计划中的主机标识、固定命令、绝对输出位置和限制。确认后在同一工作目录用
输出中的实际 `plan_sha256` 替换 `PLAN_SHA256`，显式执行：

```sh
python3 reachscope-host-collector.pyz --host-id srv-web-01 --ssh-context global --output snapshot.json --collect --plan-sha256 PLAN_SHA256
```

没有自动提权或自动上传；不要为了完成采集关闭系统安全控制。缺少命令、权限不足、
超时、预算用尽或无法支持的语法会保留对应状态。输出只包含允许的字段，并以限制
权限的新文件发布；请先自行审阅 JSON，再手动上传到本地工作台。

`global` 只表示 OpenSSH 未指定连接条件时的导出范围。它不覆盖所有 `Match` 情况。
本版不把随意填写的连接标签当成已经执行的 `-C` 条件；其他上下文将保持不支持。

## 只读的准确含义

采集器不编辑 SSH/Nginx 配置，不启动、重载或停止服务，不主动连接网络，也不采集
日志、私钥正文或环境凭据。它调用固定的系统二进制 `sshd -T`、`nginx -T` 并在内存
中投影 stdout，不把原始 stdout/stderr 放进资料包。系统自带测试命令仍可能校验其
配置引用的文件并访问诊断日志；“不修改配置”不是对任意外部二进制零文件副作用的承诺。
系统配置和被调用程序本身须由操作者信任。

四个 SSH 审查字段和有限 Nginx HTTP 上下文可以导出。Nginx 的非检查值及资源名称
通过白名单删除或稳定摘要别名处理；这不是对原系统配置的可部署替代。动态选择器、
条件块、未解决的 include 或其他无法安全保持语义的输入会使该组件保持未知，不能
删除复杂内容后冒充完整结果。普通输入的支持范围以实际测试和状态码为准。

## 上传并处理

1. 在主机配置基线中填写相同主机标识，上传资料包的 JSON。
2. 先看解析预览：组件是否采集成功，是否有超时、失败或不支持，再选检查项执行。
3. 结果中区分待复核、信息不足和满足静态条件。选已有授权工作区建立整改事项。
4. 阅读补强前提、业务影响、验证与回滚。工作台不会执行修复。
5. 人工处理后，用相同主机标识、上下文及采集格式重新导出到另一个新文件。
6. 在事项中明确关联修订资料，执行复测；核对证据并填写依据后人工关闭。

既有 `reachscope-host/1` 模板仍可用；采集器输出为 `reachscope-host/2`。
完整文本和投影资料使用不同的比较范围，不会仅因规则名称相同就自动判为可比。
从旧模板改用采集器时，应核对范围并以新格式建立对应基线。

资料的主机标识、时间、采集器版本及成功状态都是文件提供的声明，不能认证主机
身份、采集器来源或证明服务已加载该配置。无日志命中也不能当成修复成功。

## 工程与验收

- 架构边界与兼容决策：[ADR 014](../../architecture/adr/0014-host-collection-journey.md)。
- 实际 Linux 验收条件及状态：[Linux 验收](../../development/host-linux-acceptance.md)。
- 当前执行过的检查、跳过项和限制：[项目状态](../../releases/project-status.md)。

本机 Windows 测试、mock 命令和受控上传不代替实际 Linux 二进制验收。
商业 AI 推理仍遵守既有延期决定；主机资料不发送给模型。

## 依据

- OpenSSH `sshd(8)` 官方手册：`-T` 与连接条件 `-C` 的语义。
  https://man.openbsd.org/sshd.8
- Nginx 官方命令行说明：`-T` 包含 `-t` 的文件校验行为。
  https://nginx.org/en/docs/switches.html
- Python 标准库 `subprocess` 与 `zipapp` 官方说明。
  https://docs.python.org/3/library/subprocess.html
  https://docs.python.org/3/library/zipapp.html
