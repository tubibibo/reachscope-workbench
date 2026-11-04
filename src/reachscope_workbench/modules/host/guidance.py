"""Original manual hardening guidance; no command or deployment execution."""

from __future__ import annotations

from typing import Any

_SSH = "https://man.openbsd.org/sshd_config"
_RULES: dict[str, tuple[list[str], str]] = {
    "host.ssh.root_login": (["核对管理员账号、sudo 授权与应急通道；评审关闭直接 root 登录或限制到批准的密钥/命令场景。", "先验证替代管理员会话可用，再通过正常配置变更流程调整，避免远程管理锁死。"], _SSH),
    "host.ssh.password_auth": (["核对当前密钥、MFA 与账户恢复能力，再评审是否关闭口令认证；确有业务需要时记录例外和补偿控制。", "PasswordAuthentication 不涵盖键盘交互/PAM 的全部认证路径，需结合 AuthenticationMethods、Match 和实际连接上下文验证。"], _SSH),
    "host.ssh.empty_passwords": (["核对空口令账户与认证流程，保持 PermitEmptyPasswords 明确关闭；同时复核 PAM 和账户本身的限制。"], _SSH),
    "host.ssh.max_auth_tries": (["依据管理业务评审每次连接的认证尝试次数；本工具采用 ≤4 次作为本地建议阈值，非 OpenSSH 官方强制值或合规认证。", "保留密钥认证与应急通道，回归合法客户端；该参数不限制跨连接的总尝试次数。"], _SSH),
    "host.nginx.autoindex": (["复核每个相关 server/location 的目录浏览业务需求；关闭无业务依据的 autoindex，并为必要下载目录记录例外。", "目录列表是否实际出现还取决于索引文件、路由与权限，需在维护者管理的环境验证。"], "https://nginx.org/en/docs/http/ngx_http_autoindex_module.html"),
    "host.nginx.server_tokens": (["评审在相关 HTTP 上下文关闭版本令牌输出，结合代理层和错误页核对暴露范围。", "隐藏版本号仅减少信息暴露，仍需维护实际软件更新和漏洞修复。"], "https://nginx.org/en/docs/http/ngx_http_core_module.html#server_tokens"),
    "host.nginx.tls_protocols": (["梳理受支持客户端，再评审仅保留业务所需 TLSv1.2/TLSv1.3；旧协议兼容例外应明确记录。", "核对默认虚拟主机、SSL 库和部署版本，回归证书与握手；静态协议列表不是实际 TLS 扫描。"], "https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_protocols"),
}


def baseline_guidance(rule_id: str) -> dict[str, Any]:
    steps, reference = _RULES[rule_id]
    return {"prerequisites": ["确认配置资料对应的实际主机、采集上下文、服务版本与变更权限；本工具未连接主机或证明配置已加载。", "SSH 导出必须标明并保持同一连接上下文；未声明上下文时只展示配置事实，不支持据此判定整改完成。上下文声明也未经本工具验证。", "先保存原配置、有效管理通道和业务回归计划，未知项先补齐资料。"],
            "red_review": ["在批准范围内核对本项声明对应的入口与生效条件；手工确认业务例外，不将配置观察升级为已利用漏洞。"],
            "blue_steps": list(steps),
            "verification": ["重新导出同一主机、同一连接/虚拟主机范围的配置，保留相同检查项并比较新证据。", "由维护者在受控环境验证实际服务与合法业务；未知、缺失或跳过不能作为整改完成。"],
            "rollback": ["若业务或管理访问异常，使用预先保留的管理通道恢复批准的原配置；回归后重新记录配置和验证依据。"],
            "limitations": ["指南仅供人工评审，不执行命令、重载服务或自动关闭案例。", "操作员提供的静态配置不能证明运行时生效、网络可达或完整账户授权。"],
            "references": [{"title": "官方指令参考", "url": reference}]}
