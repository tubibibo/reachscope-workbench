# 工程命令

所有命令从仓库根目录执行，使用当前项目虚拟环境中的 Python。
脚本是开发和验收入口，不供业务层导入。

| 入口 | 职责 |
| --- | --- |
| `python scripts/check.py` | Python lint、严格类型和测试 |
| `python scripts/check_all.py` | 完整开发门禁：目录、Python、API 契约、前端类型/格式/构建 |
| `python scripts/quality/check_repository.py` | 仓库目录、命名和本地 Markdown 链接 |
| `python scripts/quality/check_contracts.py` | 真实本地 OpenAPI 与生成类型一致性；有意变更后加 `--write` |
| `python scripts/quality/check_browser.py` | 调度 `tests/browser/` 中八组隔离浏览器验收 |
| `python scripts/smoke/check_installed.py --data EMPTY_TEMP_DIR` | 全新安装包验收；必须使用仓库外新环境 |
| `python scripts/smoke/check_android_depth.py` | Android 合成样本深度验收 |
| `python scripts/smoke/check_asset_flow.py --help` | 资产流程 smoke 参数 |
| `python scripts/smoke/check_red_blue.py --help` | 红蓝流程 smoke 参数 |
| `python scripts/smoke/check_web.py --help` | Web smoke 参数 |
| `python scripts/benchmark/run_benchmark.py --help` | 显式提供语料后的离线评测 |

`quality/` 存放通用工程门禁，`smoke/` 存放按能力划分的验收入口，
`benchmark/` 存放评测工具。文件使用 `snake_case.py`，以 `check_` 或 `run_`
说明动作。顶层保留两个稳定入口，避免日常使用者记忆内部路径。

浏览器入口默认写入 `artifacts/validation/`；日志建议显式重定向至
`artifacts/logs/`。真实工作区、密钥和历史证据不用于测试。

`smoke/check_host_linux.py` 仅整理路径，Linux 实机方向仍暂停；现行验证不执行其
`--run`，也不把 Windows mock 视为 Linux 验收。
