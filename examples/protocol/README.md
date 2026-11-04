# 协议回放示例

全部输入来自 `tests/golden/*.json`，**不需要 APK、不需要 apktool**。

输出协议为 0.2；示例输入保留 0.1，演示向后兼容。所有状态仅针对当前静态分析报告：
`SUPPORTED` 表示匹配到带证据的候选路径，不证明运行时路径可行或漏洞成立。

```bash
cd reachscope

# 工具提问
python -m reachscope questions \
  --report tests/golden/09_origin_check_before_load.json

# 正控：完整链 → SUPPORTED
python -m reachscope verify \
  --report tests/golden/01_positive_deeplink_bridge_sink.json \
  --claim examples/protocol/claims/supported.json

# J1 否定：签名级权限 → REFUTED
python -m reachscope verify \
  --report tests/golden/02_signature_permission.json \
  --claim examples/protocol/claims/refuted_permission.json

# 模型臆造步骤 → UNDECIDABLE / STEP_MISMATCH（回显真实步骤）
python -m reachscope verify \
  --report tests/golden/01_positive_deeplink_bridge_sink.json \
  --claim examples/protocol/claims/step_mismatch.json

# 强加固报告 → UNDECIDABLE / OUTSIDE_COVERAGE
python -m reachscope verify \
  --report tests/golden/08_hardened_app.json \
  --claim examples/protocol/claims/undecidable_hardened.json

# 带显式假设 → SUPPORTED_WITH_ASSUMPTIONS
python -m reachscope verify \
  --report tests/golden/01_positive_deeplink_bridge_sink.json \
  --claim examples/protocol/claims/with_assumptions.json

# J4 风险反例不遮蔽数据路径；带回答 → SUPPORTED_WITH_ASSUMPTIONS
python -m reachscope verify \
  --report tests/golden/09_origin_check_before_load.json \
  --claim examples/protocol/claims/blocked_deeplink.json \
  --answers examples/protocol/answers.json
```

`answers.json` 里的 `858db094` 是 `questions` 对
`09_origin_check_before_load.json` 生成的 `NEGATIVE_NOT_DEFINITIVE` 问题 ID；
更换报告后请重新生成问题，不要复用旧 ID。

最后一个示例中，路径本来就在报告里；来源校验等风险判据与路径一致性分开处理。
回答仍是未验证假设，不能填补缺失代码证据。证据不完整的路径即使收到肯定回答，
仍返回 `UNDECIDABLE`。错误步骤只表明报告不匹配，不能证明程序不存在其他路径。

集成测试：`tests/integration/test_protocol_demo.py`。
