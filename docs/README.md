# 文档导航

> 本公开副本是源码快照，不包含开发期 Git 历史；历史提交号仅作溯源标识。截图可能来自早期版本，当前能力以项目状态与功能矩阵为准。

从使用流程进入，再按需查看模块、架构和验收记录。当前工程约束以根目录
`AGENTS.md` 和现行架构为准。

| 我想了解 | 入口 |
| --- | --- |
| 快速启动 | [五分钟上手](getting-started/quickstart.md) · [中文说明](getting-started/quickstart-zh-cn.md) |
| 亲手体验闭环 | [本地教学](getting-started/local-lab.md) · [资产流程](getting-started/asset-workflow.md) |
| 红蓝协作 | [验证与整改](getting-started/red-blue-workflow.md) |
| 当前进展与限制 | [项目状态](releases/project-status.md) · [功能矩阵](reference/feature-matrix.json) |
| 项目文件放在哪里 | [仓库结构和命名规范](development/repository-layout.md) |
| 理解后端边界 | [工作台架构](architecture/workbench.md) · [Android 引擎](architecture/android-engine.md) |
| API 与复测契约 | [工作台 API](reference/workbench-api.md) · [复测语义](reference/retest-semantics.md) |
| Android / Web / 云 / 主机 | [Android](modules/android/static-review.md) · [Web](modules/web/workflow.md) · [云](modules/cloud/configuration-review.md) · [主机资料](modules/host/collector.md) |
| AI 接口边界 | [Web 研判试点](modules/web/ai-advisory.md) |
| 参与开发 | [贡献指南](../CONTRIBUTING.md) · [工程命令](../scripts/README.md) · [质量门禁](development/quality-gates.md) |
| 安全测试结果 | [安全记录索引](security/README.md) · [2026-11-02 专项日志](security/security-test-log-2026-11-02.md) |
| 发布和历史验收 | [发布流程](development/releasing.md) · [验收记录](releases/validation/workbench.md) |
| 长期维护 | [维护手册](development/maintenance.md) |
| 后续研究 | [产品定位](architecture/product-direction.md) · [路线图](architecture/roadmap.md) · [蓝队工具调研](research/blue-tool-integrations.md) |

目录分工：`getting-started/` 面向使用者，`architecture/` 保存系统边界与 ADR，
`modules/` 按能力说明输入和输出，`reference/` 保存契约，`development/` 保存
维护流程，`releases/` 保存状态和验收，`security/` 保存安全记录，`research/`
保存未承诺落地的调研，`images/` 保存文档图片。
