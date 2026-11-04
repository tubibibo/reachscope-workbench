# 0.14.1 工程门禁与验收边界

## 本地开发

```sh
python -m pip install -e ".[dev,ui]"
npm --prefix frontend ci
python scripts/quality/check_contracts.py --write  # 仅在有意修改接口后更新并评审差异
python scripts/check_all.py
python scripts/quality/check_repository.py
python -m playwright install chromium
python scripts/quality/check_browser.py --out artifacts/validation/browser
```

已有 Chromium/Edge 可给最后一条命令加 `--browser <完整可执行文件路径>`。
浏览器检查使用临时工作区、随机端口和本机固定协议桩，不使用 8765 的用户配置，
清除继承的 AI 环境配置，没有真实商业推理。

## 契约

`python -m pytest tests/security --no-cov -q` 可单独复跑0.14.1 Python 安全回归，完整
`scripts/check.py` 已包含这些测试。详细before/after、SAST人工分类和未解决的开发
依赖公告见 [专项安全日志](../security/security-test-log-2026-11-02.md)。安全工具告警
不等于确认漏洞；失败、跳过和OPEN项不通过ignore/强制不兼容升级隐藏。

`scripts/quality/check_contracts.py` 从临时本地应用导出 OpenAPI，不启动 lifespan，不联系目标或模型。
`openapi-typescript` **7.13.0** 是锁定的开发依赖，生成
`frontend/src/generated/api.d.ts`；schema 快照在 `frontend/contracts/openapi.json`。
默认运行只检查，不修改仓库；有漂移返回失败。0.11 已实际注入一次 schema 版本漂移，
确认被拒绝后恢复原字节，再验证正常通过。

检查、案例更新、AI 设置/诊断和 Lab 配置的实际请求引用生成类型。
类型系统不能删掉对象运行时多余字段，因此创建案例仍显式序列化字段白名单。
响应中还有手写视图模型与通用 dict，本门禁**不是所有响应的完整兼容性证明**。

## GitHub Actions

- Windows/Linux × Python 3.11/3.13：Ruff、strict mypy、85% 覆盖率门禁、契约漂移、
  TypeScript、Prettier、生产构建及安装后冒烟。
- 独立 Ubuntu 浏览器 job：安装 Playwright Chromium，顺序执行入门、本地教学、
  Android、Web＋云、主机防御、主机引导、前端专项安全和 AI 本机协议八组；失败仍保存 7 天本地桩日志/截图。
- 工作流只要求仓库内容读取。Node/Python 开发工具不成为已安装工作台的运行要求。

工作流结构已在本地校验，所调用的脚本已在 Windows/Edge 实际跑通；没有在远程
GitHub runner 执行或推送，不能据此声称远程 CI 已通过。源码测试、浏览器协议桩、
新安装 wheel 与商业模型验收各自记录，数量不相加冒充更大的测试集。

## 升级与回退

0.14 沿用 schema **7**；投影导出使用独立输入格式 `reachscope-host/2`，旧的
`reachscope-host/1` 保持兼容。投影身份进入比较范围，跨格式不自动解释为已整改。
0.13 读取 v2 文件时会拒绝未知格式；回退前仍必须保存与版本匹配的完整工作区备份。

0.13 使用 schema **7** 标记新增 host 语义，旧版本会在写入前拒绝，避免错误解释新资产。
支持 v1–v6 加性升级，保留旧资产、任务、原始快照、事件和操作标识；旧来源不猜测。
独立回归使用真正 v5 六列及 v6 七列资产表，并验证未来 schema 8 拒绝时文件字节和
journal 不变。v6 的 12 张历史表经过两次打开仍保留原始行与 JSON 表示。

升级实际工作区前停止服务并备份。0.12 不支持打开 v7；需要回退时使用旧版本和
升级前的 v6 备份，不原地降级、不覆盖新历史。数据库备份不替代上传/源码工件备份。
版本号正确、测试通过都不能证明断电原子性、生产高可用、无 Bug 或架构师职级。

参考：[openapi-typescript](https://openapi-ts.dev/introduction)、
[Playwright Python CI](https://playwright.dev/python/docs/ci)。使用现有框架和锁定工具，
没有复制第三方完整平台源码。

## 独立 Linux 主机门禁

`scripts/smoke/check_host_linux.py` 默认只报告前置条件；显式 `--required` 可使前置条件
缺失返回非零，不能把 skipped/not_executed 算作真实采集通过。实际执行限定在明确
标记的一次性 Linux 容器，使用真实 SSH/Nginx 测试程序及受控配置，绝不在开发机的
真实 `/etc` 上做测试。详细步骤与2026-11-02 的阻断情况见 [Linux 验收](host-linux-acceptance.md)。

标准库采集器的进程组/0600/符号链接测试在 Windows 上明确跳过。输入校验、API、
浏览器文件上传、mock capture 和完整安装门禁通过仍不代替这些 Linux 实际验证。
