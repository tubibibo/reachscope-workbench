# ReachScope 专项安全测试日志 — 2026-11-02

> 发布脱敏说明：本副本将机器目录前缀和个人用户目录替换为占位符。其余历史版本、测试结果与证据说明保持原样，未将历史验收视为 2026-11-04 重新执行的结果。

> 历史记录：正文中的实际执行命令、版本、哈希和证据路径保留当时原样。当前目录与命令见 [仓库结构规范](../development/repository-layout.md)；路径迁移表见 [path-migrations.json](../../config/path-migrations.json)。

状态：0.14.1 限定范围内的测试、确认问题修复与本地发布验收完成；**仍有1条开发依赖公告未解决**。
基线：0.14.0 / a20ed41；交付版本：0.14.1；workspace schema保持7。
授权：用户明确要求全面安全测试、找到问题后修复并保留专门日志。

## 结果摘要

- 修复9项确认问题（8项Medium、1项Low），另完成2项Low防御硬化；未证明RCE或权限提升。
- 新增55项Python安全回归，已包含在完整 **2,033 passed、5 skipped、1既有上游warning** 中。
  完整pytest用时 **188.35s**，覆盖率 **92.43%**；Ruff与strict mypy **129源文件**通过。
- 最终完整浏览器门禁 **8组76项通过**，含新增安全组7项；前端类型、格式、构建及请求契约通过。
- 新建仓库外环境安装最终wheel，157运行文件/129 Python文件与冻结源码匹配；pip check、
  独立导入、5项安装态歧义拒绝检查、四模块smoke与真实loopback HTTP静态资源验证通过。
- Python实际运行依赖21包：基线和新安装版本各完成公告审计，均0个已知公告、0跳过。
  新环境anyio版本与基线不同，已按实际版本另审，没有将旧审计冒充新环境结果。
- npm生产依赖审计0；开发依赖3个moderate节点对应同一条minimatch公告，保持OPEN。
- Bandit扫描129源文件无解析错误，原始41个告警逐项保留/人工分类；不把工具High直接当产品High。

## 范围与方法

仅在新建临时工作区、合成文件、受控ASGI/loopback站点与浏览器fixture进行主动测试。
不使用用户历史工作区作恶意测试，不运行目标APK，不联系第三方测试目标或商业模型，
不继续已暂停的Linux实机工作。外网仅用于公开公告、软件包安装和依赖审计。

| 测试面 | 实际执行与结果 |
|---|---|
| HTTP/API | Host/Origin/请求字段、错误反射、路径日志、实际ASGI/HTTP请求；日志问题修复 |
| 网络/AI | 两个loopback站点验证带凭据GET与推理POST不跟随重定向；DNS私网重绑定发送前拒绝 |
| 上传与解析 | Cloud重复身份、Manifest歧义、ZIP跨平台别名、XML声明/预算、普通输入兼容与失败回归 |
| 子进程 | 工作台未用日志、legacy CLI双流预算、超时/取消、真实Windows本机Python后代回收 |
| 前端 | 文字型HTML载荷、引用协议、草稿密钥目的地、摘要授权绑定、取消/幂等、下载/sourcemap |
| 业务完整性 | 范围/来源、CAS、事件事务回滚、复测时间/完整性、并发决策与IR身份歧义 |
| 供应链 | pip-audit2.10.1、Bandit1.9.4、npm官方registry审计，区分运行/开发依赖与真实可达性 |

loopback单人设计没有账号；同机进程本就能作为操作者访问API/文件，这不被误报为多租户越权。
用户显式允许的本地资产输入也不一概标SSRF。既有通过的控制不计为新漏洞。

## 已修复的确认问题

| ID / 级别 | 根因、威胁前提与实际前态 | 修复和回归 |
|---|---|---|
| SEC-API-01 / Low / CWE117 | 解码路径中的ESC/ANSI与bidi可进入本机日志，影响呈现完整性；4例前测2fail/2pass，CR/LF未能伪造多行 | api/app.py日志路径有界ASCII JSON编码；7项专项通过。非RCE或密钥读取 |
| SEC-FILE-01 / Medium / CWE20、200 | 重复Terraform change地址last-wins丢弃先前sensitive/unknown；前态结果含纯canary且未知字段变成pass | cloud/input.py拒绝重复change身份，不能用后项抹掉保护标记 |
| SEC-FILE-02 / Medium / CWE20、436 | 重复application/uses-sdk只取首项，后续声明被忽略；前态debuggable可pass，比较器可得未再观察到 | ingest/manifest.py集中拒绝歧义单例，android/posture.py沿用校验；未宣称Android真实部署效果 |
| SEC-FILE-04 / Medium / CWE400 | 两个worker将decoder诊断写入无上限、未消费的临时decoder.log；外层tail管不到该文件 | manifest_worker.py/code_worker.py丢弃未用decoder输出，保留父worker有界错误通道；前2fail后pass |
| SEC-FILE-05 / Medium / CWE400 | legacy CLI version/decode全量缓存诊断；本机Python1MiB canary前态成功且内存随输出增长 | engine有界双流捕获（每流64KiB）并清理所属树；超限明确失败，不返回伪成功。7项新回归 |
| SEC-UI-01 / Medium / CWE522 | 手工改接口仍保留旧目的地草稿密钥；显式保存/目录授权后，两个loopback fixture实证旧canary到第二地址 | AIPreferences.tsx地址编辑清空草稿并提示，修后旧canary不跨目的地，新输入才可发送 |
| SEC-UI-06 / Medium / CWE863 | 刷新提供方/摘要后旧授权仍勾选，而UI已持有新context hash，后台stale防护无法替代这次审阅 | WebAdvisory.tsx把授权绑定具体hash；变化须重新确认，不确定提交保留原preview/幂等键。前测未发送推理 |
| SEC-CASE-01 / Medium / CWE367 | 预测下一版本并发合法重开，陈旧resolved快照跳过复测验证，末端CAS却匹配新版本，可无复测重关 | CaseService.update读取后立即绑定expected_version，末端CAS保留；前1fail、后1pass |
| SEC-IR-01 / Medium / CWE20、436 | 重复component/chain ID在分析、展示、查询中first/last-wins；还找到桥调用自然键省略实现类的歧义可能性 | ir/validation.py集中拒绝重复，在Report/分析/查询入口失败关闭；8项新回归，未改历史ID或静默去重 |

具体源文件/测试行号和前后事实见以下机器记录；模块定位采用修复后的源码：

- API：`tests/security/test_api_security_audit.py`；局部7passed、既有相关151passed。
- 案例：`tests/security/test_case_security_audit.py`；局部1passed、既有相关225passed。
- 文件：`tests/security/test_file_boundaries.py`与`test_legacy_decoder_bounds.py`；39项新安全测试，
  已包含在文件方向783passed/4skip中，不能相加成额外总数。
- IR：`tests/security/test_ir_security_audit.py`；局部8passed，unit总组665passed/1skip。
- 浏览器：`frontend/scripts/verify_frontend_security_ui.py --phase after`；7项通过。

修复前记录保留了真实失败，不是把所有新增55个测试都声称曾失败。IR仅验证重复处理与
自然键歧义，没有搜索真实SHA碰撞，没有声称认证破坏；工件仍使用原有SHA256身份。
新行为会拒绝含歧义ID的报告，不自动修写历史文件；正常历史ID格式及golden保持兼容。

## 防御硬化（不冒充已证明的远程利用）

- SEC-FILE-03 / Low / CWE178：ZIP拒绝大小写/尾点/保留名称/目录别名冲突，验证器自身也有
  路径节点预算。Windows普通canary文件抽取证实过别名覆盖；未运行恶意APK或证明Apktool RCE/穿越。
- SEC-UI-04 / Low：统一公开引用URL策略，允许HTTPS且无userinfo/控制/空白；拒绝项退回文字。
  这是服务端受控引用的防御加强，未证明当前模型可注入任意指南或远程XSS；HTTPS也不保证站点可信。

## 未解决依赖项：SEC-UI-07 / OPEN

GHSA-g3hv-75wg-m249 / CVE-2026-118764，官方标为Moderate，公告范围<11.0.1。
当前开发链：openapi-typescript7.13.0 → @redocly/openapi-core1.34.22 → minimatch5.1.9。
官方审计把影响沿链记为3个moderate节点，但只有1条底层公告；生产依赖前后均0。

没有找到公告认可且保持旧callable CommonJS API的兼容修补版。未用强制主版本override、
降级或ignore把结果刷绿。当前生成器只读取固定的本地create_app().openapi()，无用户glob
入口且有60秒子进程期限；安装的v5也无公告描述的两个预处理方法。这降低当前已验证
路径的可达性，但不推翻公告范围，也不标为已修复。

后续需上游兼容补丁或独立验证一次有意的工具链迁移；继续限制生成器处理可信固定schema。
来源：https://github.com/advisories/GHSA-g3hv-75wg-m249

## SAST逐项判定

Bandit原始结果41项（工具High1、Medium14、Low26），未加全局nosec抑制：

- 9项B608：固定SQL片段/占位符个数拼接，用户值参数绑定；未确认SQL注入。
- 8项XML提示：实际产品入口先做DTD/ENTITY拒绝及字节预算；不扩大为底层parse_manifest单独调用安全保证。
- 9项B105：PASS状态、字段名、计数等，非真实口令；B104为配置投影中的通配地址字符串，非监听。
- subprocess条目逐一核固定argv、无shell、可信工具、预算和回收；assert条目不是唯一授权/范围检查。
- B324的legacy短SHA1不是密码/签名。对应的重复ID完整性问题已修，未改8位历史格式；
  潜在真实短哈希碰撞会失败关闭而非静默错绑，不宣称拥有密码学认证能力。

完整原始输出与每项disposition保留为bandit-final.json/bandit-triage.json，不宣称扫描零告警。

## 命令、证据与时间线

主目录：`<LOCAL_AUDIT_OUTPUT_DIR>/security-audit-2026-11-02/`。
发布证明：同级`outputs/workbench-0.14.1/`。仅包含本地合成canary；不发布用户凭据/资产原文。

1. 记录干净基线，建立专门日志，分派API/文件/前端独立审查。
2. 保留文件首批14fail、decoder2fail、legacy4fail、API2fail与CASE1fail等前态证据；逐项修根因。
3. npm默认镜像审计404/NOT_IMPLEMENTED保留为失败，单次改官方registry查询，未修改全局npm配置。
4. 安全工具首次下载180秒超时保留，缓存重试成功；工具置于忽略的独立venv，不进入应用运行依赖。
5. 浏览器受到现有杀毒软件注入脚本影响；专项harness阻断非fixture origin、只记录origin，未关闭/修改杀毒软件。
   一次Windows临时server.lock清理瞬时失败也保留，未当通过；最终完整门禁通过。
6. 完整源码门禁、八组浏览器、前端契约/构建、依赖审计与全新安装包证明分别执行；数量不相加。
7. 更新备份首轮遇Windows长路径，候选服务曾在未完整副本时短暂启动；发现后核对空闲所属进程并停止。
   不完整副本不算有效。改短路径完成SQLite+139文件全量复制/hash，17表仍与最初SQLite副本完全一致，
   再最终启动0.14.1。此流程纠正已保留在workspace-backup-reference.json。
8. 最终运行健康/静态字节与历史核对通过；165任务、91资产、12事项、4 AI报告、25上传及139文件保留。
   只恢复已授权且匹配的AI会话密钥，配置revision token按设计轮换；密钥不落库/提交，无provider请求。

复跑命令：

```sh
python -m pytest tests/security --no-cov -q
python scripts/check.py
python scripts/contracts.py
npm --prefix frontend run format:check
npm --prefix frontend run check
python scripts/browser_checks.py --out .ui-checks/security-release --browser <Chromium路径>
```

扫描器命令、版本及原输出见python-runtime-audit.json、python-runtime-installed-audit.json、
frontend-review/npm-audit-*.json、bandit-final.json；工具退出码1、镜像失败和OPEN项不掩盖。

## 验收边界与未执行

- 5个完整套件skip：4项Linux专属行为、1项Windows符号链接权限；不计为通过。
- Linux实机验收暂停；未执行真实Android运行态、恶意APK/JAR、商业AI、外部目标扫描或远程GitHub CI。
- 依赖审计针对实际已安装版本，不保证所有依赖声明允许的历史版本，也不能发现尚未公开公告。
- 本地诊断/原上传可包含敏感信息，仍需操作者访问与保留策略；测试日志不替代OS防护。
- 这是一轮有边界的工程安全测试，不是形式化验证、生产多租户认证或“无漏洞”承诺。
