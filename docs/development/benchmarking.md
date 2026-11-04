# 基准评测（v0.2 基线 / v0.3 更新）

> 目的：给出可复现的检出数字，而不是只靠 9 个 fixture 和「三份真实应用 0 链」。
> 语料只在本机 `<LOCAL_PROJECT_ROOT>/corpus/`，**APK 不入库**；仓库里只保存
> `benchmark/ground_truth.json`（文件名 + sha256 + 期望）与评测脚本。

## 1. 口径

ReachScope 只判一件事：**入口 → 危险 sink 的数据流是否可达**。ground truth 只收录
落在这条轴上的漏洞；其它类型（日志、硬编码、存储、越权）标为 out of vocabulary，
只记录、不计入检出率。

每条 expectation 的结果：

| 状态 | 含义 |
|---|---|
| `detected` | 入口存在，且至少一条链的 sink 序列包含期望 sink（子序列匹配） |
| `partial` | 入口有链，只走到 `accept_partial` 声明的第一跳，期望 sink 未连通 |
| `miss` | 入口不在报告里，或入口没有任何链 |
| `out_of_vocabulary` | 漏洞类型不在当前 sink 词表内，不判分 |
| `no_chain_ok` | 阴性检查（`expect_no_chain`）：该入口 0 链，符合预期 |
| `unexpected_chain` | 阴性检查：该入口出现了链，**标记待人工复核**（不等于已判误报） |

阴性检查单独汇总为 `expect_no_chain_checks` / `expect_no_chain_violations`，
**不混进检出率**：检出率回答「该报的报了没」，阴性检查回答「不该报的报了没」。

findings 分两类：能映射回 ground truth 的记为 **explained**；剩下的记为
**unreviewed**，逐条列出供人工判真/假——脚本**不自动**把未匹配的 finding 当成误报。

## 2. 语料与 ground truth

| case | 角色 | 来源 | ground truth |
|---|---|---|---|
| `rs-control` | synthetic-positive | 项目 fixture 01 用 apktool 重新打包 | 深链 → `loadUrl` → JS 桥读文件 |
| `ovaa-1.0.0` | positive | [oversecured/ovaa](https://github.com/oversecured/ovaa) 1.0.0 | README #3/#4：`oversecured://ovaa/webview?url=...` → WebView `loadUrl` |
| `androgoat-2.0.1` | adversarial-negative | 靶场 | 已知漏洞不在本轴 |
| `mastg-android-java-1.1` | adversarial-negative | OWASP MASTG | 2 个 JS 桥，但页面固定为本地 asset |
| `dvba-1.1.0` | adversarial-negative | Damn Vulnerable Bank | 已知漏洞不在本轴 |
| `insecurebankv2-2.3.1` | adversarial-negative | 经典靶场 | 已知漏洞不在本轴 |
| `k9mail-24.0` | real-negative | 官方 release | 11 个导出入口，无桥 |
| `newpipe-0.29.1` | real-negative | 官方 release | RouterActivity 只做路由 |
| `owncloud-4.8.4` | real-negative | 官方 release | OAuth 回跳深链到不了 sink |
| `duckduckgo-5.298.1` | scale-limit（跳过） | 官方 release | 82.8 MB，无降级索引 |
| `homeassistant-2026.8.4` | scale-limit（跳过） | 官方 release | 38.7 MB，索引 OOM |

OVAA 另外两条 expectation（#1 凭据外发、#2 grant URI permissions）标为
out of vocabulary：前者是网络 sink，后者依赖攻击者组件回传 Intent 结果，均不在
当前模型内。

M1 起，阴性 case 不再只靠「findings=0」间接说明：在 6 个真实/靶场 case 上标注了
10 个已知无链入口（`expect_no_chain`），覆盖深链入口（k9mail `MessageCompose`、
newpipe `RouterActivity`、ownCloud `LoginActivity`）、OAuth 回调、广播接收器与
固定 asset 页面。它们只验证「不该出链的没出链」，不参与检出率。

## 3. 复现

```bash
python scripts/benchmark/run_benchmark.py \
  --corpus-dir ../local-corpus \
  --out ../local-runs/reachscope-bench \
  --apktool ../local-tools/apktool.jar

# 只读已有报告
python scripts/benchmark/run_benchmark.py ... --skip-scan
```

输出 `benchmark-result.json`（机器可读）与 `benchmark-report.md`（表格）。

## 4. 结果

### 4.1 v0.2 基线（2026-10-19，0.2.0）

| 指标 | 值 |
|---|---|
| 在范围内的 expectation | 2 |
| detected / partial / miss | **1 / 0 / 1** |
| 检出率 | **0.5** |
| out of vocabulary | 2（均为 OVAA） |
| findings（全部 case） | 1 |
| explained / unreviewed | 1 / 0 |

逐 case：

| case | 组件 | 深链 | 链 | findings | 反例 |
|---|---|---|---|---|---|
| rs-control | 1 | 1 | 1 | 1 | 0 |
| ovaa-1.0.0 | 12 | 1 | 0 | 0 | 7 |
| androgoat-2.0.1 | 35 | 0 | 0 | 0 | 6 |
| mastg-android-java-1.1 | 24 | 0 | 0 | 0 | 1 |
| dvba-1.1.0 | 21 | 2 | 0 | 0 | 6 |
| insecurebankv2-2.3.1 | 13 | 0 | 0 | 0 | 7 |
| k9mail-24.0 | 61 | 3 | 0 | 0 | 11 |
| newpipe-0.29.1 | 33 | 4 | 0 | 0 | 9 |
| owncloud-4.8.4 | 43 | 2 | 0 | 0 | 8 |

- **synthetic-positive 检出**：`myapp://open.example.com/web` → 链
  `webview → bridge_method → file`，high/high/high。证明完整 CLI 能端到端出链。
- **OVAA 漏报**：见下节。
- **7 个阴性/对抗阴性 case 全部 0 findings**，没有需要人工复核的 finding。
  这批语料证明了「不误报」，但没有证明「精度」——因为一个真阳性都没有出现。

### 4.2 v0.3 更新（2026-10-19，0.3.0）

补上跨组件边（显式 Intent + 攻击者数据，一跳）后重跑全部 9 个可运行 case：

| 指标 | v0.2 | v0.3 |
|---|---|---|
| 在范围内的 expectation | 2 | 2 |
| detected / partial / miss | 1 / 0 / 1 | **2 / 0 / 0** |
| 检出率 | 0.5 | **1.0** |
| findings（全部 case） | 1 | 1 |
| explained / unreviewed | 1 / 0 | 1 / 0 |

逐 case（仅列出变化）：

| case | 链 | findings | 反例 | 说明 |
|---|---|---|---|---|
| ovaa-1.0.0 | **1** | 0 | 7 | 链 `call → cross_component → webview` |
| rs-control | 1 | 1 | 0 | 不变（`webview → bridge_method → file`） |
| 其余 7 个阴性/对抗阴性 | 0 | 0 | 不变 | **0 链、0 findings** |

- **OVAA 从 `miss` 变为 `detected`**，且链的入口仍是导出的 `DeeplinkActivity`，
  跨组件步指向未导出的 `WebViewActivity`。
- **OVAA 仍是 0 findings**：现有 finding 要求「桥 + WebView 配对」（J4），
  OVAA 是「深链参数直灌 WebView」，不是桥暴露。有链≠有 finding，见下节。
- **注意**：7 个阴性 case 本身不含「显式 Intent + 攻击者数据」的跨组件流，
  所以它们只能说明没有引入明显误报，**不能验证新启发式的精度**。见 §7。

### 4.3 M1 更新（2026-10-20）：跨组件事实收紧

把跨组件边从「有攻击者数据 + 有显式目标」收紧为「源侧载体/key 与目标侧读取对得上，
启动方法与目标类型自洽」后重跑全部 9 个可运行 case：

| 指标 | v0.3 | M1 |
|---|---|---|
| 全套测试 | 540 | **552** |
| 覆盖率 | 92.30% | **92.06%** |
| 在范围内的 expectation | 2 | 2 |
| detected / partial / miss | 2 / 0 / 0 | **2 / 0 / 0** |
| 阴性检查（expect_no_chain） | 0 | **10，违规 0** |
| findings（explained / unreviewed） | 1 / 0 | 1 / 0 |

逐 case：

| case | 链 | findings | 反例 | 说明 |
|---|---|---|---|---|
| ovaa-1.0.0 | 3 | 0 | 7 | 深链链 `call → cross_component(extra "url") → webview`，`evidence_complete=True`；Service / Provider 入口各一条 file 链（M1 按组件类型补入口方法后出现） |
| rs-control | 1 | 1 | 0 | 不变 |
| 其余 7 个阴性/对抗阴性 | 0 | 0 | 不变 | **0 链、0 findings** |

- **OVAA 的 key 可回放**：`DeeplinkActivity.smali:211` 的 `putExtra(v2, v1)` 中 `v2`
  被多个分支复用；M1 用基本块级到达定义恢复出常量 `"url"`，跨组件步描述为
  `explicit Intent → WebViewActivity (extra "url")`，目标
  `WebViewActivity.getStringExtra("url")` 与之匹配。
- **10 条阴性检查全部 `no_chain_ok`**：k9mail（`MessageCompose`、OAuth 回调）、
  newpipe（`RouterActivity`、`PanicResponderActivity`）、ownCloud（`LoginActivity`、
  `ReceiveExternalFilesActivity`）以及三份靶场的 4 个无链入口。
- **OVAA 仍 0 findings**：J4 未放宽；有链≠有 finding（§5.3）。

### 用时（同一台机器，单进程）

| case | v0.3 | M1 | 变化 |
|---|---|---|---|
| rs-control | 1.6 s | 1.6 s | 0% |
| ovaa | 192.2 s | 179.7 s | −6.5% |
| androgoat | 205.0 s | 201.6 s | −1.7% |
| mastg | 54.4 s | 69.3 s | +27% |
| dvba | 49.2 s | 62.7 s | +27% |
| insecurebankv2 | 173.5 s | 224.1 s | +29% |
| k9mail | 323.0 s | 410.4 s | +27% |
| newpipe | 292.5 s | 383.8 s | +31% |
| owncloud | 581.2 s | 624.0 s | **+7.4%** |

- 验收只约束 ownCloud（+10% 以内）：**+7.4%，通过**。
- 中小 APK 的 +27–31% 主要来自新增的一层过程间污点与按组件类型的入口分析；
  这些开销与入口方法数量相关，后续如成为瓶颈可加方法级缓存。
- 绝对值受同机 MobSF 进程与磁盘缓存影响，单次运行有 ±10% 噪声。

3–14 MB 的 APK 需要半分钟到十分钟；这是当前实现（无降级索引）的可用性边界。

## 5. 关键个案：OVAA

### 5.1 v0.2 为什么漏

OVAA 的漏洞是 `oversecured://ovaa/webview?url=...`：

1. `DeeplinkActivity.onCreate` 取 `uri.getQueryParameter("url")`；
2. host 校验 `host.endsWith("example.com")`（`evilexample.com` 可过）；
3. 用 `Intent.putExtra("url", url)` 启动**未导出**的 `WebViewActivity`；
4. `WebViewActivity.onCreate` 执行 `loadUrl(getIntent().getStringExtra("url"))`。

v0.2 的报告里，两半都看到了：

- 深链入口：`oversecured://ovaa` → `DeeplinkActivity`；
- WebView 汇点：`WebViewActivity.onCreate` 的 `loadUrl`，`url_sources=[intent_extra]`。

但链是 0，`DeeplinkActivity` 的反例写着
`J5 / no attacker-controlled flow reaches a sink in entry methods`。

原因有两处模型边界：

1. **Intent extra 不传播污点**：`graph/regflow.py` 不跟踪 `Intent.putExtra` 之后
   Intent 对象被污染；`startActivity(i)` 的实参 `i` 在寄存器流里不是攻击者数据。
2. **没有跨组件边**：即使第一跳成立，模型也不把 `startActivity` 的目标组件接进来。

所以这条反例在工具内部自洽（入口方法内确实没有 sink），现实世界却是**假阴性**。

### 5.2 v0.3 如何补上

`analyze/intercomponent.py` 增加一个有界分析：方法内若出现「显式 Intent 目标 +
攻击者可控数据放入 Intent + 启动调用」，就产出一条跨组件边；`chains.py` 把这条边
接成 `cross_component` 步骤，再分析目标组件的入口方法。OVAA 的结果：

```
call             DeeplinkActivity.processDeeplink
cross_component  DeeplinkActivity → WebViewActivity   (DeeplinkActivity.smali:214, extra "url")
webview          WebViewActivity.onCreate → loadUrl   (WebViewActivity.smali:92)
```

链入口仍是导出的 `DeeplinkActivity`，目标 `WebViewActivity` 未导出也照样分析。

M1 之后，这条边还要通过载荷匹配：源侧 `putExtra("url", tainted)` 的 key 必须与
目标侧 `getStringExtra("url")` 的 key 相同（或数据载体同为 `data`）。key 不同、
载体不同都不再成链；key 不可静态确定时保留链但标 `evidence_complete=false`。
分支同时到达仍不建模，见 §7。

### 5.3 残留差距：有链，无 finding

OVAA 现在有链，仍是 0 findings。现有 finding 语义绑定 J4「桥 + WebView 配对」，
而 OVAA 是「深链参数直灌 WebView」，没有桥。工具内部因此给出
`J4 no bridge + WebView pair for this chain` 的反例。

没有为了让这一个样本出 finding 而放宽 J4：那会把 finding 从「桥攻击面」扩成
「任意可达 sink」。正确做法是单独设计 finding 族（例如 `webview_url_injection`）
与对应判据，见 §8。

## 6. 与 MobSF 的对照（OVAA）

MobSF 4.5.4 对同一个 APK 的静态结果：

- 6 条 code findings，其中 `android_webview_allow_file_from_url`
  （`WebViewActivity.java:25-26`，CVSS 6.1）正好指向危险设置；
- 3 个导出 activity + 1 个 browsable：`DeeplinkActivity`（scheme `oversecured://`，
  host `ovaa`）；
- 3 条 high、12 条 warning，manifest 层逐条列出 "not protected"。

对照更新到 v0.3：

| | MobSF | ReachScope v0.2 | ReachScope v0.3 |
|---|---|---|---|
| 看到深链入口 | ✅ browsable activity | ✅ deeplink 记录 | ✅ |
| 看到危险 WebView 设置/汇点 | ✅ `setAllowFileAccessFromFileURLs` | ✅ `loadUrl(intent_extra)` | ✅ |
| 入口 → sink 的链 | ❌ | ❌ | ✅ `call → cross_component → webview` |
| 反例/否定证据 | ❌ | ✅（假阴性） | ✅（有链，但无 finding 判据） |

这个对照仍说明 ReachScope 的差异点在**可达性裁决**：把两端的组件与配置都识别
出来不等于连得起来。v0.3 补上了这条边，但边的数据事实仍偏粗（§7）。

## 7. 有效性威胁

- 语料小：只有 1 个真实正控（OVAA）+ 1 个合成正控 + 7 个阴性；检出率 1.0 的
  置信区间很宽，不能外推。
- ground truth 由单人标注；OVAA 的 #3/#4 依赖 README 与源码人工对齐。
- OVAA 用的是 `app-debug.apk`；release 构建的混淆/裁剪可能改变结果。
- **精度样本仍少**：M1 加了 10 个真实语料阴性入口与 14 个判别性 smali fixture，
  但没有新增真实正控；不能用这些数字外推真实世界精度。
- **key 匹配是语法级的**：只认源侧常量 key；key 来自变量时链保留但
  `evidence_complete=false`（协议只能 `UNDECIDABLE`），不会自动判死。
- **过程间只走一层**：`launch(Intent)` 这类单层封装可跟；经字段、容器、回调
  （`onActivityResult`、`Handler`、协程）转存的数据仍会漏。
- **分支只对 key 敏感**：`putExtra` 的 key 按基本块到达定义取（OVAA 的跨分支
  寄存器复用已修）；其余污点仍按线性最后一次定义，互斥分支上「写了但没走到」
  的值仍可能被当成来源。
- **来源判定仍按调用点身份**：目标组件的 `getStringExtra` 只要 key 对得上就视为
  攻击者可控，不进一步证明该值确实来自入口 Intent 的同一实例（跨组件约束已把
  范围收窄到 key/载体，但仍是过近似）。
- 规模上限未变：DDG / Home Assistant 仍因时间与内存被跳过。

## 8. 结论与下一步

1. **跨组件边已收紧（M1）**：`CrossComponentHop` 现在带「载体 + key + 写入点」，
   目标侧读取 key 无交集不建链；key 不可判定时标 `evidence_complete=false`，
   协议只能给 `UNDECIDABLE`。入口 Intent 作为源锚点，启动方法绑定目标类型。
2. **过程间与表达式污点已补一层**：`launch(Intent)`、`Uri.parse`、`StringBuilder`
   / `String.format` 等单层传播可跟；更深路径仍是已知边界。
3. **证据与去重已修**：跨组件步回放 `extra "url"` / `data`；dead-end hop 的反例
   写「跨组件流到 X 但目标无 sink」；dedup 键包含跨组件目标。
4. **finding 升级单独做**：新增 `webview_url_injection` 判据（J7），不扩 J4；
   在此之前 OVAA 保持「有链、无 finding」，如实展示。
5. **再谈精度与规模**：先补设计过的近失阴性（key 不对应、互斥分支、错误组件
   类型等），再扩到 ≥5 个真实正控；ownCloud 8.7 分钟已接近上限，性能 profiling
   排在数据语义之后。
6. **MCP 继续后置**：它是传输层；在 verdict 的输入（链）尚未被收紧前接 MCP，
   只会把过近似更快地送到模型面前。
