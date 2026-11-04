"""Passive configuration checks over one bounded response; no requests or exploit tests."""

from __future__ import annotations

import re
import ssl
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

_Status = Literal["pass", "review", "info", "not_applicable"]
_SOURCE_DIRECTIVES = {
    "default-src", "script-src", "script-src-elem", "script-src-attr", "style-src",
    "style-src-elem", "style-src-attr", "img-src", "font-src", "connect-src",
    "media-src", "object-src", "frame-src", "child-src", "worker-src", "manifest-src",
    "base-uri", "form-action", "frame-ancestors",
}
_SOURCE_KEYWORDS = {
    "'self'", "'none'", "'unsafe-inline'", "'unsafe-eval'", "'strict-dynamic'",
    "'unsafe-hashes'", "'report-sample'", "'wasm-unsafe-eval'", "'inline-speculation-rules'",
}
_SCHEME_SOURCE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\Z")
_HOST_SOURCE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:\*|(?:\*\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)"
    r"(?::(?:[0-9]+|\*))?(?:/[^\s;,]*)?\Z"
)
_NONCE_HASH = re.compile(r"'(?:nonce|sha256|sha384|sha512)-[A-Za-z0-9+/_-]+={0,2}'\Z")
_REFERRER_POLICIES = {
    "no-referrer", "no-referrer-when-downgrade", "origin", "origin-when-cross-origin",
    "same-origin", "strict-origin", "strict-origin-when-cross-origin", "unsafe-url",
}
_RULE_HEADERS = {
    "csp": {"content-security-policy"},
    "frame_protection": {"content-security-policy", "x-frame-options"},
    "nosniff": {"x-content-type-options"},
    "referrer_policy": {"referrer-policy"},
    "hsts": {"strict-transport-security"},
    "cors": {"access-control-allow-origin", "access-control-allow-credentials"},
}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _result(
    rule: str, title: str, status: _Status, description: str,
    recommendation: str, evidence: dict[str, Any], severity: str = "info",
) -> dict[str, Any]:
    return {"id": rule, "title": title, "status": status, "severity": severity,
            "description": description, "recommendation": recommendation, "evidence": evidence}


def _headers(record: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in _mapping(record.get("headers")).items():
        if isinstance(key, str) and isinstance(value, str):
            name = key.strip().lower()
            output[name] = output[name] + ", " + value if name in output else value
    return output


def _scheme(url: str) -> str:
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:
        return ""


def _policies(value: str) -> list[dict[str, list[str]]]:
    policies: list[dict[str, list[str]]] = []
    for policy in value.split(","):
        directives: dict[str, list[str]] = {}
        for directive in policy.split(";"):
            parts = directive.split()
            if parts:
                # Browsers use the first occurrence of a duplicate directive.
                directives.setdefault(parts[0].lower(), parts[1:])
        if directives:
            policies.append(directives)
    return policies


def _source_valid(token: str, *, ancestor: bool = False) -> bool:
    if token.lower() in {"'none'", "'self'"}:
        return True
    if not ancestor and (token.lower() in _SOURCE_KEYWORDS or _NONCE_HASH.fullmatch(token)):
        return True
    return bool(_SCHEME_SOURCE.fullmatch(token) or _HOST_SOURCE.fullmatch(token))


def _any_host(token: str) -> bool:
    source = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", token)
    return source.split("/", 1)[0].split(":", 1)[0] == "*"


def _csp(headers: dict[str, str], policies: list[dict[str, list[str]]]) -> dict[str, Any]:
    value = headers.get("content-security-policy", "")
    evidence: dict[str, Any] = {"content_security_policy": value,
                               "report_only_present": bool(headers.get("content-security-policy-report-only"))}
    if not value.strip():
        return _result("csp", "CSP 基础配置", "review", "未观察到非空的实施型 CSP 响应头；报告模式不实施拦截。",
                       "按页面资源需求评估实施 CSP；先用报告模式观察兼容性，再逐步收紧来源。", evidence, "low")
    sources = [(name, tokens) for policy in policies for name, tokens in policy.items() if name in _SOURCE_DIRECTIVES]
    invalid = [name for name, tokens in sources if any(not _source_valid(token, ancestor=name == "frame-ancestors") for token in tokens)]
    effective: list[str] = []
    for name, tokens in sources:
        lowered = {token.lower() for token in tokens}
        script = name == "default-src" or name.startswith("script-src")
        style = name == "default-src" or name.startswith("style-src")
        has_nonce_hash = any(_NONCE_HASH.fullmatch(token) for token in tokens)
        if (script or style) and "'unsafe-inline'" in lowered and not has_nonce_hash:
            effective.append(f"{name}: 'unsafe-inline'")
        if script and ("'unsafe-eval'" in lowered or "'wasm-unsafe-eval'" in lowered):
            effective.append(f"{name}: eval")
        strict_script = name.startswith("script-src") and "'strict-dynamic'" in lowered and has_nonce_hash
        if any(_any_host(token) for token in tokens) and not strict_script:
            effective.append(f"{name}: wildcard host")
        if script and "data:" in lowered and not strict_script:
            effective.append(f"{name}: data:")
    evidence.update({"policy_count": len(policies), "source_directives": [name for name, _ in sources],
                     "syntax_review": invalid, "permissive_tokens": effective})
    if not sources or invalid or effective:
        return _result("csp", "CSP 基础配置", "review",
                       "CSP 含宽松标记、未识别的基础来源语法，或未观察到受支持的来源限制；需结合完整策略复核。",
                       "检查有效来源指令与语法；按需要用 nonce/hash 限制脚本，避免宽泛来源与 eval。多策略交集和指令覆盖需人工确认。",
                       evidence, "low")
    return _result("csp", "CSP 基础配置", "pass", "观察到实施型 CSP 来源指令，基础检查未命中宽松标记；未验证全部 CSP 语义或绕过。",
                   "结合页面功能和浏览器报告持续验证策略。", evidence)


def _framing(headers: dict[str, str], policies: list[dict[str, list[str]]]) -> dict[str, Any]:
    ancestors = [policy["frame-ancestors"] for policy in policies if "frame-ancestors" in policy]
    xfo = headers.get("x-frame-options", "")
    evidence: dict[str, Any] = {"frame_ancestors": ancestors, "x_frame_options": xfo}
    if ancestors:
        restrictive = any(
            tokens and all(_source_valid(token, ancestor=True) for token in tokens)
            and not any(_any_host(token) or _SCHEME_SOURCE.fullmatch(token) for token in tokens)
            for tokens in ancestors
        )
        if restrictive:
            return _result("frame_protection", "HTML 防嵌入配置", "pass", "实施型 CSP 包含限定来源的 frame-ancestors；未验证业务允许来源是否合适。",
                           "确认所有允许嵌入来源均受信任；必要时使用 'none'。", evidence)
        return _result("frame_protection", "HTML 防嵌入配置", "review", "frame-ancestors 来源为空、宽泛或基础语法无法确认；存在该指令时不以 X-Frame-Options 代替判断。",
                       "按业务设置有效且明确的 frame-ancestors 来源。", evidence, "low")
    if xfo.strip().lower() in {"deny", "sameorigin"}:
        return _result("frame_protection", "HTML 防嵌入配置", "pass", "观察到有效的 DENY 或 SAMEORIGIN；该检查仅确认头部配置。",
                       "确认嵌入需求，并考虑使用 CSP frame-ancestors。", evidence)
    return _result("frame_protection", "HTML 防嵌入配置", "review", "未观察到限定来源的 frame-ancestors 或有效 X-Frame-Options；ALLOW-FROM 已废弃。",
                   "根据页面是否需要被嵌入设置 frame-ancestors 'none'/'self' 或明确来源。", evidence, "low")


def _referrer(headers: dict[str, str]) -> dict[str, Any]:
    value = headers.get("referrer-policy", "")
    supported = [token.strip() for token in value.split(",") if token.strip() in _REFERRER_POLICIES]
    evidence: dict[str, Any] = {"referrer_policy": value, "effective_policy": supported[-1] if supported else None}
    if not value.strip():
        return _result("referrer_policy", "Referrer-Policy 配置", "info", "未观察到显式 Referrer-Policy；浏览器默认策略和页面内策略未在此验证。",
                       "按隐私需求考虑显式配置 strict-origin-when-cross-origin 或更严格策略。", evidence)
    if not supported:
        return _result("referrer_policy", "Referrer-Policy 配置", "review", "响应头没有可识别的 Referrer-Policy 值。",
                       "使用受支持的策略值，并检查兼容策略列表。", evidence, "low")
    if supported[-1] in {"unsafe-url", "no-referrer-when-downgrade", "origin", "origin-when-cross-origin"}:
        return _result("referrer_policy", "Referrer-Policy 配置", "review", "有效策略允许跨来源或降级请求携带部分来源信息；是否合适取决于业务。",
                       "核对 URL 中是否含敏感信息，按需使用 strict-origin-when-cross-origin 或更严格策略。", evidence, "low")
    return _result("referrer_policy", "Referrer-Policy 配置", "pass", "观察到限制跨来源或降级来源信息的有效策略。",
                   "仍需避免在 URL 中放置敏感信息。", evidence)


def _hsts(headers: dict[str, str], url: str) -> dict[str, Any]:
    scheme = _scheme(url)
    value = headers.get("strict-transport-security", "")
    evidence: dict[str, Any] = {"strict_transport_security": value, "scheme": scheme}
    if scheme != "https":
        return _result("hsts", "HTTPS HSTS 配置", "not_applicable", "该响应不是 HTTPS；浏览器不会从 HTTP 响应建立 HSTS 策略。",
                       "需要 HTTPS 传输时先部署 HTTPS，再评估 HSTS。", evidence)
    try:
        hostname = urlsplit(url).hostname or ""
        ip_address(hostname)
    except ValueError:
        pass
    else:
        evidence["hostname"] = hostname
        return _result("hsts", "HTTPS HSTS 配置", "not_applicable", "该 HTTPS URL 使用 IP 地址字面量；浏览器不会为 IP 地址建立 HSTS 策略。",
                       "需要 HSTS 时使用具备有效 HTTPS 配置的域名。", evidence)
    ages = []
    for part in value.split(";"):
        name, separator, content = part.strip().partition("=")
        if name.strip().lower() == "max-age":
            seconds = content.strip()
            if len(seconds) >= 2 and seconds.startswith('"') and seconds.endswith('"'):
                seconds = seconds[1:-1]
            ages.append(int(seconds) if separator and re.fullmatch(r"[0-9]+", seconds) else None)
    max_age = ages[0] if len(ages) == 1 else None
    evidence["max_age"] = max_age
    if max_age is None or max_age <= 0:
        return _result("hsts", "HTTPS HSTS 配置", "review", "未观察到唯一、有效且大于零的 HSTS max-age；零会取消浏览器保存的策略。",
                       "验证 HTTPS 部署后配置合适的正整数 max-age；启用子域或 preload 前核对所有相关服务。", evidence, "low")
    return _result("hsts", "HTTPS HSTS 配置", "pass", "HTTPS 响应含有效的正整数 HSTS max-age；未验证首次访问、子域覆盖或 preload。",
                   "按维护能力设置策略时长并持续更新证书。", evidence)


def _cors(headers: dict[str, str]) -> dict[str, Any]:
    origin = headers.get("access-control-allow-origin", "").strip()
    credentials = headers.get("access-control-allow-credentials", "").strip()
    evidence: dict[str, Any] = {"allow_origin": origin, "allow_credentials": credentials,
                               "origin_variation_tested": False}
    if not origin and not credentials:
        return _result("cors", "CORS 响应配置", "info", "未观察到 CORS 许可头；缺少这些头不属于缺陷。",
                       "仅在业务需要跨来源读取时配置 CORS。", evidence)
    if origin == "*" and credentials == "true":
        return _result("cors", "CORS 响应配置", "review", "通配符来源与凭据许可冲突；浏览器会拒绝此配置的凭据式跨来源读取，不能据此认定数据泄露。",
                       "公开响应可移除凭据许可；需凭据时使用经过核对的明确允许来源。", evidence, "low")
    valid_origin = origin == "*"
    try:
        parsed = urlsplit(origin)
        valid_origin = valid_origin or bool(
            parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
            and not any(char.isspace() for char in origin) and parsed.port != 0
        )
    except ValueError:
        valid_origin = False
    if not valid_origin or (credentials and credentials != "true"):
        return _result("cors", "CORS 响应配置", "review", "CORS 来源或凭据许可值需复核（包括 null 来源、空值、多个来源或非标准凭据值）。",
                       "使用单个明确的允许来源或公开通配符；仅在需要时设置大小写精确的 true。", evidence, "low")
    return _result("cors", "CORS 响应配置", "info", "仅记录本次静态 CORS 许可；未改变 Origin、发送凭据或验证响应敏感性。",
                   "确认允许来源与响应公开范围；动态返回来源时检查允许列表及 Vary: Origin。", evidence)


def _cookies(record: dict[str, Any]) -> list[dict[str, Any]]:
    cookies = _rows(record.get("cookies"))
    truncated = record.get("cookies_truncated") is True
    rules = [("cookie_secure", "Cookie Secure 属性"), ("cookie_http_only", "Cookie HttpOnly 属性"),
             ("cookie_same_site", "Cookie SameSite 属性")]
    if not cookies:
        status: _Status = "info" if truncated else "not_applicable"
        return [_result(rule, title, status, "未保留到 Cookie 元数据。" if truncated else "本次响应未观察到设置 Cookie。",
                        "如需评估会话 Cookie，请采集设置该 Cookie 的响应。", {"cookie_count": 0, "truncated": truncated})
                for rule, title in rules]
    # Whitelist metadata even if a caller supplies additional fields such as values.
    metadata = [{key: cookie.get(key) for key in ("name", "domain", "path", "secure", "http_only", "same_site", "partitioned")}
                for cookie in cookies]
    missing_secure = [cookie for cookie in metadata if cookie["secure"] is not True]
    missing_http_only = [cookie for cookie in metadata if cookie["http_only"] is not True]
    invalid_same_site = [cookie for cookie in metadata if _text(cookie["same_site"]).lower() not in {"lax", "strict", "none"}
                         or (_text(cookie["same_site"]).lower() == "none" and cookie["secure"] is not True)]
    results = []
    for (rule, title), affected, advice in zip(rules, (missing_secure, missing_http_only, invalid_same_site), (
        "需要仅经 HTTPS 发送的 Cookie 应设置 Secure，并在 HTTPS 上设置与使用。",
        "对无需脚本读取的会话或敏感 Cookie 设置 HttpOnly；前端必须读取的 Cookie 需单独评估。",
        "按跨站需求设置 Lax/Strict；必须使用 None 时同时设置 Secure。",
    ), strict=True):
        status = "review" if affected else "info" if truncated else "pass"
        description = "部分 Cookie 属性缺失或不满足该规则；未判断 Cookie 是否敏感或验证攻击。" if affected else (
            "已保留 Cookie 均符合该属性检查，但清单被截断，不能覆盖完整响应。" if truncated
            else "本次观察到的 Cookie 均符合该属性规则；不代表会话整体安全。"
        )
        results.append(_result(rule, title, status, description, advice,
                               {"cookie_count": len(cookies), "truncated": truncated, "affected": affected,
                                "cookies": metadata}, "low" if affected else "info"))
    return results


def _page_checks(page: dict[str, Any], url: str) -> list[dict[str, Any]]:
    truncated = page.get("truncated") is True
    password_forms = []
    affected_forms = []
    for index, form in enumerate(_rows(page.get("forms"))):
        fields = form.get("password_fields", 0)
        if not ((isinstance(fields, int) and not isinstance(fields, bool) and fields > 0)
                or (isinstance(fields, list) and fields)):
            continue
        method = _text(form.get("method")).strip().lower()
        method = method if method in {"get", "post", "dialog"} else "get"
        action = _text(form.get("action"))
        try:
            destination = urljoin(url, action)
        except ValueError:
            destination = action
        row = {"index": index, "action": destination, "method": method,
               "password_fields": fields if isinstance(fields, int) else len(fields)}
        password_forms.append(row)
        if method != "dialog" and (method == "get" or _scheme(destination) == "http"):
            affected_forms.append(row)
    form_status: _Status = "review" if affected_forms else "info" if truncated else "pass" if password_forms else "not_applicable"
    forms = _result("password_forms", "密码表单提交配置", form_status,
                    "观察到密码表单使用 GET 或 HTTP 目标；实际提交、脚本覆盖与敏感数据传输未验证。" if affected_forms
                    else "已保留表单中未观察到 GET/HTTP 密码提交；表单清单可能受采集范围限制。",
                    "密码表单使用 HTTPS 与 POST，并检查脚本和按钮对 method/action 的覆盖。",
                    {"password_form_count": len(password_forms), "affected": affected_forms, "truncated": truncated},
                    "medium" if affected_forms else "info")
    resources = [{"kind": kind, "url": _text(row.get("url"))}
                 for kind in ("scripts", "stylesheets", "images") for row in _rows(page.get(kind))
                 if _scheme(_text(row.get("url"))) == "http"]
    scheme = _scheme(url)
    mixed_status: _Status = "not_applicable" if scheme != "https" else "review" if resources else "info" if truncated else "pass"
    mixed = _result("mixed_content", "HTTPS 页面混合资源", mixed_status,
                    "HTTPS 页面引用 HTTP 子资源；浏览器可能阻止或升级请求，未加载资源验证。" if scheme == "https" and resources
                    else "该响应不是 HTTPS 页面。" if scheme != "https"
                    else "已保留 HTML 中未观察到 HTTP 脚本、样式或图片引用；未执行脚本或加载后续资源。",
                    "将 HTTP 子资源改为 HTTPS，并检查运行时加载行为。",
                    {"scheme": scheme, "resources": resources if scheme == "https" else [], "truncated": truncated},
                    "medium" if mixed_status == "review" else "info")
    return [forms, mixed]


def _tls(record: dict[str, Any]) -> dict[str, Any]:
    tls = _mapping(record.get("tls"))
    evidence: dict[str, Any] = {"not_after": _text(tls.get("not_after")), "warning_days": 30}
    if not tls:
        return _result("tls_expiry", "TLS 证书有效期", "not_applicable", "本次响应没有可用 TLS 证书元数据。",
                       "需要 HTTPS 证书评估时采集 HTTPS 响应。", evidence)
    now = datetime.now(UTC)
    evidence["evaluated_at"] = now.isoformat()
    try:
        expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(evidence["not_after"]), UTC)
    except (ValueError, OverflowError, OSError):
        return _result("tls_expiry", "TLS 证书有效期", "info", "TLS 元数据未含可解析的 not_after，无法判断证书有效期。",
                       "检查采集器证书元数据；这不等于证书失效。", evidence)
    remaining = (expiry - now).total_seconds()
    evidence.update({"expires_at": expiry.isoformat(), "remaining_days": round(remaining / 86400, 2)})
    if remaining <= 0:
        return _result("tls_expiry", "TLS 证书有效期", "review", "元数据中的证书有效期已结束；这是时间比较结果，未重新握手验证当前部署。",
                       "核对证书和系统时间并更新部署证书。", evidence, "medium")
    if remaining <= 30 * 86400:
        return _result("tls_expiry", "TLS 证书有效期", "review", "元数据中的证书将在 30 天内到期。",
                       "确认自动续期和部署更新能够在到期前完成。", evidence, "low")
    return _result("tls_expiry", "TLS 证书有效期", "pass", "元数据中的证书到期时间超过 30 天；此规则仅检查 not_after。",
                   "持续监控续期；证书链和主机名验证由连接采集器负责。", evidence)


def audit_response(record: dict[str, Any], *, groups: set[str] | None = None) -> list[dict[str, Any]]:
    """Return independent rule outcomes without network I/O or input mutation.

    ``pass`` applies only to the named rule and captured metadata. Certificate
    expiry is evaluated at the current UTC time, recorded in that rule's evidence.
    """
    selected = groups if groups is not None else {"headers", "page"}
    if not selected:
        return []
    if record.get("reachable") is not True:
        return [_result("response_unavailable", "响应配置不可评估", "info", "没有取得可评估的响应，无法检查页面或响应头配置。",
                        "先解决采集错误后重新观察该 URL。", {"reachable": False})]
    headers = _headers(record)
    page = _mapping(record.get("page"))
    url = _text(record.get("final_url")) or _text(record.get("url"))
    results: list[dict[str, Any]] = []
    if "headers" in selected:
        policies = _policies(headers.get("content-security-policy", ""))
        # Response-header rules do not require a successfully decoded page. A
        # compressed/opaque HTML body must not disable checks that headers-only
        # mode can assess. Older manually constructed records may omit MIME data.
        content_type = _text(record.get("content_type"))
        html = "html" in content_type.lower() if content_type else page.get("analyzed") is True
        if html:
            results.extend([_csp(headers, policies), _framing(headers, policies), _referrer(headers)])
        else:
            results.extend(_result(rule, title, "not_applicable", "本次响应未识别为 HTML，不对其应用 HTML 页面响应头规则。",
                                   "如需评估 HTML，请采集 HTML 响应。", {"html_response": False})
                           for rule, title in [("csp", "CSP 基础配置"), ("frame_protection", "HTML 防嵌入配置"),
                                               ("referrer_policy", "Referrer-Policy 配置")])
        nosniff = headers.get("x-content-type-options", "")
        valid_nosniff = nosniff.strip().lower() == "nosniff"
        results.append(_result("nosniff", "MIME 类型嗅探配置", "pass" if valid_nosniff else "review",
                           "观察到有效的 nosniff 响应头。" if valid_nosniff else "未观察到有效的 X-Content-Type-Options: nosniff；未验证 MIME 混淆或执行。",
                           "返回正确的 Content-Type，并按需要配置 X-Content-Type-Options: nosniff。",
                           {"x_content_type_options": nosniff, "content_type": _text(record.get("content_type"))},
                           "info" if valid_nosniff else "low"))
        results.extend([_hsts(headers, url), _cors(headers), *_cookies(record), _tls(record)])
    if "page" in selected and page.get("analyzed") is True:
        results.extend(_page_checks(page, url))
    elif "page" in selected:
        results.extend(_result(rule, title, "not_applicable", "未取得已解析的 HTML 页面清单。",
                               "采集 HTML 页面后可复核该项。", {"html_analyzed": False})
                       for rule, title in [("password_forms", "密码表单提交配置"), ("mixed_content", "HTTPS 页面混合资源")])
    truncated_headers = record.get("headers_truncated")
    if isinstance(truncated_headers, list):
        truncated = {name.strip().lower() for name in truncated_headers if isinstance(name, str)}
        for result in results:
            affected = sorted(_RULE_HEADERS.get(result["id"], set()) & truncated)
            if affected and result["status"] != "not_applicable":
                if result["status"] == "pass":
                    result["status"] = "info"
                    result["description"] = "相关响应头被截断；仅保留前缀，无法确认完整值是否满足本规则。"
                result["evidence"]["capture_note"] = "相关响应头只保留了截断前缀；需取得完整值后复核。"
                result["evidence"]["truncated_headers"] = affected
    return results
