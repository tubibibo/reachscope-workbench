# 真实 APK 语料（T5.3）

> 语料只在本机 `<LOCAL_PROJECT_ROOT>/corpus/` 使用，**APK 不入库**。
> 所有扫描命令的输出均写到仓库外的临时目录。

## 1. 选样与来源

| # | 应用 | 版本 | 包名 | 大小 | SHA-256 | 来源 |
|---|---|---|---|---|---|---|
| 1 | K-9 Mail | 24.0 | `com.fsck.k9` | 10.9 MB | `6b80ec681f0c882ca334f4d533778e6e50e814ee214db798d9e129a369a85af4` | [thunderbird-android releases](https://github.com/thunderbird/thunderbird-android/releases) |
| 2 | NewPipe | 0.29.1 | `org.schabi.newpipe` | 11.5 MB | `18447bfb1e06d113edc88df93f471827280de06f6f3d4dc42f56f28b9c1bab79` | [TeamNewPipe/NewPipe releases](https://github.com/TeamNewPipe/NewPipe/releases) |
| 3 | ownCloud | 4.8.4 | `com.owncloud.android` | 14.4 MB | `96bd21df0bec3fa3736b3bd0070c0b51891dc510a5a9808c195ce60da7772b4d` | [owncloud/android releases](https://github.com/owncloud/android/releases) |

选样口径：公开可下载、开源、体积适中（10–15 MB）、都有导出组件与深链，且类型不同（邮件 / 媒体 / 云盘）。

环境：ReachScope 0.1.0、apktool 2.11.1、JDK 17、Windows 11；分析日期 2026-10-19。

## 2. 复现命令

```bash
python -c "import sys; from reachscope.cli import main; sys.exit(main())" scan \
  <apk> --out <仓库外目录> --apktool <apktool.jar>
```

## 3. 结果

| 指标 | K-9 Mail | NewPipe | ownCloud |
|---|---|---|---|
| 组件 / 其中 exported | 61 / 11 | 33 / 9 | 43 / 8 |
| 深链 | 3 | 4 | 2 |
| WebView 汇点 | 1 | 3 | 2 |
| JS 桥 | 0 | 0 | 0 |
| 链 | 0 | 0 | 0 |
| findings | 0 | 0 | 0 |
| 反例 | 11 | 9 | 8 |
| 退出码 | 0 | 0 | 0 |

三份报告都没有崩溃，退出码均为 0。

### 反例形状

- K-9 Mail：11 条全部停在 **J5**（`no attacker-controlled flow reaches a sink in entry methods`）。
- NewPipe：9 条，8 条 J5、1 条深链 J5（`RouterActivity` 解析 `http(s)`/YouTube 链接，但入口方法到不了 WebView/sink）。
- ownCloud：8 条，全部 J5（含 `LoginActivity` 的 OAuth 回跳深链）。

这正是工具要回答的问题：**导出组件和深链本身不是漏洞**，从入口到危险 sink 的数据流才是。

## 4. 正控 APK（验证 high 路径）

公开语料三份都是阴性，无法证明“工具能出 high 链”。因此增加一个**正控**：

- 来源：`tests/fixtures/cases/01_positive_deeplink_bridge_sink`（项目自带 fixture），用 apktool 重新打包成 APK；
- 内容：导出 Activity + `myapp://open.example.com/web` 深链 + 无来源校验的 `loadUrl` + `@JavascriptInterface` 桥方法读文件；
- 打包命令：`apktool b <fixture> -o <仓库外>/rs-control.apk`（fixture 不是 APK，仓库里也不放 APK）；
- 结果：`components=1 / deeplinks=1 / webviews=1 / bridges=1 / chains=1 / findings=1 / counter_examples=0`，finding 三元组 **high / high / high**，退出码 0。

**性质说明**：这是合成正控，不是真实应用；作用是证明“深链 → WebView → 桥 → 文件 sink”这条路径在完整 CLI（apktool 解码 → 提取 → 判定 → 报告）上确实能产出 high，而不是只靠单元测试。

## 5. 额外负样本（非正式语料）

| 应用 | 版本 | 结果 | 说明 |
|---|---|---|---|
| AndroGoat | 2.0.1 | 0 链 / 6 反例 | 3 个 WebView，但加载 URL 的 Activity 未导出；J5 正确判负 |
| OWASP MASTG (Android Java) | 1.1 | 0 链 / 1 反例 | 检出 2 个 JS 桥，但页面是固定 `file:///android_asset/` 与常量 URL，桥不暴露给攻击者可控页面 |
| Damn Vulnerable Bank | 1.1.0 | 0 链 / 6 反例 | 无入口可达的桥/sink |
| InsecureBankv2 | 2.3.1 | 0 链 / 7 反例 | 同上 |

故意脆弱的 App 也未必命中本工具的判据——它们的漏洞类型（日志、存储、硬编码、越权）不在“WebView 桥/深链可达性”这条轴上。

## 6. 未完成的语料

- DuckDuckGo 5.298.1（82.8 MB，83k smali / 471k 方法）：`build_index` 在本机耗时 20–40+ 分钟、峰值 RSS 3.7 GB，超过 v0.1 的 §9.4 预算。已在 `PROGRESS.md` 记录为已知限制，未纳入本次对照。
- Home Assistant 2026.8.4（38.7 MB，含 2 处 `addJavascriptInterface`）：解码成功，索引阶段本机内存不足，后台进程被系统终止；未产出报告，不计入结果表。按“超出 v0.1 规模预算”记录，与 DuckDuckGo 同类。

## 7. 本次语料暴露的限制

1. **资源引用未解析**：ownCloud 的深链是 `@string/deep_link_uri_schemes`，报告里原样保留，未解析成实际 scheme；不影响“0 链”的结论，但会漏掉部分深链入口。
2. **大 APK 无降级路径**：整份索引，没有“只索引被引用类”的模式（§9.4），DuckDuckGo 级别不可用。
3. **真实应用的桥多为常量页面**：桥存在但页面 URL 不可控时，J5 正确地判负；这类结果需要人工复核，避免把“工具未发现”当成“应用无风险”。
