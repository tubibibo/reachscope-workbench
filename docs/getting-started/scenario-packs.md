# 场景包作者指南（Scenario Pack Author Guide）

> **状态：0.15.0 起可用。** 本文描述的场景包（scenario pack）机制随 0.15.0 发布；
> 如与实现不一致，以实现为准并在文档中修正。
>
> 读者画像：会写 YAML，不会写 Python。全程不需要编程、不需要联网。

## 1. 一句话说明

一个场景包就是一个目录：里面放一个 `scenario.yaml` 和若干静态页面。把它放进场景根目录、
重启应用，就多出一课——**不改任何 `.py` 文件，不重新编译前端**。

这是 0.15.0 的第一条目标（G1，原文）：

> **G1 零代码扩展**：新增一个教学场景＝新增一个目录（YAML + 静态资源），不改任何 `.py`，不重编译前端。

场景包**只描述数据，不能执行代码**（G2）：不能发起出网请求、不能读写包外路径。
它描述的是"同一个页面在两种配置下的固定响应差异"，不是一个漏洞靶场。

## 2. 包结构

```
scenarios/
  missing-headers/           # 一个目录 = 一个场景包；目录名建议与 id 一致
    scenario.yaml            # 必须。包的全部机器可读内容
    pages/                   # 静态响应体（纯文件，不执行）
      index.html
    walkthrough.md           # 可选。面向学生的步骤说明；加载器不校验它
  cookie-flags/
  csrf-token/
  ...
```

| 文件/目录 | 是否必须 | 说明 |
|---|---|---|
| `scenario.yaml` | 必须 | 包的唯一入口。没有它的子目录会被发现器**直接忽略**（不算错误） |
| `pages/` 下的页面 | 每条路由必须 | 静态响应体。只允许 `.html` / `.txt` / `.css` 三类后缀 |
| `walkthrough.md` | 可选 | 给人看的说明文件。加载器不校验、不读取它的内容，但它**计入包体积** |
| 其他文件 | 允许 | 不被校验，但同样**计入包体积**（见 §5 数值上限） |

### 发现规则（加载器怎么找到你的包）

以下是加载器发现（`discover()`）的行为，逐条照录：

1. 加载器接受一个根目录列表——内置包目录 + 可选 `--scenarios-dir <path>`（0.15.0 计划中）。
   根不存在或不是目录 → 一条 `SCENARIO_ROOT_MISSING`，继续处理下一个根。
2. 只扫根的**直接子目录**，按名字排序；以 `.` 或 `_` 开头的目录跳过；符号链接目录拒绝
   （记 `SCENARIO_PATH_ESCAPE`）。
3. 子目录含 `scenario.yaml` 才算一个包；不含则忽略（不是错误）。
4. 包内所有非符号链接常规文件的体积之和超过 2 MiB → `SCENARIO_TOO_LARGE`，跳过该包。
5. 用户包与已有包 **id 相同则拒绝加载**（保留先出现者），内置包不能被覆盖。
6. 单个包的任何错误只影响该包：坏包在界面上标记为不可用并给出原因，其他包照常加载，
   服务不会崩。
7. `--scenarios-dir` 下的改动**需重启应用才生效**（0.15.0 不做热重载）。

## 3. 最小可运行示例

目录布局：

```
my-first-pack/
  scenario.yaml
  pages/
    index.html
```

`scenario.yaml`（可整段复制）：

```yaml
pack_format: 1
id: my-first-pack
title:
  en: My first scenario pack
  zh: 我的第一个场景包
summary:
  en: One page served twice, with and without one security header.
  zh: 同一个页面服务两次，一次带某个安全响应头，一次不带。
difficulty: intro
profiles:
  baseline:
    headers:
      Content-Type: "text/html; charset=utf-8"
    cookies: []
    routes:
      "/":
        body: pages/index.html
        status: 200
  hardened:
    headers:
      Content-Type: "text/html; charset=utf-8"
      X-Content-Type-Options: nosniff
    cookies: []
    routes:
      "/":
        body: pages/index.html
        status: 200
expectations:
  - {field: headers.x-content-type-options, baseline: null, hardened: nosniff}
limits:
  - 只演示固定响应的配置差异，不包含可利用漏洞。
  - 页面不加载任何外部资源。
```

`pages/index.html`（可整段复制）：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>本地教学页面</title>
</head>
<body>
  <p>这是本地教学页面（场景包示例），不是真实网站。</p>
  <p>本页不引用任何外部资源，也不包含脚本。</p>
</body>
</html>
```

页面要求（与内置包的写作规范一致）：

- 完整的 HTML5 文档，带 `<meta charset="utf-8">`，文件用 UTF-8 编码
- **不引用任何外部资源**：无 http(s) 链接、无 CDN、无字体、无图片文件
- **不含 `<script>`**（内联 CSS 可以有）
- 页面顶部有一行说明：这是本地教学页面，不是真实网站

把 `my-first-pack/` 放进场景根目录，重启应用后生效（无热重载）。

## 4. 字段参考：8 个顶层字段

顶层字段**有且只有**以下 8 个。未知字段的规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.2，2026-11-05）

> **未知字段一律拒绝**（Pydantic `extra="forbid"`），避免包作者以为某字段生效了其实没有

多写一个字段（例如 `method`、`delay`）整个包就会被拒绝，报 `SCENARIO_INVALID`。

### 4.1 顶层字段表

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `pack_format` | 整数 | 必填 | 必须是 `1`。YAML 布尔值 `true`/`false` 即使"看起来是 1/0"也拒绝 | 包格式版本。更高的 `pack_format` 直接拒绝并提示"格式过新"，不做猜测式兼容（`SCENARIO_FORMAT_UNSUPPORTED`） |
| `id` | 字符串 | 必填 | 匹配 `^[a-z0-9][a-z0-9-]{1,40}$`（小写字母或数字开头，可含连字符，总长 2–41 字符） | 包的唯一标识。建议与目录名一致（内置包如此） |
| `title` | 映射 | 必填 | 键只能是 `en` / `zh`，且**必须含 `en`**；`zh` 不强制但建议写 | 标题。中文写在这里 |
| `summary` | 映射 | 必填 | 同 `title` | 一句话说明本课演示什么 |
| `difficulty` | 字符串 | 必填 | 只能是 `intro` / `intermediate` / `advanced` 三者之一 | 难度 |
| `profiles` | 映射 | 必填 | **恰好**两个键：`baseline` 与 `hardened`。缺一个、多一个（如 `paranoid`）都拒绝 | 两个配置剖面，见 4.2 |
| `expectations` | 列表 | 可选（默认 `[]`） | 最多 16 条；文法见 §6 | 学习者应在复测中观察到的变化 |
| `limits` | 字符串列表 | 可选（默认 `[]`） | 内容不做校验 | 纯展示：包自述的边界，**不构成运行时强制** |

关于 `limits` 的规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.2，2026-11-05）

> `limits` 纯展示，运行时强制边界全部在代码里（见 §3.3），包自述不产生任何约束力

### 4.2 每个剖面（`baseline` / `hardened`）的字段

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `headers` | 字符串映射 | 可选（默认空） | 头名必须在 11 个白名单内且不是保留头（见 §5）；值仅 ASCII、≤512 字节、不含 CR/LF |
| `cookies` | 字符串列表 | 可选（默认空） | 最多 4 条；每条是一个 `Set-Cookie` 字符串，文法见 §7 |
| `routes` | 映射 | 必填 | 1–32 条。键是路径，必须以 `/` 开头，不含 `?`、`#`、`..` |

**注意：响应头是剖面级的，不是路由级的。** 同一剖面下所有路由共用 `headers` 里那一组头。
想给单条路由单独设头（例如只让 `/old` 带 `Location`）在当前文法里做不到——要么整包围绕
重定向设计，要么拆成两个包。

### 4.3 每条路由的字段

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `body` | 字符串 | 必填 | 包内相对路径，建议放在 `pages/` 下（内置包与示例都如此）；后缀必须是 `.html` / `.txt` / `.css`；解析后必须仍落在包目录内；文件必须存在 |
| `status` | 整数 | 可选（默认 200） | 200–599 |

关于路径的规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.3，2026-11-05）

> 响应体只能来自包内 `pages/`，路径解析后必须落在包目录内（`Path.resolve().is_relative_to()`），拒绝 `..`、绝对路径、符号链接逃逸

硬性约束是"解析后不得逃出包根"；按 `pages/` 组织是设计约定与示例写法，两种情况都能加载。

建议 `body` 写干净的相对路径（如 `pages/index.html`），不要用 `..`，即使它解析后仍在包内。

### 4.4 数值上限速查表

| 上限 | 值 | 代码内常量名 |
|---|---|---|
| 包内文件总体积 | ≤ 2 MiB | `MAX_PACK_BYTES = 2 * 1024 * 1024` |
| 路由条数 | 1–32 | `MAX_ROUTES = 32` |
| 每个剖面的 cookie 条数 | ≤ 4 | `MAX_COOKIES = 4` |
| expectations 条数 | ≤ 16 | `MAX_EXPECTATIONS = 16` |
| 响应头值长度 | ≤ 512 字节 | `MAX_HEADER_VALUE = 512` |
| cookie 名/值长度 | 各 ≤ 128 字节 | `MAX_COOKIE_PART = 128` |
| `status` 取值范围 | 200–599 | — |
| 页面文件后缀 | `.html` / `.txt` / `.css` | `ALLOWED_BODY_SUFFIXES` |

### 4.5 两个容易踩的语法坑

- **数值就是数值，字符串就是字符串。** 模型校验是严格模式（`strict=True`）：
  > `status: "200"` 这类字符串直接拒绝，不做宽松转换。

  写 `status: 200`，不要写 `status: "200"`。
- **校验失败一次只报第一条错误。** 错误消息取 pydantic 校验的
  第一条错误的 `loc` + `msg`。改掉这一条后可能再冒出下一条，逐条修即可。

## 5. 响应头白名单（11 个名字）

包作者**只能设置以下 11 个响应头（response header）**，大小写不敏感。名单之外的任何头一律
拒绝（`SCENARIO_INVALID`）。

| # | 头名 | 它防什么（一句话） |
|---|---|---|
| 1 | `Content-Type` | 声明响应体的媒体类型（media type）。写对它，浏览器才不必靠"猜"来解释正文；配合 `X-Content-Type-Options: nosniff` 才能真正关掉类型嗅探 |
| 2 | `Cache-Control` | 控制响应能否被缓存。对含敏感内容的响应写 `no-store`，防止副本留在共享缓存或磁盘上 |
| 3 | `Location` | 重定向的目标地址。本白名单把它限制为站内相对路径，从文法上排除开放重定向（open redirect） |
| 4 | `X-Content-Type-Options` | 取值 `nosniff`：禁止浏览器对响应做 MIME 嗅探（MIME sniffing），防止把上传的文本当脚本执行 |
| 5 | `X-Frame-Options` | 控制本页能否被 iframe 嵌入（`DENY` / `SAMEORIGIN`），是防点击劫持（clickjacking）的常用头 |
| 6 | `Referrer-Policy` | 控制跳转到其他站点时 `Referer` 头带出多少本站信息；`no-referrer` 表示完全不发送 |
| 7 | `Content-Security-Policy` | 声明页面允许加载哪些来源的脚本、样式、框架等资源，是最主要的注入缓解手段之一；其中的 `frame-ancestors` 指令也管嵌入 |
| 8 | `Permissions-Policy` | 控制摄像头、定位等浏览器强权限特性允许给谁用，防止嵌入内容滥用这些特性 |
| 9 | `Cross-Origin-Opener-Policy` | 隔离跨源窗口关系（`window.opener`），缓解 tab-nabbing 与跨源窗口干扰 |
| 10 | `Cross-Origin-Resource-Policy` | 声明本资源拒绝被其他源的页面嵌入或读取，防止敏感资源被跨站引用 |
| 11 | `Strict-Transport-Security` | HSTS：告诉浏览器一段时间内只用 HTTPS 访问本站。**注意**：本实验室是纯 HTTP 回环，浏览器不会对 HTTP 响应生效 HSTS，此头在这里只作配置演示 |

### 5.1 运行时保留头（作者设置即拒绝）

规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.3，2026-11-05）

> **运行时保留头（作者设置即拒绝）**：`content-length`、`connection`，以及任何以
> `x-reachscope-lab-` 开头的名字。

即 `Content-Length`、`Connection`、`X-ReachScope-Lab-*` 三类。原因原文：

> 这些由服务端计算或属于协议头，允许作者设置只会制造"以为生效了其实被覆盖"的错觉

### 5.2 头值约束

| 约束 | 值 | 原因 |
|---|---|---|
| 字符集 | 仅 ASCII | `http.server.send_header` 内部按 **latin-1 strict** 编码，非 latin-1 字符会让接入后的响应直接抛 `UnicodeEncodeError` |
| 长度 | ≤ 512 字节 | `MAX_HEADER_VALUE = 512` |
| 禁止字符 | 不许含 `\r` / `\n` | 防响应头注入（header injection） |
| `Location` 的值 | 只允许以单个 `/` 开头的站内相对路径；不含反斜杠与控制字符 | `/\host` 和 `/<TAB>/host`（`<TAB>` 即制表符）在浏览器 URL 解析里会被当成 `//host`（站外跳转），因此一并拒绝；同时排除开放重定向 |

中文只能写在 `title` / `summary` / `limits` 里，**不能**出现在任何头值里。

### 5.3 想用的头不在名单里怎么办

规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.3，2026-11-05）

> 名单外的头一律拒绝。**扩展白名单 = 一次代码变更**，场景包做不到——这个成本要写在使用说明里

也就是说：给白名单加一个头需要改 Python 代码、走完整的发布流程，不是写包能解决的。
这是刻意的成本设计，不是疏忽。

## 6. `expectations` 文法

`expectations` 声明"学习者应在复测中观察到的变化"。它是一个极小的
文法，0.15.0 **只允许三种断言**，原文照录：

> **`expectations` 是极小的文法，0.15.0 只允许三种断言**：`status`（数值相等）、
> `headers.<name>`（值相等）、`headers.<name>` 取 `null`（表示该头缺失）。
> **不做 body / CSS / DOM 选择器**——那会让场景包变成第二套断言规则系统

| 断言 | 写法 | 值的类型 |
|---|---|---|
| 状态码相等 | `field: status` | 两侧都必须是整数 |
| 头存在且值相等 | `field: headers.<小写头名>` | 两侧都必须是字符串 |
| 头缺失 | `field: headers.<小写头名>`，对应侧写 `null` | `null` |

规则细节：

- 头名只用 11 个白名单名字的小写形式（如 `headers.x-frame-options`）。
- `field` 写成 `body`、CSS 选择器、DOM 选择器都会被拒绝（附录 A 第 21 条）。
- `headers.*` 断言的值只能是字符串或 `null`，写成整数会被拒绝（附录 A 第 26 条）。
  `status` 断言的值只能是整数（附录 A 第 22 条）。
- 最多 16 条。
- 两侧（`baseline` / `hardened`）都建议显式写出；`headers.*` 断言省略的一侧按 `null`
  （缺失）理解，而 `status` 断言两侧必须是整数。

### 6.1 "不存在"必须写 `null`

规则原文：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.2，2026-11-05）

> "缺失"用 YAML `null` 编码，**不许**写不带引号的 `absent`（YAML 会解析成字符串
> `"absent"`，然后被当成真实头值去比较）

正确与错误写法：

```yaml
# 正确：baseline 里没有这个头
- {field: headers.x-frame-options, baseline: null, hardened: DENY}

# 错误：absent 会被当成一个真实的头值 "absent" 去比较
- {field: headers.x-frame-options, baseline: absent, hardened: DENY}
```

### 6.2 expectations 表达不了的东西

- **cookie 属性的变化**：`field` 只允许 `status` 和 `headers.*`，cookie 的差异靠对比两次
  采集的证据观察，不能写成断言。
- **响应体内容**：不做 body 断言（见开头引文，这是刻意的设计边界）。
- `expectations` 是声明式的展示数据：文法**不要求**它与 `profiles` 里的实际取值一致，
  但请保持一致，以免误导学习者。

## 7. `Set-Cookie` 受限文法

cookie 不走"任意头值"的规则，`cookies` 是每个剖面下的独立字段，每条是一个字符串。

### 7.1 允许的写法

```yaml
profiles:
  baseline:
    cookies:
      - "session=demo123; Path=/"
  hardened:
    cookies:
      - "session=demo123; Path=/; HttpOnly; Secure; SameSite=Lax"
```

cookie 文法的规则原文（对应附录 A 第 19 条）：

（出处：《ReachScope Workbench 0.15 架构设计 v2》§3.3，2026-11-05）

> 每条**恰好一个** `name=value` 段（`"Secure"` 这种只有属性没有键值的写法即拒绝），名字与值
> 各 ≤128 字节、字符集 `[A-Za-z0-9._-]`；允许属性 `Secure`、`HttpOnly`、
> `SameSite=Lax|Strict|None`、`Path=/`、`Max-Age=<0..86400>`；其余一律拒绝。

### 7.2 允许与禁止对照表

| 类别 | 内容 | 说明 |
|---|---|---|
| 允许的属性 | `Secure`、`HttpOnly`、`SameSite=Lax|Strict|None`、`Path=/`、`Max-Age=<0..86400>` | `Max-Age` 取 0–86400 的整数（含 0 与 86400） |
| 数量上限 | 每个剖面最多 4 条 | `MAX_COOKIES = 4` |
| 每条结构 | 恰好一个 `name=value` 段开头 | 只有属性没有 `name=value` 的条目拒绝 |
| 名字/值字符集 | `[A-Za-z0-9._-]`，各 ≤ 128 字节 | 中文、空格、其他符号都不行 |
| 禁止 | `Domain` | 见 7.3 |
| 禁止 | `Path` 取 `/` 以外的值 | 只接受 `Path=/` 一种写法 |
| 禁止 | 值中出现 `\r` / `\n` / `;` | `\r`/`\n` 防头注入；`;` 会开出一个新属性段，破坏文法的确定性 |
| 禁止 | 一条里挤多个 `name=value`（如 `a=1; b=2`） | 拆成两条 |
| 禁止 | 白名单之外的任何属性 | — |

注意：`Set-Cookie` **不能**写在 `headers` 里——它不在 11 个白名单头中，写进去会被拒绝。
cookie 只能通过 `cookies` 字段声明。

### 7.3 为什么禁止 `Domain`

允许的属性要么**收紧** cookie 的可用范围（`Secure` 限安全通道、`HttpOnly` 挡脚本读取、
`SameSite` 限跨站携带、`Max-Age` 限生命周期），要么是取值固定的中性写法（`Path=/`）。
`Domain` 是唯一一个**扩大**作用域的属性：`Domain=example.com` 会让 cookie 发给
`example.com` 的所有子域。"把 cookie 作用域放大"是真实世界里一类常见的配置错误，
对教学没有任何增益，所以文法干脆不提供它。

另两条禁令的原因：

- **`Path` 只许 `/`**：本实验室只服务固定路径，只接受一种规范写法，避免同一属性出现多种
  形态造成对比时的歧义。
- **字符集与长度上限**：与头值同理——确定性优先，排除编码歧义与注入面。

## 8. 错误码表

共 6 个错误码。坏包**不会让服务崩溃**：它会被标记为不可用并
给出原因，其他包照常。

| 错误码 | 什么情况触发 | 作者看到后该改哪里 |
|---|---|---|
| `SCENARIO_INVALID` | 包内容不合文法的总入口：YAML 解析失败、顶层不是映射、`pack_format` 缺失/非整数（含布尔值）、未知字段、`id` 不合正则、`title`/`summary` 缺 `en` 或含其他键、`profiles` 键不对、路由条数/键名/status 范围/body 后缀或文件不存在、头名不在白名单或撞保留头、头值非 ASCII/超长/含 CR/LF、`Location` 不是站内相对路径、cookie 文法违规、expectations 文法违规 | 看界面给出的原因（取第一条错误的位置与消息），对照 §4 字段参考逐条修；改完可能再冒出下一条 |
| `SCENARIO_FORMAT_UNSUPPORTED` | `pack_format` 大于 1 | 这个包是为更新版本的格式写的。确认你使用的应用版本；不要盲目把 `pack_format` 改小来"骗过"校验 |
| `SCENARIO_DUPLICATE_ID` | 两个根目录下出现相同 `id` 的包（含用户包与内置包撞 id） | 给你的包换一个 id（并保持与目录名一致）。先出现的包保留，后来者被丢弃 |
| `SCENARIO_PATH_ESCAPE` | 路由的 `body` 解析后逃出包目录（`..`、绝对路径），或包目录本身是符号链接 | 把 `body` 改成包内的相对路径（如 `pages/index.html`）；不要用符号链接组织包目录 |
| `SCENARIO_TOO_LARGE` | 包内所有常规文件体积之和超过 2 MiB | 精简页面、删除包里用不到的文件（所有文件都计入体积，包括 `walkthrough.md`） |
| `SCENARIO_ROOT_MISSING` | 某个场景根目录不存在或不是目录 | 检查 `--scenarios-dir` 指向的路径（0.15.0 计划中的参数）是否拼写正确、目录是否已创建；内置根缺失属于安装问题 |

## 9. 常见错误（错误写法 → 正确写法 → 为什么）

### 9.1 用 `absent` 表示"头不存在"

```yaml
# 错误
- {field: headers.x-frame-options, baseline: absent, hardened: DENY}
# 正确
- {field: headers.x-frame-options, baseline: null, hardened: DENY}
```

为什么：不带引号的 `absent` 是 YAML 字符串，会被当成一个真实的头值 `"absent"` 去比较，
于是断言永远等不到它以为的"缺失"。"缺失"只有一种合法编码：`null`。

### 9.2 头值里写中文

```yaml
# 错误
headers:
  X-Frame-Options: 拒绝
# 正确
headers:
  X-Frame-Options: DENY
```

为什么：头值仅限 ASCII（附录 A 第 16 条）。HTTP 服务端按 latin-1 strict 编码头，
非 ASCII 值会在运行时抛 `UnicodeEncodeError`。中文写在 `title` / `summary` / `limits` 里。

### 9.3 两条 cookie 挤进一条

```yaml
# 错误
cookies:
  - "a=1; b=2"
# 正确
cookies:
  - "a=1"
  - "b=2"
```

为什么：每条 cookie **恰好一个** `name=value` 段（附录 A 第 19 条）。`a=1; b=2` 里的 `b=2`
会被当成属性名，而 `b` 不是允许的属性。

### 9.4 给 cookie 加 `Domain`

```yaml
# 错误
cookies:
  - "sid=abc123; Domain=example.com; Path=/"
# 正确
cookies:
  - "sid=abc123; Path=/"
```

为什么：`Domain` 不在允许属性列表里（见 §7.3）。它是唯一扩大作用域的属性，
教学文法不提供。

### 9.5 `body` 逃出包目录

```yaml
# 错误
routes:
  "/":
    body: ../../shared/index.html
# 正确
routes:
  "/":
    body: pages/index.html
```

为什么：`body` 是包内相对路径，解析后必须仍落在包目录内，逃出包根即报
`SCENARIO_PATH_ESCAPE`（附录 A 第 10 条）。包必须自包含，不能引用包外文件。

### 9.6 用 `.js` 文件当页面

```yaml
# 错误
routes:
  "/":
    body: pages/app.js
# 正确
routes:
  "/":
    body: pages/index.html
```

为什么：页面只允许 `.html` / `.txt` / `.css` 三类后缀（`ALLOWED_BODY_SUFFIXES`，
附录 A 第 9 条）。原文：**不提供 `.js` 文件**（场景包不承载可执行资源；页面内联脚本仍由浏览器
执行，这是本地作者自己的内容，不构成安全边界）。

### 9.7 给 header 设 `Content-Length`

```yaml
# 错误
headers:
  Content-Length: "1024"
# 正确
# （删掉这一行，让服务端自己算）
```

为什么：`Content-Length`、`Connection`、`X-ReachScope-Lab-*` 是运行时保留头，作者设置即
拒绝（附录 A 第 15 条）。它们由服务端计算，允许作者设置只会制造"以为生效了其实被覆盖"的
错觉。

### 9.8 `profiles` 只写一个

```yaml
# 错误
profiles:
  hardened:
    ...
# 正确
profiles:
  baseline:
    ...
  hardened:
    ...
```

为什么：`profiles` 必须**恰好**有 `baseline` 和 `hardened` 两个键，缺一个、多一个都拒绝
（附录 A 第 6 条）。场景包教的就是两个剖面的**差异**，只有一个剖面就没有可对比的东西。

### 9.9 `status` 写成字符串

```yaml
# 错误
routes:
  "/":
    body: pages/index.html
    status: "200"
# 正确
routes:
  "/":
    body: pages/index.html
    status: 200
```

为什么：模型是严格模式，`status: "200"` 这类字符串直接拒绝，不做宽松转换
（规则原文，出处：《ReachScope Workbench 0.15 架构设计 v2》§3.2，2026-11-05）。同理 `pack_format: true` 也会被拒绝——布尔值不是整数。

### 9.10 顶层发明新字段

```yaml
# 错误
pack_format: 1
id: my-pack
method: GET        # ← 不存在这个字段
routes: ...
# 正确
# 删掉 method。HTTP 方法不是包的字段：当前实验室只支持 GET
```

为什么：未知字段一律拒绝（`extra="forbid"`，附录 A 第 4 条）。加 `method`、`queries`、
`delay` 这类字段等于发明新 schema，会被整个包拒绝。表达力不够时，宁可场景简单一点，
也不要发明字段。

## 10. 常用片段

三个常用写法的片段（都需要补全成完整包才能使用）。

### 10.1 文本页面（`.txt` / `.css`）

```yaml
routes:
  "/notes":
    body: pages/notes.txt
    status: 200
```

`pages/notes.txt` 按后缀属于 `text/plain` 类型。如果你同时在 `headers` 里显式设置了
`Content-Type`，请让它与页面后缀一致，不要依赖未指定的优先级。

### 10.2 cookie 对比

见 §7.1 的完整示例。要点：baseline 写最松的合法组合，hardened 写收紧后的组合，
让差异集中在你教的那个属性上。

### 10.3 重定向（`Location`）

```yaml
# 片段：还需要 baseline/hardened 两个剖面齐全才是合法的包
profiles:
  baseline:
    headers:
      Content-Type: "text/plain; charset=utf-8"
      Location: /moved          # 只允许以单个 / 开头的站内相对路径
    routes:
      "/old-page":
        body: pages/moved.txt
        status: 301
```

注意：`headers` 是剖面级的，`Location` 会作用于该剖面的**所有**路由。当前文法做不到
"只给某一条路由加重定向头"。

## 11. 边界：这个机制不是什么

以下边界与 `SECURITY.md` 的语气一致，写给包作者，也请转述给学习者：

- **不执行代码。** 场景包只能描述数据：不执行包内任何代码，不动态导入，不 `eval`，
  不能发起出网请求，不能读写包外路径。
- **不出网。** 实验室只绑 `127.0.0.1`、随机端口；场景包加载过程中没有任何网络调用。
  也没有在线场景市场或自动下载——项目明确不做，因为这会破坏"你机器上的东西"
  这个前提。
- **不是漏洞靶场。** 项目明确的原则：不提供可利用漏洞，只提供配置差异。场景包描述的是
  "演示用的固定响应"，不承载检测规则。
- **页面内联脚本不是安全边界。** 页面内联脚本仍由浏览器执行，这是本地作者
  自己的内容，不构成安全边界。所以页面规范要求不写 `<script>`。
- **缺头是观察，不是结论。** 与 `SECURITY.md` 的表述一致：缺失的响应头是观察（observation），
  不是漏洞存在的证明。对比展示的是配置差异，不自动给任何站点下"安全/不安全"的结论。
- **不写访问日志。** 实验室不记录访问日志（现状不变）。
- **确定性是特性。** 同一场景同一剖面连续两次采集，捕获到的证据字段（状态码、白名单内的
  响应头、响应体字节）完全一致。`Date` 头由 HTTP 服务自动生成、逐秒变化，不属于证据
  字段。

## 12. 尚未实现的部分（不要当成已支持）

| 能力 | 状态 |
|---|---|
| 场景包加载机制（本指南描述的全部文法与校验） | **0.15.0 计划中**，尚未发布 |
| `--scenarios-dir` 命令行参数、`GET /api/lab/scenarios`、`POST /api/lab/start` 的 `scenario_id` 参数 | **0.15.0 计划中** |
| 3 个内置场景（安全响应头、Cookie、CSRF） | **0.15.0 计划中** |
| 讲义导出（一次实验 → HTML，含字段对比与截图位） | **0.15.1 计划中** |
| 第 4 个数据场景 + 课堂重置 | **0.15.2 计划中** |
| TLS 配置场景 | **0.16+ 待定**：需要运行时代码（证书与 ssl context），不属于"零代码场景包"，单独立项 |
| `--scenarios-dir` 热重载 | 0.15.0 **不做**；改动需重启生效 |
| body / CSS / DOM 断言 | **明确不做**（会让场景包变成第二套断言规则系统） |
| 在线场景市场 / 自动下载 | **明确不做**（会引入出网） |
| 多用户、账号、隔离 | 0.x 不做，1.0 也不做 |

当前已发布的 0.14.2 里能用的只有硬编码的教学实验室：一个固定页面、`baseline` /
`hardened` 两个剖面、四类加固响应头。给实验室加一课仍然等于改 Python 代码——这正是
0.15.0 要解决的问题。

## 附录 A：校验规则 → 错误码对照表（27 条）

| # | 规则 | 错误码 |
|---|---|---|
| 1 | 根目录不存在/不是目录 | `SCENARIO_ROOT_MISSING` |
| 2 | `pack_format` 缺失或非 int；取值不是 `1`（含 `0` 与负数）也报本码 | `SCENARIO_INVALID` |
| 3 | `pack_format` > 1 | `SCENARIO_FORMAT_UNSUPPORTED` |
| 4 | 顶层/嵌套出现未知字段（`extra="forbid"`） | `SCENARIO_INVALID` |
| 5 | `id` 不匹配 `[a-z0-9][a-z0-9-]{1,40}` | `SCENARIO_INVALID` |
| 6 | `profiles` 缺 `baseline` 或 `hardened`，或含其他键 | `SCENARIO_INVALID` |
| 7 | `routes` 为空、>32 条、键不以 `/` 开头、含 `?`/`#`/`..` | `SCENARIO_INVALID` |
| 8 | `status` 不在 200..599 | `SCENARIO_INVALID` |
| 9 | body 后缀不在 `.html/.txt/.css` | `SCENARIO_INVALID` |
| 10 | body 解析后逃出包根 | `SCENARIO_PATH_ESCAPE` |
| 11 | body 文件不存在 | `SCENARIO_INVALID` |
| 12 | 包目录是符号链接 | `SCENARIO_PATH_ESCAPE` |
| 13 | 包内文件总字节 > 2 MiB | `SCENARIO_TOO_LARGE` |
| 14 | header 名不在白名单 | `SCENARIO_INVALID` |
| 15 | header 名是保留头（`content-length`/`connection`/`x-reachscope-lab-*`） | `SCENARIO_INVALID` |
| 16 | header 值含非 ASCII 字符、> 512 字节或含 `\r`/`\n` | `SCENARIO_INVALID` |
| 17 | `Location` 不是以单个 `/` 开头的站内相对路径（含 `//`、反斜杠、控制字符） | `SCENARIO_INVALID` |
| 18 | cookie 条目 > 4 条 | `SCENARIO_INVALID` |
| 19 | cookie 含 `Domain`、`Path` 非 `/`、未知属性、多条 `name=value`、非法字符、片段 > 128 字节 | `SCENARIO_INVALID` |
| 20 | `expectations` > 16 条 | `SCENARIO_INVALID` |
| 21 | `field` 不是 `status` 或 `headers.<白名单名>`（如 body/CSS 选择器） | `SCENARIO_INVALID` |
| 22 | `field == "status"` 但值不是 int | `SCENARIO_INVALID` |
| 23 | 两个根下同 id | `SCENARIO_DUPLICATE_ID`（保留先出现者） |
| 24 | `title`/`summary` 缺 `en` 或含 en/zh 以外的键 | `SCENARIO_INVALID` |
| 25 | YAML 解析失败 / 顶层不是 dict | `SCENARIO_INVALID` |
| 26 | `headers.<name>` 断言的值不是 str 或 null（如写成 int） | `SCENARIO_INVALID` |
| 27 | `pack_format` 是 YAML 布尔值（`true`/`false`） | `SCENARIO_INVALID`（loader 预检用 `type(x) is int`，**不用** `isinstance`——`isinstance(True, int)` 为真） |

表后的两条附注，原文照录：

> **header 值为什么限 ASCII**（第 16 条）：`http.server.send_header` 内部按 **latin-1
> strict** 编码，非 latin-1 字符会让响应在运行时直接抛 `UnicodeEncodeError`。文法在
> 校验层把它限死，成本为零；等接入真实响应才发现在运行时炸，代价高得多。

> **cookie 受限文法**（第 19 条细化）：每条**恰好一个** `name=value` 段（`"Secure"` 这种
> 只有属性没有键值的写法即拒绝），名字与值各 ≤128 字节、字符集 `[A-Za-z0-9._-]`；允许属性
> `Secure`、`HttpOnly`、`SameSite=Lax|Strict|None`、`Path=/`、`Max-Age=<0..86400>`；
> 其余一律拒绝。

## 附录 B：白名单 11 名（小写形式）

```
content-type, cache-control, location,
x-content-type-options, x-frame-options, referrer-policy,
content-security-policy, permissions-policy,
cross-origin-opener-policy, cross-origin-resource-policy,
strict-transport-security
```

关于 `location` 的附注，原文照录：

> `location` 在内是刻意的：重定向教学场景需要它，值的站内相对路径约束由单独的规则把关
> （见 §5.2）。若不放进来，这条规则会被"不在白名单"先一步拦死，成为永不可达的死规则。
