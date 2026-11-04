"""Original public-guidance summaries; not executable or proprietary detections.

Signals refer only to existing saved Web response checks. An empty signal list
means manual guidance, not a missing implementation that a model may invent.
The catalogue performs no I/O and exposes defensive copies to callers.
"""

from __future__ import annotations

import copy
from typing import Any

_OWASP = "https://cheatsheetseries.owasp.org/cheatsheets/"


def _owasp(title: str, page: str) -> dict[str, str]:
    return {"title": title, "url": _OWASP + page + "_Cheat_Sheet.html", "kind": "owasp_guidance"}


def _vendor(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url, "kind": "vendor_public_overview"}


_HEADERS = _owasp("OWASP HTTP Headers Cheat Sheet", "HTTP_Headers")
_TLS = _owasp("OWASP Transport Layer Security Cheat Sheet", "Transport_Layer_Security")
_CSP = _owasp("OWASP Content Security Policy Cheat Sheet", "Content_Security_Policy")
_SESSION = _owasp("OWASP Session Management Cheat Sheet", "Session_Management")
_FRAMING = _owasp("OWASP Clickjacking Defense Cheat Sheet", "Clickjacking_Defense")
_CSRF = _owasp("OWASP CSRF Prevention Cheat Sheet", "Cross-Site_Request_Forgery_Prevention")
_INPUT = _owasp("OWASP Input Validation Cheat Sheet", "Input_Validation")
_AUTHORIZATION = _owasp("OWASP Authorization Cheat Sheet", "Authorization")
_LOGGING = _owasp("OWASP Logging Cheat Sheet", "Logging")
_DEPENDENCIES = _owasp("OWASP Vulnerable Dependency Management Cheat Sheet", "Vulnerable_Dependency_Management")
_WEB_PROTECTION = _vendor(
    "Kaspersky: About Web Threat Protection (public KES 11 overview)",
    "https://support.kaspersky.com/KESWin/11/en-US/128016.htm",
)
_EXPLOIT_PREVENTION = _vendor(
    "Kaspersky: Exploit Prevention (public KES 11.5 overview)",
    "https://support.kaspersky.com/keswin/11.5.0/en-US/151109.htm",
)
_ANOMALY_CONTROL = _vendor(
    "Kaspersky: Adaptive Anomaly Control (public KES 11.4 overview)",
    "https://support.kaspersky.com/KESWin/11.4.0/en-US/173855.htm",
)

_CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "id": "web.tls", "title": "HTTPS 与证书维护", "category": "transport", "applicability": "web_config",
        "signals": ["hsts", "tls_expiry"],
        "red_review": ["在授权范围内核对敏感页面的传输边界、证书信息和 HTTP 到 HTTPS 的处理。"],
        "blue_actions": ["评审反向代理和应用的 HTTPS 配置、证书主机名及续期责任人。",
                         "确认 HTTPS 稳定后分阶段评审 HSTS 策略及子域影响，保留回滚方案。"],
        "verification": ["保存同一 URL 的新检查记录，复核相关 HSTS 和证书元数据及采集限制。",
                         "由维护者用受控客户端检查实际证书链、续期部署和跳转，记录人工结果。"],
        "limitations": ["现有信号只是保存响应和证书到期元数据，不是完整 TLS 协议或密码套件审计。",
                        "HSTS 缺失或静态证书时间比较不直接证明漏洞或真实部署状态。"],
        "references": [_TLS, _HEADERS],
    },
    {
        "id": "web.csp", "title": "内容安全策略评审", "category": "browser_policy", "applicability": "web_config",
        "signals": ["csp"],
        "red_review": ["在授权页面清单内人工核对脚本、资源来源与业务需要之间的差距。"],
        "blue_actions": ["梳理必要资源来源，评审 default-src、script-src、object-src 和 base-uri。",
                         "先用受控报告和业务回归评估影响，再收紧策略；需要时评审 nonce/hash 方案。"],
        "verification": ["对同一 HTML URL 保存新响应，确认强制策略与报告模式的区别。",
                         "在维护者管理的浏览器环境回归关键页面，审阅策略报告并记录例外依据。"],
        "limitations": ["仅检查策略文本的有限条件，不运行脚本、不验证绕过路径，也不证明不存在 XSS。"],
        "references": [_CSP],
    },
    {
        "id": "web.frame", "title": "页面嵌入边界", "category": "browser_policy", "applicability": "web_config",
        "signals": ["frame_protection"],
        "red_review": ["依据授权业务页面清单，确认哪些页面确实需要被其他站点嵌入。"],
        "blue_actions": ["评审 CSP frame-ancestors 的允许范围及兼容性要求。",
                         "核对 X-Frame-Options 与 CSP 是否一致，并为必要嵌入保留明确业务说明。"],
        "verification": ["保存同一页面的新响应，核对生效响应头及部署层是否覆盖策略。",
                         "由维护者在受控浏览器回归允许和不允许的嵌入场景。"],
        "limitations": ["响应头观察不代替实际浏览器行为验证，也不自动确认点击劫持风险。"],
        "references": [_FRAMING, _HEADERS],
    },
    {
        "id": "web.cookies", "title": "会话 Cookie 属性", "category": "session", "applicability": "web_config",
        "signals": ["cookie_secure", "cookie_http_only", "cookie_same_site"],
        "red_review": ["在授权会话设计评审中区分认证 Cookie 与普通偏好数据，核对跨站业务需要。"],
        "blue_actions": ["对认证相关 Cookie 评审 Secure、HttpOnly、SameSite 及最小 Domain/Path 范围。",
                         "核对登录、续期、注销和跨站跳转的预期行为，不因属性补齐而省略服务端会话控制。"],
        "verification": ["由维护者采集实际设置目标 Cookie 的响应，结合新保存记录复核属性。",
                         "在受控测试账号中回归会话生命周期；记录属性例外，不在笔记中保存 Cookie 值。"],
        "limitations": ["现有检查保存属性而非 Cookie 值；未收到 Cookie 不证明会话安全或没有会话。",
                        "属性检查不验证会话固定、注销失效、CSRF 防护或整个认证流程。"],
        "references": [_SESSION, _CSRF],
    },
    {
        "id": "web.cors", "title": "跨来源读取配置", "category": "cross_origin", "applicability": "web_config",
        "signals": ["cors"],
        "red_review": ["经授权核对哪些来源需要读取哪些接口，区分匿名响应与凭据式业务。"],
        "blue_actions": ["维护明确的可信来源清单，按业务核对来源判断、凭据许可和缓存变化维度。",
                         "评审代理与应用的 CORS 配置一致性，避免用 CORS 代替身份验证和对象授权。"],
        "verification": ["检查同一 URL 的保存许可头，并由维护者在受控客户端回归合法来源流程。",
                         "人工记录响应敏感性及服务端授权依据，不从静态许可头推定数据泄露。"],
        "limitations": ["现有检查不改变 Origin、不发送凭据，也不验证跨来源读取是否实际成功。",
                        "通配符与凭据许可冲突可能被浏览器拒绝，缺少 CORS 头本身不是缺陷。"],
        "references": [_HEADERS, _CSRF],
    },
    {
        "id": "web.mixed_content", "title": "HTTPS 页面资源传输", "category": "content", "applicability": "web_config",
        "signals": ["mixed_content"],
        "red_review": ["在授权页面清单内核对已保存的脚本、样式及图片来源与部署预期。"],
        "blue_actions": ["迁移必要资源到受维护的 HTTPS 地址，核对模板和资源构建配置。",
                         "评审第三方资源依赖与所有者，避免在修订时引入额外未审批来源。"],
        "verification": ["保存同一页面的新完整响应，核对静态资源引用与页面截断标记。",
                         "由维护者在受控浏览器检查实际加载和关键页面功能，补充运行时人工结果。"],
        "limitations": ["只解析已捕获的静态 HTML，不下载子资源、不执行 JavaScript，可能看不到运行时资源。"],
        "references": [_TLS, _CSP],
    },
    {
        "id": "web.forms", "title": "敏感表单提交边界", "category": "forms", "applicability": "web_config",
        "signals": ["password_forms"],
        "red_review": ["在明确授权的业务流程中人工核对敏感表单的预期接收方及认证上下文。"],
        "blue_actions": ["评审密码表单的 HTTPS 提交目标、提交方式和允许的接收来源。",
                         "单独评审服务端 CSRF、认证及验证机制，确保敏感数据不进入 URL 或日志。"],
        "verification": ["保存目标页面的新完整响应，核对表单清单、提交目标和采集完整性。",
                         "由维护者在受控测试账号下回归合法提交并审阅服务端校验记录。"],
        "limitations": ["工具不填写或提交表单，不验证密码处理、CSRF、业务授权或登录成功。"],
        "references": [_TLS, _CSRF, _INPUT],
    },
    {
        "id": "web.mime", "title": "响应类型与嗅探边界", "category": "browser_policy", "applicability": "web_config",
        "signals": ["nosniff"],
        "red_review": ["在授权资源清单内核对应用声明的响应类型是否符合实际业务内容。"],
        "blue_actions": ["配置准确的 Content-Type，并评审 X-Content-Type-Options: nosniff。",
                         "核对上传文件和静态资源的响应策略，使用维护者批准的隔离交付方案。"],
        "verification": ["保存同一资源的新响应，核对类型声明与 nosniff 值。",
                         "由维护者回归合法下载和资源加载，不将头部存在视为内容处理全面安全。"],
        "limitations": ["现有信号不分析上传存储权限、文件内容真实性或浏览器全部 MIME 行为。"],
        "references": [_HEADERS],
    },
    {
        "id": "web.referrer", "title": "来源信息传递策略", "category": "privacy", "applicability": "web_config",
        "signals": ["referrer_policy"],
        "red_review": ["在授权数据流评审中确认路径或查询参数是否含不应传给外部站点的业务信息。"],
        "blue_actions": ["按业务评审 Referrer-Policy，优先减少跨来源暴露的路径和查询信息。",
                         "避免将令牌和敏感数据放入 URL，并记录必要的兼容性例外。"],
        "verification": ["保存同一 HTML 页的新响应并核对策略值。",
                         "由维护者用受控浏览器观察合法跳转中的实际来源信息，避免记录秘密值。"],
        "limitations": ["静态响应头不能证明 URL 不含敏感数据，也不覆盖浏览器扩展或所有跳转上下文。"],
        "references": [_HEADERS, _LOGGING],
    },
    {
        "id": "app.input_validation", "title": "服务端输入与输出评审", "category": "application", "applicability": "manual_review",
        "signals": [],
        "red_review": ["仅在授权设计或代码评审中梳理输入信任边界、数据类型与错误路径。"],
        "blue_actions": ["为服务端输入定义允许的类型、长度、格式、范围及业务约束，并限制解析预算。",
                         "核对参数化数据访问和输出上下文编码；前端校验不能替代服务端校验。"],
        "verification": ["由维护者审阅实现与正常/非法边界的单元和集成测试，记录受审版本。",
                         "确认日志和错误响应不会回显秘密或未经转义的数据。"],
        "limitations": ["当前 Web 采集没有输入校验检测能力；这项是人工任务，不由响应头推断结论。",
                        "输入校验不能替代对象授权、参数化访问或上下文输出编码。"],
        "references": [_INPUT, _LOGGING],
    },
    {
        "id": "app.access_control", "title": "身份与对象授权评审", "category": "application", "applicability": "manual_review",
        "signals": [],
        "red_review": ["仅在批准的角色和业务清单内人工核对资源所有者、租户与操作权限边界。"],
        "blue_actions": ["维护角色/对象/操作权限矩阵，服务端默认拒绝并在每次访问执行对象级授权。",
                         "评审敏感管理操作、租户隔离和失败响应；把授权逻辑纳入回归测试。"],
        "verification": ["由维护者在受控测试账号和数据中审阅权限矩阵与允许/拒绝路径测试结果。",
                         "记录批准角色、数据范围、版本及评审者，不自动创建或切换真实账号。"],
        "limitations": ["当前工具不登录、不遍历对象、不验证越权；此项没有自动观测信号。",
                        "工作台红/蓝视角和自由文本负责人不提供身份验证或权限隔离。"],
        "references": [_AUTHORIZATION],
    },
    {
        "id": "ops.logging", "title": "安全事件记录与处置", "category": "operations", "applicability": "manual_review",
        "signals": [],
        "red_review": ["在授权设计评审中核对关键业务事件能否被发现、关联并交给明确负责人。"],
        "blue_actions": ["定义认证/授权失败、敏感变更和异常事件的结构、关联标识、保留与访问策略。",
                         "排除令牌、密码和完整敏感请求体，处理日志注入风险并安排告警分流责任。"],
        "verification": ["由维护者在受控环境产生批准的测试事件，检查记录完整性、告警和响应流程。",
                         "记录误报复核、例外原因和到期复审日期，不把日志空白解释为没有异常。"],
        "limitations": ["工作台不接入站点或终端实时日志、不学习行为基线，也不执行告警阻断。",
                        "公开异常控制资料只启发先观测再人工复核的流程，不表示复刻供应商规则。"],
        "references": [_LOGGING, _ANOMALY_CONTROL],
    },
    {
        "id": "ops.patching", "title": "依赖更新与修订证据", "category": "operations", "applicability": "manual_review",
        "signals": [],
        "red_review": ["在批准的资产和版本清单内人工核对依赖所有者、维护状态与变更影响。"],
        "blue_actions": ["维护依赖/版本清单，使用项目批准的漏洞情报来源评审适用性和修订优先级。",
                         "为更新建立验证、回滚、发布和延期例外记录，避免只升级版本却不验证实际部署。"],
        "verification": ["由维护者保存受审依赖清单、更新审阅和业务回归结果，核对最终部署版本。",
                         "如有对应配置规则，再用新保存检查辅助复核；版本变化本身不是案例自动关闭依据。"],
        "limitations": ["当前工具不提供完整 SCA、CVE 匹配、补丁部署或部署状态证明。",
                        "公开 Exploit Prevention 概述是纵深防护参考，不代表站点已安装此类保护。"],
        "references": [_DEPENDENCIES, _EXPLOIT_PREVENTION],
    },
    {
        "id": "endpoint.hygiene", "title": "访问终端的纵深防护", "category": "endpoint", "applicability": "endpoint_hygiene",
        "signals": [],
        "red_review": ["仅在批准的终端治理评审中确认浏览器、应用和终端安全策略的负责人与适用范围。"],
        "blue_actions": ["由终端管理员评审受支持的浏览器/应用更新、网页威胁防护和漏洞利用防护策略。",
                         "先在受控群组观察兼容性和事件，再按组织流程复核阻断、例外及其到期日期。"],
        "verification": ["由授权终端管理员在其正式管理工具中检查策略和事件，提交人工评审摘要即可。",
                         "确认终端控制与网站配置分别验收，不从网站响应推断终端防护状态。"],
        "limitations": ["仅为公开概念层面的人工清单；不读取、导出或复制电脑上的专有规则和策略库。",
                        "工作台不是杀毒软件、EDR 或 WAF；不检测进程行为、不部署策略、不声称有厂商检测能力。"],
        "references": [_WEB_PROTECTION, _EXPLOIT_PREVENTION, _ANOMALY_CONTROL],
    },
)


def catalog() -> list[dict[str, Any]]:
    """Return stable, attributed guidance as an independent JSON-compatible copy."""
    return copy.deepcopy(list(_CONTROLS))


_NGINX_HEADERS = {
    "title": "NGINX ngx_http_headers_module", "url": "https://nginx.org/en/docs/http/ngx_http_headers_module.html",
    "kind": "vendor_documentation",
}
_NGINX_COOKIES = {
    "title": "NGINX proxy_cookie_flags", "url": "https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cookie_flags",
    "kind": "vendor_documentation",
}
_NGINX_TEMPLATES: dict[str, dict[str, Any]] = {
    "web.mime": {
        "title": "响应 MIME 嗅探保护（人工审核片段）", "content": 'add_header X-Content-Type-Options "nosniff" always;',
        "conditions": ["先确认应用和静态文件发送正确的 Content-Type，并回归脚本、样式与下载。"],
        "references": [_NGINX_HEADERS, _HEADERS],
    },
    "web.referrer": {
        "title": "来源信息最小化（人工审核片段）", "content": 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
        "conditions": ["先确认受支持浏览器、合法跳转及外部合作流程不依赖完整跨站路径。"],
        "references": [_NGINX_HEADERS, _HEADERS],
    },
    "web.frame": {
        "title": "仅同源嵌入（业务适用后人工合并）", "content": 'add_header Content-Security-Policy "frame-ancestors \'self\'" always;',
        "conditions": ["仅适用于业务确认无需跨源嵌入的页面；有合法外部嵌入时先制定批准来源清单。",
                       "必须合并现有 CSP；不要覆盖既有脚本、资源或更严格的嵌入限制，也不要重复发送冲突策略。"],
        "references": [_NGINX_HEADERS, _FRAMING],
    },
    "web.csp": {
        "title": "先观察的 CSP 评审起点（不是强制策略）",
        "content": 'add_header Content-Security-Policy-Report-Only "default-src \'self\'; object-src \'none\'; base-uri \'self\'" always;',
        "conditions": ["这是受控预发布环境的评审起点，业务资源清单完成后再由维护者设计最终策略。",
                       "报告模式不会阻止违规资源；此片段未配置报告接收端，不会自动收集报告。",
                       "已有强制 CSP 必须保留；从报告模式转为强制模式需要单独审批和完整业务回归。"],
        "references": [_NGINX_HEADERS, _CSP],
    },
    "web.cookies": {
        "title": "已确认代理会话 Cookie 的属性评审（需替换名称）",
        "content": "proxy_cookie_flags CHANGE_ME_SESSION_COOKIE secure httponly samesite=lax;",
        "conditions": ["仅适用于 NGINX 反向代理的上游 Cookie；需要 NGINX 1.19.3+，由维护者确认实际版本。",
                       "替换为已确认的认证 Cookie 名称，不填 Cookie 值；仅在完整 HTTPS 部署下考虑 secure。",
                       "先验证跨站登录和回调确实兼容 SameSite=Lax；应用自行读取的 Cookie 不能盲目加 HttpOnly。",
                       "优先在拥有会话语义的应用层配置；核对现有 proxy_cookie_flags 顺序与重复 Set-Cookie。"],
        "references": [_NGINX_COOKIES, _SESSION],
    },
}


def implementation_guide(identifier: str, environment: str = "generic") -> dict[str, Any]:
    """Return original reviewed guidance, never inferred deployment or commands.

    The API binds this pure guide to a saved report's selected known evidence.
    A requested NGINX template is an operator choice, not stack detection.
    """
    control = next((row for row in _CONTROLS if row["id"] == identifier), None)
    if control is None or environment not in {"generic", "nginx"}:
        raise ValueError("unsupported control or manual environment")
    templates: list[dict[str, Any]] = []
    if environment == "nginx" and identifier in _NGINX_TEMPLATES:
        template = copy.deepcopy(_NGINX_TEMPLATES[identifier])
        templates.append({**template, "language": "nginx", "context": "由维护者选择既有 http/server/location 的正确层级；不是完整配置文件。",
                          "limitations": ["先人工确认部署使用 NGINX；工具没有检测其版本、配置文件或管理权限。",
                                          "add_header 默认仅在当前层未配置 add_header 时继承父层；检查 location、错误页和所有已有头部。",
                                          "always 扩展状态码覆盖，不替代代理/应用一致性检查；片段不能直接当作完整安全配置部署。"
                                          ] if identifier != "web.cookies" else ["该片段仅用于代理上游 Cookie，不配置应用会话、认证或 CSRF 防护。"]})
    rollback = ["变更前记录原配置版本、业务检查清单与恢复负责人；使用部署环境自己的配置校验和受控发布流程。",
                "如关键业务出现回归，由维护者恢复已备份版本并重新验证；工作台不会连接服务器、部署配置或执行命令。"]
    if identifier == "web.tls":
        rollback.append("若评审涉及 HSTS，浏览器缓存策略可能在撤除响应头后继续生效；必须独立评估持续时间和子域影响，不能把恢复文件视为即时回滚。")
    return {
        "control_id": identifier, "title": control["title"], "applicability": control["applicability"], "guide_version": "2026-11-01",
        "environment": environment, "observed_stack": None, "requires_environment_confirmation": environment == "nginx",
        "preconditions": ["确认资产、URL、变更窗口、负责人和授权范围，先在维护者控制的预发布环境演练。",
                          "保留受审版本及原始配置备份，确认代理、CDN 与应用各自负责的响应层；不要从响应头缺失推断部署技术栈。"],
        "red_review": list(control["red_review"]), "blue_steps": list(control["blue_actions"]),
        "verification": list(control["verification"]),
        "rollback": rollback,
        "acceptance": ["对同一已授权资产保存更新的完整检查，区分通过、缺失、跳过、未知及采集失败；保留关联证据。",
                       "由维护者记录真实业务回归与人工验证；头部出现或模型建议并不证明漏洞修复，案例关闭仍需既有复测规则。"],
        "templates": templates, "references": copy.deepcopy(control["references"]),
        "limitations": list(control["limitations"]) + ["这是服务端审核过的人工指南；不含模型生成的自由命令，不自动执行、部署或关闭案例。"],
    }
