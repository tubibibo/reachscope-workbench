# Fixture 矩阵

这些 fixture 是 **T5.1 的验收基线**，也是 T1.2 / T1.3 / T2.x / T3.x 单元测试的输入。

## 约定

- `AndroidManifest.xml` 是 **apktool 解码后的文本 XML**，不是二进制 AXML。
- `smali/` 下的文件**只用于解析，不参与编译**。语法保持真实，但不保证能回编。
- 所有类名统一用 `com.example.app` 包，避免刻意混淆，便于断言。
- 每个 case 目录下必须有 `expected.json`。
- 可选 `protection.json`：存在时，测试 harness 用它替代真实 APKiD 结果。

## expected.json 结构

```json
{
  "case": "<目录名>",
  "description": "<一句话说明这个 case 验证什么>",
  "expect": {
    "exit_code": 0,
    "analyzable": true,
    "components": {
      "<类的全限定名>": {
        "exported": true,
        "impl_present": true,
        "permission_protection": null
      }
    },
    "deeplinks": [
      {"scheme": "myapp", "host": "open.example.com", "component": "com.example.app.MainActivity"}
    ],
    "bridges": [
      {
        "impl_class": "com.example.app.JsBridge",
        "revoked": false,
        "origin_check_strength": "none",
        "origin_check_location": "none",
        "origin_check_effective": false
      }
    ],
    "findings": [
      {
        "exploitability": "high",
        "impact": "high",
        "confidence_at_least": "medium",
        "chain_must_include": ["loadUrl", "FileInputStream"]
      }
    ],
    "counter_examples": [
      {
        "entry_kind": "component",
        "failed_judgment": "J1",
        "reason_contains": "signature-level permission"
      }
    ]
  }
}
```

### 断言语义

| 字段 | 语义 |
|---|---|
| `exit_code` | 进程退出码，精确匹配 |
| `analyzable` | `Protection.analyzable`，精确匹配 |
| `components` | 只断言列出的类；未列出的不约束 |
| `deeplinks` | 集合包含即可，不要求顺序 |
| `bridges` | 按 `impl_class` 匹配；`origin_check_*` 精确匹配；`bypass_reason_non_empty=true` 表示该字段必须非空 |
| `findings` | 至少存在一条满足全部约束的 Finding |
| `counter_examples` | 至少存在一条满足全部约束的反例 |
| `chain_must_include` | 链的 `steps[].sink` 或 `description` 中必须出现的子串 |

**未在 expected.json 中出现的字段不做断言**，避免 fixture 过度耦合实现细节。

`reason_contains` 匹配的是英文子串，取值参照 `PLAN.md` §6.3 给出的判据原文（如 `signature-level permission`、`implementation class not found`）。实现时不要改写成中文，否则这里会失配。

## protection.json

存在时，harness 读取该文件并替代真实 APKiD 结果，字段与 `Protection` 一致：

```json
{"detected": true, "tool": "apkid", "labels": ["packer::dexguard"], "analyzable": false}
```

## Case 清单

| # | 目录 | 验证点 | 期望 |
|---|---|---|---|
| 01 | `01_positive_deeplink_bridge_sink` | 深链 URL 直灌 + 无校验 + 未撤销桥 + 任意文件读 | Finding, high/high |
| 02 | `02_signature_permission` | exported 但签名级权限保护 | 反例 J1 |
| 03 | `03_missing_impl` | manifest 声明 exported，实现类不在包里 | 反例 J2 |
| 04 | `04_origin_strong_should_override` | 强校验但只在 `shouldOverrideUrlLoading`（拦不住首次 loadUrl） | Finding，附 `effective=false` 证据 |
| 05 | `05_origin_weak_concat` | `contains` 作用于 host+path 拼接 | Finding，`bypass_reason` 命中 |
| 06 | `06_bridge_partial_revoke` | 注册两个桥，只撤销其中一个 | 未撤销的桥 `revoked=false` |
| 07 | `07_own_cache_only` | 桥方法只读自身 cache 目录 | Finding, impact=low |
| 08 | `08_hardened_app` | 加固包 | 退出码 3，`analyzable=false` |
| 09 | `09_origin_check_before_load` | 强校验且在 `loadUrl` 之前生效 | 反例 J4 |

## 如何新增 case

1. 建目录 `NN_<snake_case_描述>/`
2. 放 `AndroidManifest.xml` + 最小 `smali/`
3. 写 `expected.json`
4. 在本文件表格追加一行
5. 跑 `pytest tests/unit/test_golden.py -k NN`（T5.2 完成后）
