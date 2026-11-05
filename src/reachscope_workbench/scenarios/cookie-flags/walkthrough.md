# cookie-flags：Cookie 安全属性

## 1. 你将看到什么

两个剖面用 `Set-Cookie` 下发**同一个**会话 Cookie（`session=demo123`），页面内容与状态码完全相同，差异在 Cookie 的属性上：

| 响应中的 Set-Cookie | 属性差异 |
|---|---|
| baseline：`session=demo123; Path=/` | 只有作用路径，没有任何安全属性 |
| hardened：`session=demo123; Path=/; HttpOnly; Secure; SameSite=Lax` | 加上了三个安全属性 |

| 属性 | baseline | hardened |
|---|---|---|
| HttpOnly | 无 | 有 |
| Secure | 无 | 有 |
| SameSite | 无 | Lax |
| Path | / | / |

## 2. 操作步骤

1. 打开 ReachScope 实验室页面，选择场景包 `cookie-flags`，剖面保持 `baseline`，启动。
2. 用浏览器打开 `http://127.0.0.1:<随机端口>/`，然后在开发者工具里查看：
   - **网络面板**：找到对 `/` 的响应，看 `Set-Cookie` 响应头的完整内容；
   - **应用/存储面板**：查看本站已存的 Cookie 及其 HttpOnly / Secure / SameSite 列。
3. 记录 baseline 的 Set-Cookie 全文。
4. 回到实验室页面，把剖面切换为 `hardened`（切换以新一代次重启；地址以界面显示为准）。
5. 对同一条 URL 再访问一次，重复第 2 步，记录 hardened 的 Set-Cookie 全文。
6. 对比两条 Set-Cookie：值相同，差别只在属性。

> 说明：Cookie 属性不在场景包 expectations 文法（仅 status 与响应头）覆盖范围内，所以本场景的证据对比要在浏览器开发者工具或采集到的原始响应里完成。

## 3. 为什么

- **HttpOnly**——防"脚本偷 Cookie"。XSS 成功后最值钱的目标常常是会话 Cookie；HttpOnly 让脚本调 `document.cookie` 时看不到它。注意：网络面板里仍能看到 Set-Cookie，HttpOnly 只限制脚本读取，不限制传输。
- **Secure**——防"明文信道泄露"。带 Secure 的 Cookie 只允许在 HTTPS 连接上发送，避免在明文 HTTP 里被窃听。浏览器把 `http://127.0.0.1` 这类回环地址视为可信来源，所以本地实验室的 Secure Cookie 也能被接受——这是本地环境特例，**不代表**生产环境的 HTTP 站点可以用 Secure。
- **SameSite=Lax**——防"借身份发请求"。跨站请求默认不携带 Lax Cookie，直接掐断了 CSRF 攻击最常用的路径（顶层导航仍会带，属于可用性与安全的折中）。
- **Path=/**——只是作用域声明，告诉浏览器这个 Cookie 对哪些路径生效；它**不是**安全边界，不要指望 Path 隔离同站内其他页面。

## 4. 常见误区

- **加了头/属性不等于修好了后端逻辑。** SameSite 降低 CSRF 风险，但状态变更仍应另有令牌校验；HttpOnly 不减少 XSS 本身，只是减少它的收获。
- **Secure 在本地"生效了"是回环特例。** 别把它当成"HTTP 站点也可以配 Secure"的证据；生产环境必须 HTTPS。
- **HttpOnly 的 Cookie 不是"看不见"。** 它在网络面板、服务端日志里照常出现，防的只是页面脚本读取。
- **SameSite=None 不是"更安全"。** 它是**取消**同站限制（必须配合 Secure），与本场景的 Lax 方向相反，写错会把防线整个放开。
- **四个属性各管一段，不能互相替代。** 只配其中一个，剩下那段风险原样存在。
