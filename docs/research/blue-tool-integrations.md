# GitHub 蓝队工具接入调研

调研日期：2026-11-02。工程基线：0.14.0 / f34f5a0。
状态：研究建议；没有安装工具、运行扫描、复制规则或实现下列适配器。

## 结论

Linux 实机方向保持暂停。优先建议选择 **Hayabusa Windows 调查报告**作为下一版的
单一接入切片；随后考虑 **Prowler 云检查报告**、**Trivy 软件与依赖报告**。
这是结合现有架构和使用场景的工程判断，不是按星数排列的客观排名。

共同路线是：选择来源 → 上传既有报告 → 验证版本与范围 → 脱敏预览 → 保存外部证据
→ 人工调查或整改。扫描器与工作台先通过数据契约衔接；远程控制、托管扫描和自动
修复分别设计。这样不需要部署 Linux、云账号接管或整套 SIEM 作为报告导入的前提。

## 候选比较

下列星数是 2026-11-02 调研时 GitHub 页面显示的约数，不代表精确实时值或质量排序，
也不据此推断维护日期。
未验证任何候选 release 二进制，main/master 与文档不能直接当作已锁定稳定版。

| 候选 | 上游能力/契约 | 对 ReachScope 的接法与判断 | 许可关注 |
|---|---|---|---|
| Hayabusa（约 3.4k） | Windows 事件日志调查；当前官方文档支持 CSV/JSON/JSONL 时间线及自定义 profile [H1,H2] | **第一候选**：导入单一约定 profile 的 JSONL，提供时间线、规则来源和人工调查事项 | 引擎 AGPLv3，检测规则 DRL1.1，分开记录 [H3,L1] |
| Prowler（约 15.2k） | 云安全/合规检查，有 JSON-OCSF 输出 [P1,P2] | **第二候选**：先限定 AWS、一个账号声明和少量 S3 检查报告，衔接既有云模块证据 | 上游代码 Apache2.0；规则/数据来源仍逐项记录 [P3] |
| Trivy（约 38.9k） | 软件包漏洞、错误配置、秘密等不同结果类型，JSON 为结构化报告 [T1,T2] | **第三候选**：先接漏洞摘要，不将扫描器、数据库或全部敏感上下文打包到工作台 | 上游代码 Apache2.0；数据库/上游数据来源另核对 [T3] |
| osquery（约 23.7k） | 终端查询结果、JSON 日志，快照与差分语义不同 [O1,O2] | 适合后续有限 OS/软件/端口快照，补充资产上下文；第一版不接任意 SQL 或远程控制协议 | Apache2.0 OR GPL2.0-only，可选择其一，依赖另核对 [O3] |
| Chainsaw（约 3.7k） | Windows 取证材料搜索和规则匹配，可输出机器可读结果 [C1] | Hayabusa 的替代方案，第一版不同时适配两种时间线以免扩大验证面 | 引擎 GPLv3；Sigma 子模块规则另看 DRL1.1 |
| Sigma / pySigma | Sigma 是规则格式/规则集合；pySigma 解析和转换查询 [S1,S2] | 可为命中保留规则说明、作者和 ATT&CK 标签；暂不承诺完整 Sigma 日志执行器 | SigmaHQ 规则 DRL1.1；pySigma LGPL2.1，两者不能混作一个许可证 [S3,L1] |
| Wazuh（约 17.5k） | 完整安全平台；已有告警可经文件或 Indexer 搜索获取 [W1,W2] | 适合已有部署用户的后续外部告警来源；不作为本地单人工具的强制平台依赖 | 按版本/组件核对：当前 main 有 GPLv2、AGPLv3 和双许可部分，不能只写单一 GPL [W1] |
| Velociraptor | 终端调查与 collection 结果；公开自动化 API 为 mTLS gRPC [V1,V2] | 后置。先考虑已完成 collection 的指定结果，不引入 hunt、任意 VQL 或主机隔离 | AGPLv3；数据与源码分发方式分别核对 |

## 第一切片：Hayabusa 报告

先做“已有 Windows 调查报告的读取与复核”，当前方案不决定原始 EVTX 解析、工具安装
或执行方式。用户在工作台外生成受控报告，再导入。当前官方命令文档是
`dfir-timeline` 配合输出类型；旧文章中的命令不能当成当前固定契约 [H1]。

### 固定契约

- 实现前选择一个实际 release/commit，生成并保存真实导出 fixture；2026-11-02 的调研未验收具体工具版本。
- 锁定一个带版本与摘要的最小 profile，而非只凭 `.jsonl` 后缀接受任意对象。
- 目标字段：Timestamp、Computer、Channel、EventID、RecordID、RuleTitle、Level、RuleID、RuleAuthor。
- 可选：规则相对引用、状态与 ATT&CK 标签；输入未提供的字段保持未知。
- 不直接透传 Details、ExtraFieldInfo、AllFieldInfo、RenderedMessage 或完整 EVTX 路径。
- 引擎版本、规则版本、profile 声明和采集窗口来自操作者或报告，未经核实均保留为声明。
- 原报告 SHA-256 由工作台对实际上传字节计算；它证明保存资料的对应关系，不认证报告来源或内容真实性。
- 适配器维护的固定 profile 配置自行计算摘要；用户声明的 profile 摘要另存，不能冒充已核对契约。

官方 profile 可以定制；默认 standard 字段列表不含 RuleAuthor，而 super-verbose
同时包含作者及大量事件上下文，不适合整份透传 [H2]。DRL1.1 对基于规则命中的
展示也有作者保留要求，不能只存“标题＋严重程度” [L1]。具体版本/profile 能否提供
所有必要归属字段应在实现前验证，缺失不能用臆造作者补齐。

### 用户得到什么

按时间、主机别名、级别和规则定位调查线索；打开来源事件引用；将一条明确的外部
观察放入已有授权范围和案例。保留“第三方报告、待核实”，而非声称 ReachScope
自己完成了检测或确认入侵。用户名、路径和命令行等原始内容只在明确策略下处理。

日志缺失、通道未启用、规则过滤或片段无命中都不能证明没有攻击；导入后的规则
命中本身也不证明已入侵。不增加任何基于“下一份报告没有这条”的自动清除逻辑。

## 第二/第三切片的关键区别

### Prowler

OCSF 是检查结果，不是 AWS 原始配置。不能将报告强行塞入当前 cloud 配置解析器，
也不能沿用自研规则 ID 冒充本项目重新检查。官方输出代码的 `status_code` 承载
PASS/FAIL/MANUAL；`status_id` 的 New/Suppressed 不能替代检查结论，更不能把抑制
当成已修复 [P4]。批次/扫描 ID 与稳定资源身份也应分开。

首版范围可限定 AWS S3；保留工具/规则命名空间、账号声明、区域、资源 UID、检查
ID、时间、上游状态、证据定位和版本。缺少资源、权限、过滤或 mutelist 造成缺项
都不能自动通过复测。所谓序列化 sanitize 也不等于隐私脱敏，应独立字段投影。

### Trivy

JSON 的漏洞、配置、Secrets、许可证属于不同结果结构。先只接漏洞摘要，保留包名、
安装版本、可用修复版本、漏洞 ID、严重程度及其来源，不混用结果类型 [T2,T4]。
`Status=fixed` 不能理解为用户安装的软件已完成升级；报告缺项也可能受忽略规则、
严重程度或 VEX 等过滤影响 [T5]。

当前 secret scanner 会遮盖匹配范围，但 JSON 并不是隐私白名单：代码上下文、路径、
镜像配置等仍可能含敏感内容 [T6]。首版不导入 Secret 的正文/Code/Match 或完整
ImageConfig，不自动发送 AI。“离线导入”不需要运行扫描器；以后执行 Trivy 时，
也不能只凭 `--offline-scan` 就宣称所有更新、模块或数据库请求均被禁止 [T7]。

## 高内聚、低耦合的接入边界（提案，未实现）

1. 每种上游格式拥有独立适配器，负责探测、版本校验、有界解析和字段归一化；不直接访问数据库或执行工具。
2. 应用层负责上传预览、不可变任务、授权范围和错误反馈；沿用 Evidence/Observation/ModuleResult 端口。
3. 工具命名空间、原始状态、规则作者/引用、原报告摘要和行/JSON 指针始终可回查。
4. 日志、云检查、软件漏洞分别保留类型；通用层不把它们压成一个失去语义的 severity 字符串。
5. 当前 case 来源白名单、imported_unverified 和比较器需要显式评审；不绕过已知规则/证据检查。
6. 第一版先做人工调查/处理决定；修复可比性另有契约后再支持，不能复用“资源没了＝修好”的捷径。
7. 现有 Web 通用导入已支持部分 httpx/Nuclei JSONL，但不是上述工具的通用接入器；不能重复宣称为新兼容。
8. 公开预览保留总数、未支持字段、解析失败、过滤和截断；不静默丢弃低优先级或超预算记录后声称完整。
9. 本阶段不引入远程账号、云凭据、自动运行、自动修复或额外 AI 请求。可选模型摘要属于后续独立授权能力。

候选验收包括真实固定版本 fixture、正常/缺字段/恶意嵌套/重复键/超预算/乱码、来源
与署名、不泄露原始敏感数据、重复导入、重启、人工建事项、明确不可比较以及手机端。
跨工具去重先展示可能关联并人工确认，不仅凭 IP、主机名或相同 CVE 合并证据。

## 已完成与未完成

- 已完成：官方材料与许可证核对、三路独立研究、现有模块边界审阅、接入优先级建议。
- 已记录：Linux 方向暂停；历史未验收状态保留。
- 未完成：固定候选 release、真实候选二进制导出验收、适配器、集成 UI、端到端测试。
- 未执行：安装工具/规则、扫描本机或第三方、访问云账号、启动 Linux、复制代码/规则、商业 AI。

## 官方来源

- H1: https://yamato-security.github.io/hayabusa/commands/
- H2: https://yamato-security.github.io/hayabusa/output/
- H3: https://github.com/Yamato-Security/hayabusa
- L1: https://github.com/SigmaHQ/Detection-Rule-License/blob/main/LICENSE.Detection.Rules.md
- P1: https://github.com/prowler-cloud/prowler
- P2: https://docs.prowler.com/user-guide/cli/tutorials/reporting
- P3: https://github.com/prowler-cloud/prowler/blob/master/LICENSE
- P4: https://github.com/prowler-cloud/prowler/blob/master/prowler/lib/outputs/ocsf/ocsf.py
- T1: https://github.com/aquasecurity/trivy
- T2: https://www.trivy.dev/docs/latest/guide/configuration/reporting/
- T3: https://github.com/aquasecurity/trivy/blob/main/LICENSE
- T4: https://github.com/aquasecurity/trivy/blob/main/pkg/types/report.go
- T5: https://github.com/aquasecurity/trivy/blob/main/docs/guide/configuration/filtering.md
- T6: https://github.com/aquasecurity/trivy/blob/main/pkg/fanal/secret/scanner.go
- T7: https://www.trivy.dev/docs/latest/guide/advanced/air-gap/
- O1: https://github.com/osquery/osquery
- O2: https://osquery.readthedocs.io/en/stable/deployment/logging/
- O3: https://github.com/osquery/osquery/blob/master/LICENSE
- C1: https://github.com/WithSecureOpenSource/chainsaw
- S1: https://github.com/SigmaHQ/sigma
- S2: https://github.com/SigmaHQ/pySigma
- S3: https://github.com/SigmaHQ/pySigma/blob/main/LICENSE
- W1: https://github.com/wazuh/wazuh#authors
- W2: https://documentation.wazuh.com/current/user-manual/indexer-api/use-case.html
- V1: https://github.com/Velocidex/velociraptor
- V2: https://docs.velociraptor.app/docs/server_automation/server_api/
