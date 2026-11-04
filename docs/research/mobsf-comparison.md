# 与 MobSF 的对照（T5.3）

> MobSF 4.5.4（官方源码安装，Python 3.12，Windows 11），对本目录 `docs/development/corpus.md` 的三份 APK 各跑一次静态扫描。
> ReachScope 0.1.0 对同一批 APK 各跑一次。两边都只做**离线静态分析**。

## 1. 结果总表

| 指标 | K-9 Mail | NewPipe | ownCloud |
|---|---|---|---|
| MobSF 安全分 | 40 | 45 | 40 |
| MobSF high / warning | 5 / 14 | 1 / 11 | 4 / 8 |
| MobSF 导出组件（a/s/r/p） | 5/2/2/1 | 3/2/3/0 | 2/3/1/1 |
| MobSF browsable activities | 2 | 1 | 1 |
| MobSF manifest findings | 15 | 10 | 9 |
| **MobSF code findings** | **0** | **0** | **0** |
| ReachScope 导出组件 | 11 | 9 | 8 |
| ReachScope 深链 / WebView / 桥 | 3 / 1 / 0 | 4 / 3 / 0 | 2 / 2 / 0 |
| ReachScope 链 / findings | 0 / 0 | 0 / 0 | 0 / 0 |
| **ReachScope 反例** | **11** | **9** | **8** |

## 2. 两边各自覆盖什么

| 能力 | MobSF | ReachScope |
|---|---|---|
| 导出组件清单 | ✅（按类型计数 + 逐条 “not protected”） | ✅（含 `exported` / 权限保护 / 实现存在性） |
| 深链 / browsable 解析 | ✅（scheme/host/path 汇总） | ✅（逐元素展开，关联到组件） |
| 危险权限 / 证书 / 网络安全配置 / tracker | ✅ | ❌（不在本工具范围） |
| 硬编码密钥、字符串、二进制/恶意特征 | ✅ | ❌ |
| WebView / JS 桥识别 | 弱（仅规则命中，未见专门桥模型） | ✅（注册点、名字、撤销、来源校验） |
| 入口 → sink 的可达性 | ❌ | ✅（寄存器级回溯源 + 深度 4 调用图） |
| 利用性 / 影响 / 置信度三元组 | ❌（只有安全分与严重度标签） | ✅（§6.5 排序） |
| **反例**（看起来危险但不可达） | ❌ | ✅（每个入口一条，带失败判据） |

## 3. 逐项解读

### K-9 Mail

- MobSF：5 条 high 主要是**证书 MD5、cleartext 流量、信任用户证书、minSdk 过低**；manifest 层把 5 个 activity / 2 个 service / 2 个 receiver / 1 个 provider 标成 “not protected”；`code_analysis.findings = 0`。
- ReachScope：11 个导出入口全部走到 **J5 失败**（入口方法到不了 WebView/sink），0 桥、0 链。3 条深链（`msauth`、`mailto`、`com.fsck.k9`）都能提取，但没有一条接到危险 sink。
- 结论不矛盾：MobSF 说的是“这些组件对外可见”，ReachScope 说的是“可见但没有可达的危险数据流”。前者是暴露面，后者是可利用性。

### NewPipe

- MobSF：`RouterActivity` 是唯一 browsable activity；high 1 条（minSdk）；`code_analysis.findings = 0`。
- ReachScope：4 条深链（`http`/`https`/`vnd.youtube`/`vnd.youtube.launch`），9 个导出入口全部 J5 失败；`RouterActivity` 只做路由，入口方法不触达 WebView。

### ownCloud

- MobSF：2 个导出 activity（`ReceiveExternalFilesActivity`、`LoginActivity`）、3 个导出 service、1 个 provider；high 4 条（证书 SHA1、cleartext、信任用户证书、minSdk）。
- ReachScope：2 条深链（OAuth 回跳）指向 `LoginActivity`，8 个导出入口全部 J5 失败；报告的深链是 `@string/...` 未解析（见 `docs/development/corpus.md` §7）。
- MobSF 的 “LoginActivity is not protected” 与 ReachScope 的 “深链可达但到不了 sink” 是两个层次的事实。

## 4. 正控对照

ReachScope 的 fixture 01 重新打包成 APK 后：

- **ReachScope**：完整 CLI 产出 **1 条 high/high/high 链**（`docs/development/corpus.md` §4）。
- **MobSF**：识别出 1 个导出 Activity、`browsable` 的 `.MainActivity`，manifest findings 3 条（minSdk、allowBackup、Activity not protected），`code_analysis.findings = 0`。

也就是说，MobSF 能看到“这个 Activity 对外且可被浏览”，但看不到“深链参数经 `loadUrl` 进入带桥的 WebView，桥方法再读文件”这条链；也没有反例概念。

## 5. 定位差异（一句话）

- **MobSF 是广度扫描器**：清单、权限、证书、网络配置、密钥、tracker、恶意特征，回答“这个 App 有哪些风险面”。
- **ReachScope 是纵深判定器**：只盯 WebView 桥与深链，回答“哪一条攻击链能被零权限 App 真正走通”，并给出不可达的反例。

两者不是替代关系。真实项目里可以先用 MobSF 扫面，再用 ReachScope 对深链/桥做可达性裁决。

## 6. 复现

MobSF（本机源码安装）：

```bash
mobsf 127.0.0.1:8000
curl -H "X-Mobsf-Api-Key: $KEY" -F "file=@<apk>" http://127.0.0.1:8000/api/v1/upload
curl -H "X-Mobsf-Api-Key: $KEY" -X POST \
  -d "hash=<hash>&scan_type=apk&file_name=<name>.apk" \
  http://127.0.0.1:8000/api/v1/scan
```

ReachScope：

```bash
python -c "import sys; from reachscope.cli import main; sys.exit(main())" scan \
  <apk> --out <repo 外目录> --apktool <apktool.jar>
```

## 7. 已知偏差与限制

1. **两边“0 findings”不等于应用安全**：都只覆盖静态可达性/规则，不执行 App；动态、反射、加密字符串、服务端逻辑不在范围内。
2. **MobSF 的安全分不是可利用性**：40/45 分来自清单与配置项，和“有没有能走通的链”无关。
3. **ReachScope 的阴性需要人工复核**：J5 失败只说明“模型内的入口方法到不了 sink”，不排除更深的调用链或反射路径；v0.1 的可达深度上限为 4。
4. **MobSF 的 code_analysis 对这三份 APK 均为空**：与 ReachScope 的 “0 桥” 相互印证；但不代表 MobSF 永不报桥，规则集和版本会影响结果。
