# Report-scoped Claim–Verdict 协议（0.2）

ReachScope 的协议核对一条结构化主张是否与**当前静态分析报告里的候选路径和证据**一致。工具不调用模型，不重新执行 APK，也不独立证明漏洞。AI 可以借助证据继续调查，但自由文本回答不能变成代码事实。

## 1. 状态的准确含义

| 状态 | 含义 |
|---|---|
| `SUPPORTED` | 当前报告中存在匹配的候选路径，路径步骤有证据，相关可达性判据完整 |
| `SUPPORTED_WITH_ASSUMPTIONS` | 存在匹配的候选路径，但调用者还提交了未验证的假设或回答 |
| `REFUTED` | 当前 manifest 配置中的一个直接访问条件阻断该零权限入口，例如未导出或签名级权限 |
| `UNDECIDABLE` | 报告未找到匹配、证据不完整、实现缺失，或本次分析存在警告/降级 |

所有输出的 `scope` 为 `static_analysis_report`。`statement` 说明本次到底检查了什么。

`SUPPORTED` 不证明运行时分支能够同时成立，不证明可利用性或影响。`REFUTED` 只否定所检查的直接入口条件，不否定其他导出入口、间接路径，也不代表整个应用安全。没有匹配的入口、sink 或步骤顺序一律不能作为实际程序不可达的证明。

## 2. 路径与风险判据分开

一个深链把 URL 传给内部 WebView，即使没有 JavaScript 桥，也可能形成候选路径。桥风险 J4 不适用，不应遮蔽这条路径。

路径核验检查以下证据：

- `Chain.evidence_complete=true`；
- 至少一个步骤，每步有文件名和正数物理行号；
- 存在完整的 J6；已有 J1、J2、J5、J6 不能为 FAIL 或 UNKNOWN；
- 当前报告没有警告、不可分析加固或已知降级索引状态。

J3（影响）和 J4（桥风险）不作为路径一致性的支持条件。风险结论继续由分析报告中的独立判据表达。匹配候选链时优先选择证据完整的链，不让同一入口的一条不完整路径遮蔽另一条完整路径。

这些检查仍然基于报告，不是第二套独立的程序分析器。工件来源和代码内容的一致性由工件层检查。

## 3. 覆盖范围与实际降级

每个裁决包含 `coverage`：

```json
{
  "scope": "static_analysis_report",
  "closed_world": false,
  "report_usable": true,
  "negative_conclusions_limited": true,
  "reasons": [],
  "limitations": ["Call paths are bounded to depth 4."]
}
```

`closed_world` 保留用于旧消费者读取，0.2 中恒为 false。它不再将“解析没有警告”解释成全程序语义完整。`report_usable` 表示本次分析没有已记录的故障，可用于范围明确的报告核验；不是安全证明。

`limitations` 始终包含当前分析器固定限制：调用深度 4；本 APK 内显式 Intent 跨组件一跳；非完整分支/路径敏感；反射、JNI、动态加载、异步回调未完整建模；参数、实例和别名传播不完整。

`reasons` 记录本次实际遇到的分析警告、加固或索引降级。存在这些条件时输出为 `UNDECIDABLE / OUTSIDE_COVERAGE`，同时保留已有步骤证据供继续调查。固定限制不使所有正面匹配失效；它们限定了该匹配能够说明什么。

## 4. Claim

```json
{
  "schema_version": "0.2",
  "claim_id": "optional-stable-id",
  "kind": "reachability",
  "entry": {"kind": "component", "name": "com.example.app.MainActivity"},
  "sink": {"kind": "webview"},
  "asserted_steps": [{"sink": "cross_component"}, {"sink": "webview"}],
  "assumptions": []
}
```

- 只支持 `kind=reachability`。
- `entry.kind` 为 `component` 或 `deeplink`；`name` / `id` 至少提供一个。
- 组件名称支持全名、`.MainActivity`、`MainActivity`；后两者按报告包名补全。
- 深链支持报告内 ID 或规范 URI `scheme://host/path`；多义需改用 ID。
- `sink.kind` 可为 `any`、`bridge`（`bridge_method` 别名），或步骤词表：`webview`、`bridge_method`、`file`、`file_ownership`、`call`、`external_storage`、`content_provider`、`command_exec`、`cross_component`、`clipboard`、`result_callback`、`unknown`。词表可接受不代表分析器对每种行为都完整建模。
- `asserted_steps` 按 `Step.sink` 顺序做子序列匹配，不要求等于整条链。
- `assumptions` 每项包含唯一 `id`、`text` 和可选 `source`。带假设的支持结论上限为 `SUPPORTED_WITH_ASSUMPTIONS`。
- 未提供 `claim_id` 时，用规范化的当前版本数据生成稳定 ID。
- 未知输入字段忽略；必需字段或词表非法时返回输入错误。

## 5. Verdict

```json
{
  "schema_version": "0.2",
  "claim_id": "optional-stable-id",
  "status": "SUPPORTED",
  "reason_code": "CHAIN_FOUND",
  "scope": "static_analysis_report",
  "statement": "A matching candidate path has complete evidence in this static-analysis report. Runtime feasibility and vulnerability impact have not been independently proven.",
  "failed_judgment": null,
  "evidence": [
    {"step": 0, "sink": "webview", "description": "URL reaches loadUrl", "file": "smali/example/Main.smali", "line": 54, "snippet": "invoke-virtual ..."}
  ],
  "counterexample": null,
  "missing_facts": [],
  "coverage": {
    "closed_world": false,
    "scope": "static_analysis_report",
    "report_usable": true,
    "negative_conclusions_limited": true,
    "reasons": [],
    "limitations": ["Call paths are bounded to depth 4."]
  },
  "assumptions_used": []
}
```

此处 `limitations` 为简化示例，实际输出提供全部固定限制。证据文件行号是 smali 物理行，不是反编译 Java 源码行。

主要 `reason_code`：

| 原因码 | 状态与意义 |
|---|---|
| `CHAIN_FOUND` | SUPPORTED 或 SUPPORTED_WITH_ASSUMPTIONS：报告中有匹配路径 |
| `NOT_ZERO_PERMISSION` | REFUTED：manifest 的直接入口条件阻断；警告存在时降级 |
| `ENTRY_NOT_FOUND` | UNDECIDABLE：当前报告中没有该入口 |
| `STEP_MISMATCH` / `SINK_MISMATCH` | UNDECIDABLE：当前报告中的路径不匹配；回显候选证据 |
| `IMPL_MISSING` | UNDECIDABLE：实现未在报告中找到 |
| `EVIDENCE_INCOMPLETE` | UNDECIDABLE：路径证据或相关判据不完整 |
| `NEGATIVE_NOT_DEFINITIVE` | UNDECIDABLE：只有不足以证明不可达的反例 |
| `NO_ANALYSIS_RESULT` | UNDECIDABLE：该入口没有候选路径 |
| `OUTSIDE_COVERAGE` | UNDECIDABLE：本次报告有实际分析警告、加固或降级 |

## 6. 开放问题与回答

```bash
reachscope questions --report out/report.json --out out/questions.json
```

问题由报告派生：证据不完整、判据未知、实现缺失、反例不确定、警告和不可分析加固。每条问题包含稳定 `question_id`、`subject`、`why`、证据位置、回答类型。

```json
{
  "schema_version": "0.2",
  "answers": [{"question_id": "858db094", "value": "false", "source": "model"}]
}
```

回答引用当前报告的问题 ID。未知 ID、重复 ID、空值或不符合问题类型的值为输入错误。每条回答仅生成 `answer:<question_id>` 假设，出现在 `assumptions_used` 中。回答不会修改报告、补齐代码证据或让一个原本不可判定的路径获得支持。

如果路径本来就有完整证据，仅风险判据未知，则路径核验可以得到支持；附带回答时仍必须标记为 `SUPPORTED_WITH_ASSUMPTIONS`。这不意味着回答的内容已被验证。

## 7. CLI 与回放

```bash
# 生成分析报告
reachscope scan app.apk --out out --apktool /path/to/apktool.jar

# 列出分析缺口
reachscope questions --report out/report.json

# 核对主张
reachscope verify --report out/report.json --claim claim.json

# 带回答核对；回答只成为假设
reachscope verify --report out/report.json --claim claim.json --answers answers.json
```

`verify` 的 stdout 为 UTF-8 JSON，日志在 stderr。退出码 0 表示核验完成，包括 REFUTED / UNDECIDABLE；输入错误为 2，内部错误为 4。`--out` 将 JSON 写入文件。

无 APK / Java 的回放见 `examples/protocol/README.md`；测试见 `tests/integration/test_protocol_demo.py`。

## 8. 从 0.1 迁移

- 输入 claim 和 answers 接受 0.1 / 0.2；解析后规范化为 0.2。未知版本拒绝。
- 自动生成的 claim ID 基于规范化后的版本计算，可能与 0.1 工具生成的 ID 不同。调用者显式提供的 ID 保留。
- 输出统一为 0.2，新增 `scope`、`statement` 以及 coverage 中的范围字段。
- `closed_world` 恒 false。用 `report_usable` 理解本次报告是否存在已记录的降级，不能将它当作全程序完备性。
- 错误入口、sink、步骤不再作为实际不可达的 REFUTED 结论。
- 影响或桥风险判据不再阻断完整候选路径的报告支持。因此旧的 J4 反例可能与 SUPPORTED 路径并存。
- JSON **分析报告**仍使用独立 schema 0.1。文件读取要求明确支持的报告版本；缺失或未知版本拒绝。内部 IR 构造并不承担文件版本协商。
