# 仓库结构与命名规范

> 公开源码说明：文中的历史提交号属于公开导出前的开发记录；本副本不携带该私有 Git 历史。提交号仅用于来源标识，不代表新仓库中存在对应提交。

本次整理基于安全补丁提交 `ceb525a`，不改变公开包名、HTTP API、工作区 schema
或分析规则。目录负责表达文件的职责；历史记录和用户数据保留来源与内容。

## 目录职责

```text
reachscope-workbench/
├── src/
│   ├── reachscope/                Android 分析引擎及随包分发的合成样本
│   └── reachscope_workbench/      工作台；api / core / integrations / modules
│       ├── collectors/           随包分发的主机离线采集器
│       ├── scenarios/            随包分发的本地教学场景资源
│       └── static/               前端构建的发布副本，由 Vite 生成
├── frontend/
│   ├── contracts/                本地 OpenAPI 快照
│   └── src/
│       ├── components/           React 组件，按现有功能分组
│       ├── hooks/                React hooks
│       ├── lib/                  公共 API、类型、来源及安全辅助函数
│       ├── ai/                   AI 接口适配与类型
│       ├── generated/            工具生成的 API 类型，不手工编辑
│       └── styles/               全局样式入口与分区样式
├── tests/
│   ├── unit/                     分析引擎单元测试
│   ├── workbench/                工作台契约、服务和模块回归
│   ├── integration/              多层集成测试
│   ├── security/                 安全回归
│   ├── browser/                  显式运行的浏览器验收脚本
│   ├── fixtures/                 测试专用合成输入
│   └── golden/                   经审阅的回归快照
├── scripts/
│   ├── check.py                  Python 稳定入口
│   ├── check_all.py              完整开发门禁稳定入口
│   ├── quality/                  目录、契约和浏览器调度门禁
│   ├── smoke/                    安装态与专项验收
│   └── benchmark/                显式语料评测
├── config/                       仓库治理规则与历史路径迁移表
├── docs/                         使用、模块、架构、开发、验收、安全及历史文档
├── examples/                     可运行的协议示例
├── benchmark/                    语料清单；真实 APK 不入库
├── artifacts/                    本地日志、截图和安装包；仅 README 入 Git
├── .cache/                       lint / 类型 / pytest / coverage 可再生缓存
├── .workbench/                   私有真实资产、数据库与任务证据
└── .reachscope/                  私有工具环境及备份
```

根目录保留行业工具约定的入口：README、LICENSE、CHANGELOG、CONTRIBUTING、
SECURITY、AGENTS、pyproject、锁文件及工具配置。`start-workbench.ps1` 保持原启动
入口。不要为了表面整齐改包名、移动安装资源或增加只有一个子目录的 `backend/`。

## 命名约定

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| Python 模块和工具 | `snake_case`，动词说明脚本动作 | `check_contracts.py`、`run_benchmark.py` |
| pytest 测试 | `test_<behavior>.py` | `test_case_security_audit.py` |
| 浏览器验收入口 | `check_<journey>.py`，由显式门禁调度 | `check_onboarding.py` |
| React 组件 | `PascalCase.tsx` | `CaseDetail.tsx` |
| React hook | `use<Name>.ts` | `useJobs.ts` |
| 公共 TS / CSS 文件 | `lowercase-kebab-case`；按职责目录归组 | `inspection-source.ts`、`styles/assets.css` |
| 普通文档 | `lowercase-kebab-case.md`；目录索引保留 `README.md` | `quality-gates.md` |
| ADR | 四位编号加主题 | `0014-host-collection-journey.md` |
| 历史版本文档 | 文件名分隔用连字符，正文保留原版本 | `workbench-0-11-to-0-14.md` |
| 日期记录 | ISO 日期 `YYYY-MM-DD` | `security-test-log-2026-11-02.md` |

标准配置文件、外部接口字段、样本/case/evidence ID、golden 文件和第三方来源文件
遵守各自既有契约，不为统一外观改名。`src/reachscope/samples/` 是安装包运行资源，
与 `tests/fixtures/` 生命周期不同，不能合并。`static/` 是发布输出，不手工维护。

## 产物和用户数据

新日志写 `artifacts/logs/`，浏览器和专项结果写 `artifacts/validation/`，显式
构建可用 `python -m build --outdir artifacts/packages`。setuptools 仍可能生成
标准临时 `build/`；它与 `dist/` 都是忽略的产物，不是源代码。历史日志保留原名，
移动后的 SHA-256 记录在本地归档清单。旧工具兼容目录 `data/` 暂保留，可能含历史
工作区，不作为普通缓存自动迁移或清除。`.venv/` 和 `frontend/node_modules/` 为工具约定。

`.workbench/`、`.reachscope/` 和 `data/` 中的用户资料不进入 Git，也不在这次整理中
改名、迁移或清空。不能将私有备份或任务证据当作“无用文件”删除。

## 迁移和工程门禁

[迁移表](../../config/path-migrations.json) 记录旧路径与新路径，帮助查阅旧提交或
安全测试日志。历史日志中的原命令、哈希和计数不改写为本次路径，避免伪造验收来源。
当前教程、CI、脚本调度和代码引用使用新路径。

[治理配置](../../config/repository-layout.json) 集中声明根目录边界、保留的私有目录、
必要入口及排除项。新增顶层目录应先说明职责并更新配置。

```console
python scripts/quality/check_repository.py
python scripts/check_all.py
python scripts/quality/check_browser.py
```

目录门禁检查必要入口、根目录散落文件、Python/文档命名、迁移脚本的同级导入、本地 Markdown 目标文件
是否存在；不会访问外网、读取私有工作区，也不声称检查 Markdown 锚点或证明历史
验收结论。sdist 必须带上 `config/`、脚本、文档和测试；wheel 仍只包含运行文件。
