"""内置样例资产（纯虚构，供 --demo 使用）。

合规要求：
- 域名只用 RFC 2606 保留域 example.com / example.org / example.net
- IP 只用 RFC 5737 文档保留段 203.0.113.0/24（TEST-NET-3）与 198.51.100.0/24
- 不含任何真实资产、真实凭据

这些数据的第二个用途：作为分类引擎的 golden dataset ——
预期类别写在 `expect` 字段里，可被 --eval 用来算准确率。
"""

from __future__ import annotations

from .models import Asset

DEMO_TARGET = "example.com"

# (host, ip, port, title, server, expect_category, expect_tech)
_DEMO_ROWS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    # ---- 认证面（P1）----
    ("login.example.com", "203.0.113.10", "443", "统一身份认证平台", "nginx", "auth", "login_portal"),
    ("sso.example.com", "203.0.113.11", "443", "单点登录系统", "openresty", "auth", "login_portal"),
    ("passport.example.com", "203.0.113.12", "443", "用户通行证", "nginx", "auth", "login_portal"),
    ("oauth.example.com", "198.51.100.20", "443", "开放授权中心", "nginx", "auth", "oauth"),
    # ---- 管理后台 / 中间件控制台（P1）----
    ("admin.example.com", "203.0.113.13", "8443", "运营管理后台", "nginx", "admin", "admin_panel"),
    ("jenkins.example.com", "203.0.113.14", "8080", "Dashboard [Jenkins]", "Jetty", "admin", "jenkins"),
    ("manager.example.com", "203.0.113.15", "8080", "Tomcat Manager Application", "Apache Tomcat", "admin", "tomcat_manager"),
    ("console.example.com", "203.0.113.16", "7001", "WebLogic Server Console", "WebLogic", "admin", "weblogic_console"),
    ("dbadmin.example.com", "203.0.113.17", "443", "phpMyAdmin", "nginx", "admin", "phpmyadmin"),
    # ---- API 文档 / 调试接口（P2）----
    ("api.example.com", "203.0.113.18", "443", "Swagger UI", "nginx", "api_doc", "swagger"),
    ("actuator.example.com", "203.0.113.19", "8080", "Spring Boot Actuator", "", "api_doc", "spring_actuator"),
    ("graphql.example.com", "203.0.113.20", "443", "GraphiQL Playground", "nginx", "api_doc", "graphql"),
    # ---- 文件上传 / 对象存储（P2）----
    ("upload.example.com", "203.0.113.21", "443", "文件上传中心", "nginx", "upload", "upload"),
    ("oss.example.com", "203.0.113.22", "443", "Object Storage Bucket", "AliyunOSS", "object_storage", "object_storage"),
    # ---- 组件暴露（P3）----
    ("redis.example.com", "203.0.113.23", "6379", "", "Redis", "exposed_service", "redis"),
    ("mysql.example.com", "203.0.113.24", "3306", "", "MySQL", "exposed_service", "mysql"),
    ("es.example.com", "203.0.113.25", "9200", "Elasticsearch", "", "exposed_service", "elasticsearch"),
    ("docker.example.com", "203.0.113.26", "2375", "Docker Daemon", "", "exposed_service", "docker_api"),
    # ---- 泄露（P3）----
    ("files.example.com", "203.0.113.27", "80", "Index of /backup", "Apache", "scm_leak", "dir_listing"),
    ("git.example.com", "203.0.113.28", "80", "Index of /.git", "nginx", "scm_leak", "git_exposed"),
    ("phpinfo.example.com", "203.0.113.29", "80", "phpinfo()", "Apache", "scm_leak", "phpinfo"),
    ("config.example.com", "203.0.113.30", "80", "配置文件 .env", "nginx", "scm_leak", "env_exposed"),
    # ---- 常规 Web / 未识别 ----
    ("www.example.com", "203.0.113.31", "443", "Example 企业官网", "nginx", "web", "nginx"),
    ("shop.example.com", "203.0.113.32", "443", "Example 商城", "Microsoft-IIS/10.0", "web", "iis"),
    ("legacy.example.com", "198.51.100.31", "9999", "", "", "unknown", ""),
)


def demo_rows() -> tuple[tuple[str, str, str, str, str, str, str], ...]:
    """返回原始样例行（含预期分类，供评估用）。"""
    return _DEMO_ROWS


def demo_assets() -> list[Asset]:
    """返回样例资产列表（不含预期字段）。"""
    return [
        Asset(host=host, ip=ip, port=port, title=title, server=server)
        for host, ip, port, title, server, _, _ in _DEMO_ROWS
    ]


def website_demo_assets() -> list[Asset]:
    """Synthetic HTTP websites only; retain the original mixed golden dataset.

    Generic databases, exposed service APIs and unknown transports belong to the
    legacy classifier evaluation, not the website input walkthrough.
    """
    return [
        Asset(host=host, ip=ip, port=port, title=title, server=server,
              protocol="https" if port in {"443", "8443"} else "http")
        for host, ip, port, title, server, category, _ in _DEMO_ROWS
        if category not in {"exposed_service", "unknown"}
    ]
