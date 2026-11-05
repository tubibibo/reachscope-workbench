# missing-headers：安全响应头缺失

## 1. 你将看到什么

两个剖面返回**同一个页面**（状态码都是 200，内容逐字节相同），差异全部在响应头：

| 响应头 | baseline（有问题） | hardened（修复后） |
|---|---|---|
| Content-Type | text/html; charset=utf-8 | text/html; charset=utf-8 |
| X-Content-Type-Options | （缺失） | nosniff |
| X-Frame-Options | （缺失） | DENY |
| Referrer-Policy | （缺失） | no-referrer |
| Content-Security-Policy | （缺失） | default-src 'none' |

要点：**baseline 不是"配置错了"，而是"什么都没配"**。安全响应头不设置就没有——它们是"默认缺失"的，这与很多开发者的直觉相反。

## 2. 操作步骤

1. 打开 ReachScope，进入实验室页面，选择场景包 `missing-headers`，剖面保持 `baseline`。
2. 启动实验室，得到形如 `http://127.0.0.1:<随机端口>/` 的地址（只监听本机回环，只支持 `GET /`）。
3. 用浏览器打开该地址（或在应用里执行一次采集），在证据面板/开发者工具的网络面板里查看**响应头**，对照上表逐行记录。
4. 回到实验室页面，把剖面切换为 `hardened`（切换会以新一代次重启；若界面显示的地址发生变化，以新地址为准）。
5. 对**同一条 URL** 再访问/采集一次，记录响应头。
6. 并排对比两次结果：页面内容与状态码不变，变化的只有那四个响应头。

## 3. 为什么

- **X-Content-Type-Options: nosniff**——浏览器历史上会"嗅探"响应体猜真实类型（比如把用户上传的文本当 HTML/脚本渲染）。nosniff 关掉这条猜的路，强制按 Content-Type 处理。缺了它，一个只差 Content-Type 的响应就可能被浏览器升级成可执行内容。
- **X-Frame-Options: DENY**——禁止任何页面把本页嵌进 iframe，是点击劫持（clickjacking）最直接的防线。缺了它，任何站点都能嵌套你的页面。
- **Referrer-Policy: no-referrer**——默认情况下，从你的页面跳出去会带 Referer，把完整 URL（可能含令牌、内网路径）交给第三方。no-referrer 表示"离开时什么都不说"。
- **Content-Security-Policy: default-src 'none'**——默认禁止加载一切资源，是 CSP 最收紧的起点；真实站点要按需逐步放开（脚本、样式、图片各自白名单）。

这四个头共同说明一件事：HTTP 响应的安全默认值需要**显式声明**，服务器不声明，浏览器就按最宽松的方式处理。

## 4. 常见误区

- **加了头不等于修好了后端逻辑。** 响应头是纵深防御的一层，替代不了权限校验、输入处理与会话管理。
- **缺头不等于必然被利用。** 它是"少了一层防护"，是否可利用取决于页面实际承载的内容；教学页故意把这个差异放大到可见。
- **CSP 不是越严越好抄。** `default-src 'none'` 对这个无资源的固定页面刚好合适；直接抄到真实站点上会先把站点自己弄坏，需要按站点资源逐步放开。
- **头名大小写、拼写写错等于没写。** 浏览器只认标准名字，`X-Frame-Option`（少了 s）不会报错，只会安静地失效。
