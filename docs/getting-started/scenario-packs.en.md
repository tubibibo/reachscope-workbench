# Scenario Pack Author Guide

> **Status: available since 0.15.0.** Where this document and the implementation
> disagree, the implementation wins and this document is corrected.
>
> Intended reader: someone who can write YAML and does not write Python.
> No programming and no network access are needed at any point.

## 1. What a scenario pack is, in one sentence

A scenario pack is a directory: one `scenario.yaml` plus a few static pages.
Put the directory into a scenarios root and restart the application — you get
one more lesson, **without changing any `.py` file and without rebuilding the
frontend**.

This is goal G1 of 0.15.0, quoted verbatim:

> **G1 零代码扩展**：新增一个教学场景＝新增一个目录（YAML + 静态资源），不改任何 `.py`，不重编译前端。
> (G1, zero-code extension: adding one teaching scenario = adding one directory
> (YAML + static assets), changing no `.py`, rebuilding no frontend.)

A scenario pack **describes data only and cannot execute code** (G2):
it cannot make outbound network requests and cannot read or write paths outside
the pack. It describes fixed-response configuration differences between two
profiles; it is not a vulnerability range.

## 2. Pack structure

```
scenarios/
  missing-headers/           # one directory = one pack; directory name should match the id
    scenario.yaml            # required; all machine-readable content of the pack
    pages/                   # static response bodies (plain files, never executed)
      index.html
    walkthrough.md           # optional; student-facing steps; not validated by the loader
  cookie-flags/
  csrf-token/
  ...
```

| File / directory | Required | Notes |
|---|---|---|
| `scenario.yaml` | Yes | The only entry point. A subdirectory without it is **ignored** by discovery (not an error) |
| Pages under `pages/` | One per route | Static response bodies. Only `.html` / `.txt` / `.css` suffixes are allowed |
| `walkthrough.md` | Optional | Human-readable notes. The loader does not validate or read its content, but it **counts toward pack size** |
| Other files | Allowed | Not validated, but also **count toward pack size** (see §4.4) |

### Discovery rules (how the loader finds your pack)

The loader's discovery (`discover()`) behaves as follows, item by item:

1. The loader takes a list of root directories — the built-in pack directory plus
   an optional `--scenarios-dir <path>` (planned for 0.15.0). A root that does
   not exist or is not a directory produces one `SCENARIO_ROOT_MISSING` issue;
   discovery continues with the next root.
2. Only **direct subdirectories** of a root are scanned, sorted by name;
   directories starting with `.` or `_` are skipped; symlinked directories are
   rejected (recorded as `SCENARIO_PATH_ESCAPE`).
3. A subdirectory counts as a pack only if it contains `scenario.yaml`;
   otherwise it is ignored (not an error).
4. If the total size of all non-symlink regular files in a pack exceeds 2 MiB →
   `SCENARIO_TOO_LARGE`, and that pack is skipped.
5. A user pack with the **same id** as an already loaded pack is rejected (the
   first one wins); built-in packs cannot be overridden.
6. Any error in one pack affects only that pack: the bad pack is marked
   unavailable in the UI with its reason, other packs load normally, and the
   service does not crash.
7. Changes under `--scenarios-dir` **require an application restart** (0.15.0
   has no hot reload).

## 3. Minimal runnable example

Directory layout:

```
my-first-pack/
  scenario.yaml
  pages/
    index.html
```

`scenario.yaml` (copy as-is):

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

(`limits` strings are shown to learners; the built-in packs write them in
Chinese. Write them in the language your students read.)

`pages/index.html` (copy as-is):

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

Page requirements (same writing rules as the built-in packs):

- A complete HTML5 document with `<meta charset="utf-8">`, saved as UTF-8
- **No external resources at all**: no http(s) links, no CDN, no web fonts,
  no image files
- **No `<script>`** (inline CSS is allowed)
- A line at the top saying this is a local teaching page, not a real website

Put `my-first-pack/` into a scenarios root; it takes effect after an
application restart (no hot reload).

## 4. Field reference: the 8 top-level fields

There are exactly 8 top-level fields. The unknown-field rule, quoted verbatim:

> **未知字段一律拒绝**（Pydantic `extra="forbid"`），避免包作者以为某字段生效了其实没有
> (Unknown fields are always rejected (`extra="forbid"`), so an author never
> believes a field took effect when it did not.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.2, 2026-11-05.)

One extra field (for example `method`, `delay`) makes the whole pack invalid
with `SCENARIO_INVALID`.

### 4.1 Top-level fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `pack_format` | integer | Yes | Must be `1`. YAML booleans `true`/`false` are rejected even though they "look like" 1/0 | Pack format version. A higher `pack_format` is rejected outright with a "format too new" hint; no guessing compatibility (`SCENARIO_FORMAT_UNSUPPORTED`) |
| `id` | string | Yes | Matches `^[a-z0-9][a-z0-9-]{1,40}$` (starts with a lowercase letter or digit, may contain hyphens, total length 2–41) | Unique pack identifier. Should match the directory name (the built-in packs do) |
| `title` | mapping | Yes | Keys only `en` / `zh`, and **must contain `en`**; `zh` is optional but recommended | Title. Write your students' language here |
| `summary` | mapping | Yes | Same as `title` | One-sentence description of the lesson |
| `difficulty` | string | Yes | Exactly one of `intro` / `intermediate` / `advanced` | Difficulty |
| `profiles` | mapping | Yes | **Exactly** two keys: `baseline` and `hardened`. Missing one or adding one (e.g. `paranoid`) is rejected | The two configuration profiles, see 4.2 |
| `expectations` | list | No (default `[]`) | At most 16 entries; grammar in §6 | Changes the learner should observe in the re-test |
| `limits` | list of strings | No (default `[]`) | Content is not validated | Display only: the pack's self-declared boundaries, **no runtime force** |

On `limits`, quoted verbatim:

> `limits` 纯展示，运行时强制边界全部在代码里（见 §3.3），包自述不产生任何约束力
> (`limits` is display only; all runtime-enforced boundaries live in code
> (§3.3); a pack's self-description has no binding force.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.2, 2026-11-05.)

### 4.2 Fields of each profile (`baseline` / `hardened`)

| Field | Type | Required | Constraints |
|---|---|---|---|
| `headers` | string mapping | No (default empty) | Names must be in the 11-name allowlist and must not be reserved headers (see §5); values ASCII only, ≤ 512 bytes, no CR/LF |
| `cookies` | list of strings | No (default empty) | At most 4 entries; each entry is a `Set-Cookie` string, grammar in §7 |
| `routes` | mapping | Yes | 1–32 entries. Keys are paths: must start with `/`, must not contain `?`, `#`, `..` |

**Note: response headers are profile-level, not route-level.** All routes in one
profile share the one set of headers in `headers`. Giving a single route its own
header (for example, only `/old` gets `Location`) is not possible in this
grammar — either design the whole pack around the redirect or split it into two
packs.

### 4.3 Fields of each route

| Field | Type | Required | Constraints |
|---|---|---|---|
| `body` | string | Yes | Relative path inside the pack; put it under `pages/` as the built-in packs and examples do; suffix must be `.html` / `.txt` / `.css`; after resolution it must stay inside the pack directory; the file must exist |
| `status` | integer | No (default 200) | 200–599 |

On paths, quoted verbatim:

> 响应体只能来自包内 `pages/`，路径解析后必须落在包目录内（`Path.resolve().is_relative_to()`），拒绝 `..`、绝对路径、符号链接逃逸
> (Response bodies may only come from `pages/` inside the pack; after path
> resolution the target must be inside the pack directory
> (`Path.resolve().is_relative_to()`); `..`, absolute paths and symlink escapes
> are rejected.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.3, 2026-11-05.)

The hard constraint is "must not escape the pack root after resolution";
organizing files under `pages/` is a design convention and the example style —
both load fine. Write `body` as a relative path inside the pack; put it under
`pages/` as the built-in packs and examples do. Do not use `..`, even when it
still resolves inside the pack.

### 4.4 Numeric limits at a glance

| Limit | Value | Code constant |
|---|---|---|
| Total pack file size | ≤ 2 MiB | `MAX_PACK_BYTES = 2 * 1024 * 1024` |
| Route count | 1–32 | `MAX_ROUTES = 32` |
| Cookies per profile | ≤ 4 | `MAX_COOKIES = 4` |
| Expectation count | ≤ 16 | `MAX_EXPECTATIONS = 16` |
| Header value length | ≤ 512 bytes | `MAX_HEADER_VALUE = 512` |
| Cookie name/value length | ≤ 128 bytes each | `MAX_COOKIE_PART = 128` |
| `status` range | 200–599 | — |
| Page file suffixes | `.html` / `.txt` / `.css` | `ALLOWED_BODY_SUFFIXES` |

### 4.5 Two syntax traps

- **Numbers are numbers, strings are strings.** Model validation is strict
  (`strict=True`):
  > `status: "200"` 这类字符串直接拒绝，不做宽松转换。
  > (Strings like `status: "200"` are rejected outright, no lenient conversion.)

  Write `status: 200`, not `status: "200"`.
- **Validation reports one error at a time.** The message is the
  **first** pydantic error's `loc` + `msg`. Fix that one and the next may appear;
  work through them one by one.

## 5. Response header allowlist (11 names)

A pack author can set only the following 11 response headers, case-insensitive.
Any header outside the list is rejected (`SCENARIO_INVALID`).

| # | Header | What it defends against (one sentence) |
|---|---|---|
| 1 | `Content-Type` | Declares the media type of the body. With it set correctly, the browser does not have to guess; together with `X-Content-Type-Options: nosniff` it actually turns type sniffing off |
| 2 | `Cache-Control` | Controls whether the response may be cached. `no-store` on sensitive responses keeps copies out of shared caches and off disk |
| 3 | `Location` | The redirect target. This allowlist restricts it to site-relative paths, ruling out open redirects by grammar |
| 4 | `X-Content-Type-Options` | Value `nosniff`: forbids the browser from MIME-sniffing the response, preventing uploaded text from being executed as script |
| 5 | `X-Frame-Options` | Controls whether this page can be framed (`DENY` / `SAMEORIGIN`); the common header against clickjacking |
| 6 | `Referrer-Policy` | Controls how much of your site's information the `Referer` header carries to other sites; `no-referrer` sends nothing |
| 7 | `Content-Security-Policy` | Declares which sources of scripts, styles, frames etc. the page may load; one of the main injection mitigations; its `frame-ancestors` directive also governs framing |
| 8 | `Permissions-Policy` | Controls which origins may use powerful browser features (camera, geolocation, …), preventing embedded content from abusing them |
| 9 | `Cross-Origin-Opener-Policy` | Isolates cross-origin window relationships (`window.opener`), mitigating tab-nabbing and cross-origin window interference |
| 10 | `Cross-Origin-Resource-Policy` | Declares that this resource refuses to be embedded or read by pages from other origins, keeping sensitive resources out of cross-site references |
| 11 | `Strict-Transport-Security` | HSTS: tells the browser to use HTTPS only for this site for a period. **Note:** this lab serves plain HTTP on loopback, so browsers will not honor HSTS here; the header is a configuration demonstration only |

### 5.1 Runtime-reserved headers (author-set means rejected)

Quoted verbatim:

> **运行时保留头（作者设置即拒绝）**：`content-length`、`connection`，以及任何以
> `x-reachscope-lab-` 开头的名字。
> (Runtime-reserved headers, rejected when set by the author: `content-length`,
> `connection`, and any name starting with `x-reachscope-lab-`.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.3, 2026-11-05.)

That is: `Content-Length`, `Connection`, `X-ReachScope-Lab-*`. The reason,
quoted verbatim:

> 这些由服务端计算或属于协议头，允许作者设置只会制造"以为生效了其实被覆盖"的错觉
> (These are computed by the server or belong to the protocol; letting an author
> set them only creates the illusion that they took effect when in fact they get
> overridden.)

### 5.2 Header value constraints

| Constraint | Value | Reason |
|---|---|---|
| Character set | ASCII only | `http.server.send_header` encodes headers as **latin-1 strict**; a non-latin-1 value makes the wired-up response raise `UnicodeEncodeError` at runtime |
| Length | ≤ 512 bytes | `MAX_HEADER_VALUE = 512` |
| Forbidden characters | no `\r` / `\n` | Prevents response header injection |
| `Location` value | site-relative paths starting with a single `/` only; no backslashes and no control characters | `/\host` and `/<TAB>/host` (a literal tab) parse as `//host` — an off-site redirect — in browser URL parsing, so both are rejected; this also rules out open redirects |

Chinese text belongs in `title` / `summary` / `limits`, never in a header value.

### 5.3 If the header you need is not on the list

Quoted verbatim:

> 名单外的头一律拒绝。**扩展白名单 = 一次代码变更**，场景包做不到——这个成本要写在使用说明里
> (Headers outside the list are always rejected. **Extending the allowlist is a
> code change**, which a scenario pack cannot do — this cost belongs in the user
> documentation.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.3, 2026-11-05.)

In other words: adding one header to the allowlist means changing Python code and
going through the full release process. That cost is deliberate, not an oversight.

## 6. The `expectations` grammar

`expectations` declares "the changes the learner should observe in the re-test".
It is a deliberately tiny grammar; 0.15.0 allows **exactly three assertion
forms**, quoted verbatim:

> **`expectations` 是极小的文法，0.15.0 只允许三种断言**：`status`（数值相等）、
> `headers.<name>`（值相等）、`headers.<name>` 取 `null`（表示该头缺失）。
> **不做 body / CSS / DOM 选择器**——那会让场景包变成第二套断言规则系统
> (`expectations` is a minimal grammar; 0.15.0 allows only three assertion
> forms: `status` (numeric equality), `headers.<name>` (value equality), and
> `headers.<name>` with `null` (header absent). No body / CSS / DOM selectors —
> that would turn scenario packs into a second assertion-rule system.)

| Assertion | Syntax | Value type |
|---|---|---|
| Status code equality | `field: status` | Both sides must be integers |
| Header present with a value | `field: headers.<lowercase-name>` | Both sides must be strings |
| Header absent | `field: headers.<lowercase-name>` with `null` on that side | `null` |

Details:

- Use the lowercase form of the 11 allowlist names (e.g. `headers.x-frame-options`).
- `field` values like `body`, CSS selectors or DOM selectors are rejected
  (Appendix A, rule 21).
- Values of `headers.*` assertions must be strings or `null`; an integer is
  rejected (Appendix A, rule 26). Values of `status` assertions must be integers
  (Appendix A, rule 22).
- At most 16 entries.
- Write both sides (`baseline` / `hardened`) explicitly. An omitted side of a
  `headers.*` assertion reads as `null` (absent); both sides of a `status`
  assertion must be integers.

### 6.1 "Absent" must be written as `null`

Quoted verbatim:

> "缺失"用 YAML `null` 编码，**不许**写不带引号的 `absent`（YAML 会解析成字符串
> `"absent"`，然后被当成真实头值去比较）
> (Absence is encoded as YAML `null`; do **not** write an unquoted `absent`
> (YAML parses it as the string `"absent"`, which is then compared as a real
> header value).)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.2, 2026-11-05.)

Wrong and right:

```yaml
# Correct: the header does not exist in baseline
- {field: headers.x-frame-options, baseline: null, hardened: DENY}

# Wrong: `absent` is treated as a real header value "absent" to compare against
- {field: headers.x-frame-options, baseline: absent, hardened: DENY}
```

### 6.2 What expectations cannot express

- **Cookie attribute changes**: `field` only allows `status` and `headers.*`;
  cookie differences are observed by comparing the evidence of two collections,
  not written as assertions.
- **Response body content**: no body assertions (see the quoted design rule —
  a deliberate boundary).
- `expectations` is declarative display data: the grammar does **not**
  require it to match the actual values in `profiles`, but keep them consistent
  so learners are not misled.

## 7. The restricted `Set-Cookie` grammar

Cookies do not follow the "any header value" rule; `cookies` is a separate field
per profile, and each entry is one string.

### 7.1 Allowed form

```yaml
profiles:
  baseline:
    cookies:
      - "session=demo123; Path=/"
  hardened:
    cookies:
      - "session=demo123; Path=/; HttpOnly; Secure; SameSite=Lax"
```

The full cookie grammar, quoted verbatim (Appendix A, rule 19):

> 每条**恰好一个** `name=value` 段（`"Secure"` 这种只有属性没有键值的写法即拒绝），名字与值
> 各 ≤128 字节、字符集 `[A-Za-z0-9._-]`；允许属性 `Secure`、`HttpOnly`、
> `SameSite=Lax|Strict|None`、`Path=/`、`Max-Age=<0..86400>`；其余一律拒绝。
> (Each entry has exactly one `name=value` segment (an entry like `"Secure"`
> with attributes but no name=value pair is rejected); name and value are each
> ≤ 128 bytes with charset `[A-Za-z0-9._-]`; allowed attributes are `Secure`,
> `HttpOnly`, `SameSite=Lax|Strict|None`, `Path=/`, `Max-Age=<0..86400>`;
> everything else is rejected.)
> (Source: ReachScope Workbench 0.15 Architecture Design v2, §3.3, 2026-11-05.)

### 7.2 Allowed vs forbidden

| Category | Content | Notes |
|---|---|---|
| Allowed attributes | `Secure`, `HttpOnly`, `SameSite=Lax|Strict|None`, `Path=/`, `Max-Age=<0..86400>` | `Max-Age` takes an integer 0–86400 inclusive |
| Count limit | At most 4 entries per profile | `MAX_COOKIES = 4` |
| Entry structure | Exactly one `name=value` segment first | An entry with attributes but no `name=value` is rejected |
| Name/value charset | `[A-Za-z0-9._-]`, each ≤ 128 bytes | No Chinese, spaces, or other symbols |
| Forbidden | `Domain` | See 7.3 |
| Forbidden | `Path` values other than `/` | Only `Path=/` is accepted |
| Forbidden | `\r` / `\n` / `;` inside the value | `\r`/`\n` prevent header injection; `;` would open a new attribute segment and break the deterministic grammar |
| Forbidden | Several `name=value` pairs in one entry (e.g. `a=1; b=2`) | Split into two entries |
| Forbidden | Any attribute outside the allowed list | — |

Note: `Set-Cookie` **cannot** be written in `headers` — it is not one of the 11
allowlisted headers and would be rejected there. Cookies are declared only
through the `cookies` field.

### 7.3 Why `Domain` is forbidden

Every allowed attribute either **tightens** the cookie's reach (`Secure`
restricts to secure transport, `HttpOnly` blocks script reads, `SameSite`
limits cross-site sending, `Max-Age` bounds lifetime) or is a neutral,
fixed-value form (`Path=/`). `Domain` is the one attribute that **widens**
scope: `Domain=example.com` sends the cookie to every subdomain of
`example.com`. "Widening cookie scope" is a classic real-world configuration
mistake and adds nothing to teaching, so the grammar simply does not offer it.

The other two prohibitions:

- **`Path` only `/`**: the lab serves fixed paths; accepting exactly one
  canonical form avoids ambiguity when comparing profiles.
- **Charset and length limits**: same reasoning as header values —
  determinism first; no encoding ambiguity, no injection surface.

## 8. Error codes

There are 6 error codes. A bad pack
**does not crash the service**: it is marked unavailable with its reason, and
everything else keeps working.

| Error code | When it is triggered | What the author should fix |
|---|---|---|
| `SCENARIO_INVALID` | The general entry point for grammar violations: YAML parse failure, top level not a mapping, `pack_format` missing / non-integer (including booleans), unknown fields, `id` not matching the regex, `title`/`summary` missing `en` or containing other keys, wrong `profiles` keys, route count / key / status range / body suffix / missing body file, header name not in the allowlist or colliding with a reserved header, header value non-ASCII / too long / containing CR/LF, `Location` not site-relative, cookie grammar violations, expectations grammar violations | Read the reason shown in the UI (the first error's location and message), fix against §4, and expect the next error to surface |
| `SCENARIO_FORMAT_UNSUPPORTED` | `pack_format` greater than 1 | The pack was written for a newer format version. Check your application version; do not blindly lower `pack_format` to sneak past validation |
| `SCENARIO_DUPLICATE_ID` | Two roots contain packs with the same `id` (including a user pack colliding with a built-in id) | Pick a new id for your pack (and keep it matching the directory name). The earlier pack wins; the later one is dropped |
| `SCENARIO_PATH_ESCAPE` | A route's `body` resolves outside the pack directory (`..`, absolute path), or the pack directory itself is a symlink | Change `body` to a relative path inside the pack (e.g. `pages/index.html`); do not organize packs with symlinks |
| `SCENARIO_TOO_LARGE` | Total size of all regular files in the pack exceeds 2 MiB | Trim pages and remove unused files (every file counts, including `walkthrough.md`) |
| `SCENARIO_ROOT_MISSING` | A scenarios root does not exist or is not a directory | Check the `--scenarios-dir` path (a parameter planned for 0.15.0) for typos and that the directory exists; a missing built-in root is an installation problem |

## 9. Common mistakes (wrong → right → why)

### 9.1 Using `absent` for a missing header

```yaml
# Wrong
- {field: headers.x-frame-options, baseline: absent, hardened: DENY}
# Right
- {field: headers.x-frame-options, baseline: null, hardened: DENY}
```

Why: an unquoted `absent` is a YAML string and is compared as a real header
value `"absent"`, so the assertion never sees the absence it assumes. Absence
has exactly one legal encoding: `null`.

### 9.2 Chinese text in a header value

```yaml
# Wrong
headers:
  X-Frame-Options: 拒绝
# Right
headers:
  X-Frame-Options: DENY
```

Why: header values are ASCII-only (Appendix A, rule 16). The HTTP server encodes
headers as latin-1 strict; a non-ASCII value raises `UnicodeEncodeError` at
runtime. Chinese text belongs in `title` / `summary` / `limits`.

### 9.3 Two cookies squeezed into one entry

```yaml
# Wrong
cookies:
  - "a=1; b=2"
# Right
cookies:
  - "a=1"
  - "b=2"
```

Why: each cookie entry has **exactly one** `name=value` segment (Appendix A, rule 19).
In `a=1; b=2` the `b=2` is parsed as an attribute, and `b` is not an allowed
attribute.

### 9.4 Adding `Domain` to a cookie

```yaml
# Wrong
cookies:
  - "sid=abc123; Domain=example.com; Path=/"
# Right
cookies:
  - "sid=abc123; Path=/"
```

Why: `Domain` is not in the allowed attribute list (see §7.3). It is the one
scope-widening attribute; the teaching grammar does not offer it.

### 9.5 `body` escaping the pack directory

```yaml
# Wrong
routes:
  "/":
    body: ../../shared/index.html
# Right
routes:
  "/":
    body: pages/index.html
```

Why: `body` is a relative path inside the pack and must stay inside the pack
directory after resolution; escaping the pack root triggers
`SCENARIO_PATH_ESCAPE` (Appendix A, rule 10). A pack must be self-contained.

### 9.6 Using a `.js` file as a page

```yaml
# Wrong
routes:
  "/":
    body: pages/app.js
# Right
routes:
  "/":
    body: pages/index.html
```

Why: pages allow only the suffixes `.html` / `.txt` / `.css`
(`ALLOWED_BODY_SUFFIXES`, Appendix A rule 9). Verbatim: **no `.js` files are provided**
(scenario packs carry no executable resources; inline scripts in pages are still
executed by the browser — that is the local author's own content and not a
security boundary).

### 9.7 Setting `Content-Length` as a header

```yaml
# Wrong
headers:
  Content-Length: "1024"
# Right
# (delete the line; the server computes it)
```

Why: `Content-Length`, `Connection` and `X-ReachScope-Lab-*` are
runtime-reserved headers; setting them as an author is rejected (Appendix A, rule 15).
They are computed by the server; letting an author set them only creates the
illusion that they took effect.

### 9.8 Writing only one profile

```yaml
# Wrong
profiles:
  hardened:
    ...
# Right
profiles:
  baseline:
    ...
  hardened:
    ...
```

Why: `profiles` must have **exactly** the keys `baseline` and `hardened`;
missing one or adding one is rejected (Appendix A, rule 6). A scenario pack teaches
the **difference** between two profiles — with one profile there is nothing to
compare.

### 9.9 `status` written as a string

```yaml
# Wrong
routes:
  "/":
    body: pages/index.html
    status: "200"
# Right
routes:
  "/":
    body: pages/index.html
    status: 200
```

Why: model validation is strict; strings like `status: "200"` are rejected with
no lenient conversion. Likewise `pack_format: true` is rejected — a
boolean is not an integer.

### 9.10 Inventing a new top-level field

```yaml
# Wrong
pack_format: 1
id: my-pack
method: GET        # ← no such field
routes: ...
# Right
# delete `method`. The HTTP method is not a pack field: the lab serves GET only.
```

Why: unknown fields are always rejected (`extra="forbid"`, Appendix A rule 4).
Adding `method`, `queries`, `delay` and the like means inventing a new schema,
and the whole pack is rejected. When the grammar feels too weak, prefer a
simpler scenario over inventing fields.

## 10. Useful fragments

Three fragments for common cases (each must be completed into a full pack).

### 10.1 Text pages (`.txt` / `.css`)

```yaml
routes:
  "/notes":
    body: pages/notes.txt
    status: 200
```

`pages/notes.txt` is a `text/plain` page by suffix. If you also set
`Content-Type` explicitly in `headers`, keep it consistent with the page
suffix; do not rely on unspecified precedence.

### 10.2 Cookie comparison

See the full example in §7.1. The point: baseline carries the loosest legal
form, hardened the tightened form, so the difference concentrates on the
attribute you are teaching.

### 10.3 Redirects (`Location`)

```yaml
# Fragment: a valid pack still needs both baseline and hardened profiles
profiles:
  baseline:
    headers:
      Content-Type: "text/plain; charset=utf-8"
      Location: /moved          # site-relative paths starting with a single / only
    routes:
      "/old-page":
        body: pages/moved.txt
        status: 301
```

Note: `headers` is profile-level, so `Location` applies to **all** routes of
that profile. The current grammar cannot attach a redirect header to a single
route only.

## 11. Boundaries: what this mechanism is not

The following boundaries match the tone of `SECURITY.md`; they are written for
pack authors and should be relayed to learners:

- **No code execution.** A scenario pack describes data only: no code from the
  pack is executed, nothing is dynamically imported, no `eval`. Packs cannot
  make outbound requests and cannot read or write outside the pack.
- **No network access.** The lab binds `127.0.0.1` only, on a random port;
  loading a pack involves no network calls. There is no online scenario
  marketplace and no auto-download — the project explicitly excludes this,
  because it would break the "everything stays on your machine" premise.
- **Not a vulnerability range.** A project principle, verbatim: 不提供可利用漏洞，只提供配置差异
  (no exploitable vulnerabilities are provided, only configuration
  differences). Packs describe fixed demo responses and carry no detection
  rules.
- **Inline page scripts are not a security boundary.** Inline
  scripts in pages are still executed by the browser; that is the local
  author's own content and not a security boundary. Hence the page rule: no
  `<script>`.
- **A missing header is an observation, not a verdict.** Consistent with
  `SECURITY.md`: missing response headers are observations, not proof of a
  vulnerability. The comparison shows a configuration difference; it does not
  automatically label any site secure or insecure.
- **No access logs.** The lab keeps no access logs (unchanged from the current
  behavior).
- **Determinism is a feature.** Collecting the same scenario and profile twice
  yields identical captured evidence fields (status code, allowlisted response
  headers, response body bytes). The `Date` header is generated automatically
  by the HTTP server and changes every second; it is not an evidence field.

## 12. What is not implemented yet (do not treat as available)

| Capability | Status |
|---|---|
| The scenario pack mechanism (all grammar and validation in this guide) | **Planned for 0.15.0**, not released |
| `--scenarios-dir` CLI parameter, `GET /api/lab/scenarios`, the `scenario_id` parameter of `POST /api/lab/start` | **Planned for 0.15.0** |
| 3 built-in scenarios (security headers, cookies, CSRF) | **Planned for 0.15.0** |
| Handout export (one experiment → HTML with field comparison and screenshot slots) | **Planned for 0.15.1** |
| A 4th data scenario + classroom reset | **Planned for 0.15.2** |
| TLS misconfiguration scenario | **0.16+, undecided**: needs runtime code (certificates and ssl context), not a "zero-code scenario pack"; separate project |
| Hot reload for `--scenarios-dir` | **Not** in 0.15.0; changes need a restart |
| body / CSS / DOM assertions | **Explicitly not planned** (would turn packs into a second assertion-rule system) |
| Online scenario marketplace / auto-download | **Explicitly not planned** (it would require outbound network access) |
| Multi-user, accounts, isolation | Not in 0.x, not in 1.0 |

In the currently released 0.14.2, only the hardcoded teaching lab exists: one
fixed page, the `baseline` / `hardened` profiles, and four kinds of hardened
response headers. Adding a lesson still means changing Python code — which is
exactly the problem 0.15.0 sets out to solve.

## Appendix A: Validation rules → error codes (27 rules)

The rule table below is kept in the original Chinese to prevent translation
drift. Field names, error codes and constants are exact; the English prose for
each rule is in §4–§7 above.

| # | Rule | Error code |
|---|---|---|
| 1 | 根目录不存在/不是目录 | `SCENARIO_ROOT_MISSING` |
| 2 | `pack_format` 缺失或非 int | `SCENARIO_INVALID` |
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
| 17 | `Location` 不是以 `/` 开头的站内相对路径 | `SCENARIO_INVALID` |
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

The two notes following the table, quoted verbatim:

> **header 值为什么限 ASCII**（第 16 条）：`http.server.send_header` 内部按 **latin-1
> strict** 编码，非 latin-1 字符会让响应在运行时直接抛 `UnicodeEncodeError`。文法在
> 校验层把它限死，成本为零；等接入真实响应才发现在运行时炸，代价高得多。

> **cookie 受限文法**（第 19 条细化）：每条**恰好一个** `name=value` 段（`"Secure"` 这种
> 只有属性没有键值的写法即拒绝），名字与值各 ≤128 字节、字符集 `[A-Za-z0-9._-]`；允许属性
> `Secure`、`HttpOnly`、`SameSite=Lax|Strict|None`、`Path=/`、`Max-Age=<0..86400>`；
> 其余一律拒绝。

## Appendix B: The 11 allowlist names (lowercase)

```
content-type, cache-control, location,
x-content-type-options, x-frame-options, referrer-policy,
content-security-policy, permissions-policy,
cross-origin-opener-policy, cross-origin-resource-policy,
strict-transport-security
```

Note on `location`, quoted verbatim:

> `location` 在内是刻意的：重定向教学场景需要它，值的站内相对路径约束由单独的规则把关
> （见 §5.2）。若不放进来，这条规则会被"不在白名单"先一步拦死，成为永不可达的死规则。
> (`location` is included deliberately: redirect teaching scenarios need it, and
> the site-relative-path constraint on its value is handled by a dedicated rule
> (§5.2 above). Without it, that rule would be blocked first by "not in the
> allowlist" and become an unreachable dead rule.)
