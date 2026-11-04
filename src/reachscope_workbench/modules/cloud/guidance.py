"""Evidence-bound cloud implementation guides, with no execution or AI dependency.

Original explanations based on the linked AWS documentation. These guides add no
rules, state evaluation, permissions, target requests or remediation side effects.
"""

from __future__ import annotations

import copy
from typing import Any

_NETWORK = "https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html"
_IAM = "https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html"
_ANALYZER = "https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html"
_S3_BLOCK = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html"
_S3_ENCRYPTION = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-encryption.html"


def _reference(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url}


_GUIDES: dict[str, dict[str, Any]] = {
    "network.public_sensitive_ports": {
        "prerequisites": ["确认配置对应的账号、区域、VPC、安全组及关联实例；本报告的资源地址不替代云端资源身份核对。", "记录当前管理出口地址、必要业务端口和恢复通道；先确保受控堡垒机或已配置的 Session Manager 可用，避免远程管理锁死。"],
        "red_review": ["从证据标记的入站规则索引核对任意 IPv4/IPv6 来源、协议和敏感端口；仅有允许规则不证明公网可达。", "在授权环境人工核对公网地址、路由、网络 ACL、实例全部安全组及主机监听，记录尚未取得的证据；本工具不扫描端口或尝试登录。"],
        "blue_steps": ["将管理/数据库端口的来源缩到业务明确需要的 CIDR 或受信安全组；同时检查 IPv4 与 IPv6，不用一个协议栈的收紧代替另一个。", "先建立并验证替代管理通道，再分批调整规则；保留确需公开的 HTTPS 等业务入口，避免删除所有入站规则。"],
        "verification": ["导出同一安全组的完整修订配置，关联到原案例后选择 network 复测；确认未知规则索引为空且同资源同规则不再命中。", "另由获授权人员在真实环境验证必要业务和管理入口；会话、已有连接及其他安全组允许规则需单独考虑，本报告不提供部署验证。"],
        "rollback": ["变更前保存规则版本和有效管理通道；若合法业务受影响，通过原管理变更流程恢复已批准的特定规则，而非直接开放全部来源。"],
        "limitations": ["规则只覆盖所列敏感 TCP 端口条件；安全组规则可叠加，未评估完整网络可达性或主机安全。"],
        "references": [_reference("AWS 安全组规则", _NETWORK), _reference("AWS Session Manager", "https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html")],
    },
    "iam.broad_allow": {
        "prerequisites": ["确认策略实际附加的身份/资源、业务所有者及所需动作；Terraform 地址和一份策略文件不能描述全部授权来源。", "准备正常业务回归和经批准的应急访问方式，保留原策略版本；Condition 的值在本工具证据中已省略，须由授权人员在原配置核对。"],
        "red_review": ["按证据中的语句索引复核宽泛 Allow 的 Action 与 Resource，区分条件化授权和无条件授权，不把通配符直接等同于可提权。", "补充显式 Deny、资源策略、权限边界、会话策略、组织 SCP/RCP 和适用条件，判断哪些仍未覆盖；本模块不是有效权限求值器。"],
        "blue_steps": ["依据实际业务调用与资源清单，将通配动作/资源收敛为所需范围；部分动作不支持资源级授权时应查对应服务授权参考，不能机械删掉星号。", "通过策略版本及受控变更流程分阶段收紧；条件、权限边界与组织策略作为额外约束，不能替代业务权限梳理。"],
        "verification": ["上传同一策略的完整修订配置并执行 iam 复测，保留资源身份和语句证据；info 只表示本条宽泛条件未命中，不证明最小权限。", "如具备授权，可在 AWS 自行使用 IAM Access Analyzer 策略验证和业务测试；外部工具未由本项目执行，其结果应独立记录。"],
        "rollback": ["若合法业务出现授权失败，通过审批恢复已记录的策略版本并定位缺少的具体动作，避免恢复长期管理员权限作为默认解决方案。"],
        "limitations": ["缺少历史调用不等于权限永远无用；本报告不计算完整有效权限，也不发起 AssumeRole 或权限提升测试。"],
        "references": [_reference("AWS IAM 最佳实践", _IAM), _reference("AWS IAM Access Analyzer 范围", _ANALYZER)],
    },
    "iam.trust_principal": {
        "prerequisites": ["确认目标角色、受信账号/主体、正常调用者和跨账号业务；记录允许的身份提供方及适用条件。", "保留原信任策略与恢复渠道；ExternalId、组织条件等实际值由授权人员在原文件核对，不应上传凭据补充上下文。"],
        "red_review": ["核对证据中的 Principal 通配符、允许动作和 Condition 是否有业务依据；存在宽泛声明不证明任意主体实际能够承担角色。", "分别检查信任策略和调用方身份授权，区分第三方委派、AWS 服务主体与组织内访问；本工具未验证条件真值或执行角色承担。"],
        "blue_steps": ["将信任主体限定为明确需要的账号、角色或服务，并按集成协议使用合适条件；第三方角色委派时核对 ExternalId 防混淆代理设计。", "分阶段验证合法联合登录、服务调用和自动化，避免用删除全部受信主体的方式破坏正常业务。"],
        "verification": ["上传同一角色的修订信任策略，选择 iam 复测并人工核对资源对应；未知或缺失策略不能作为已整改。", "由获授权人员在真实 AWS 环境使用预期调用者和不被授权的测试主体验证边界；可另行查看 Access Analyzer 外部访问发现，本工具未执行这些操作。"],
        "rollback": ["发生合法委派故障时，通过现有管理员恢复已批准的信任策略版本；保留失败上下文后缩小调整，勿临时改为任意主体。"],
        "limitations": ["Principal、Condition 和外部授权共同决定访问；当前静态检查不证明实际角色访问、域身份或跨账号权限。"],
        "references": [_reference("AWS 第三方角色委派", "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html"), _reference("AWS IAM Access Analyzer 范围", _ANALYZER)],
    },
    "storage.public_access_block": {
        "prerequisites": ["确认相同存储桶、账号、区域、访问点和公开业务需求；先记录静态网站/CDN/跨账号消费方式，避免直接中断业务。", "补充组织/账号级、桶级和访问点公共访问保护，以及相关桶策略、ACL、对象所有权配置；单份桶级配置不足以判断实际公开。"],
        "red_review": ["从字段证据逐项核对四个桶级保护开关，明确哪些关闭、缺失或未知；关闭一个开关不等于存在匿名读取。", "由授权人员组合复核账号、桶和访问点限制及资源策略；不主动下载对象或将外部地址变为测试目标。"],
        "blue_steps": ["在确认业务兼容后按所需范围启用公共访问保护，并清理不必要的公开 ACL/策略；各层设置需一起审查。", "确需公开分发时记录批准范围并评估合适的受控分发架构；不要为通过检查盲目关闭静态网站或跨账号业务。"],
        "verification": ["导出同桶四项完整布尔配置后做 storage 复测，检查未知字段清空；四项为 true 只验证当前桶级声明。", "在真实环境另行核对账号/访问点最严格组合及正常读写业务，并保留外部审查记录；本工具未访问存储桶或对象。"],
        "rollback": ["变更前保留各层设置及业务访问方式；合法访问受损时通过批准流程恢复所需的最小例外，避免全局解除公共访问保护。"],
        "limitations": ["S3 会组合应用相关层次的限制；当前结果不计算完整公开访问，也不证明对象无敏感数据或无其他授权路径。"],
        "references": [_reference("AWS S3 公共访问保护及组合规则", _S3_BLOCK)],
    },
    "storage.bucket_policy_principal": {
        "prerequisites": ["确认策略所属桶及使用方，保存原策略和当前账号/桶/访问点保护状态；Condition 的实际值须在授权原配置查看。", "记录对象 ARN 与桶 ARN 的差异、CloudFront/服务主体、跨账号访问及业务公开例外；不要从名字推断资源关系。"],
        "red_review": ["按证据语句索引检查 Allow Principal 的范围、Action、Resource 与条件；宽泛主体不直接证明对象公开或可写。", "结合显式拒绝、公共访问保护、资源所有权及服务访问条件人工复核；外部账号权限和敏感对象内容不在本工具已验证范围。"],
        "blue_steps": ["保留必要的服务与跨账号集成，将主体、动作、资源及条件收敛为已批准业务范围；避免一刀切移除正常分发策略。", "通过现有 IaC/策略发布流程评审差异，区分桶级和对象级操作，保留必要的安全传输与来源约束。"],
        "verification": ["上传同一桶策略修订并选择 storage 复测；info 仅表示未再命中本条宽泛 Allow 条件，不证明桶已私有。", "由授权人员在真实环境核对预期访问和拒绝路径，可另行审阅 Access Analyzer；本项目未请求对象或执行 AWS 策略求值。"],
        "rollback": ["正常消费路径失败时依据原策略版本恢复已审批部分，并重新核对资源/条件；不要为恢复服务直接授予所有主体所有动作。"],
        "limitations": ["不能仅凭单份桶策略计算公开访问或有效权限，未提供的 ACL、访问点和账号约束可能改变结论。"],
        "references": [_reference("AWS S3 策略动作与资源", "https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html"), _reference("AWS S3 公共访问保护", _S3_BLOCK)],
    },
    "storage.encryption_declaration": {
        "prerequisites": ["确认桶、区域、数据分类及加密/密钥控制要求；缺少显式加密声明不意味着对象未加密。", "若选择 KMS，先核对密钥状态、区域、密钥策略、读写主体及复制服务权限，并评估请求配额和费用。"],
        "red_review": ["核对证据记录的加密算法及未知字段；把 IaC 声明、桶默认设置和已有对象状态分开记录。", "默认配置不能证明 KMS 密钥可用、所有对象使用同一算法或具备合规性；本工具不解密对象、不取得密钥。"],
        "blue_steps": ["按真实数据要求选择 SSE-S3、SSE-KMS 或 DSSE-KMS 等受支持配置；不因存在更复杂选项就机械替换当前合适方案。", "修改默认加密前验证应用读写与复制链路的密钥权限；已有对象是否需迁移应单独评估和批准，不能假设默认设置已重写历史对象。"],
        "verification": ["补充并上传同桶完整加密配置后做 storage 复测，确认声明可解析；info 保持声明信息含义，不提升为部署/对象验证。", "授权人员另行核对实际桶设置、对象清单/元数据、业务读写、密钥轮换和恢复场景；本项目未调用 S3/KMS API。"],
        "rollback": ["保留原默认加密配置、密钥依赖和恢复计划；回退默认设置不会自动改变已写入对象，不得为回退停用或删除仍被引用的密钥。"],
        "limitations": ["S3 新对象有默认服务端加密；静态缺失不等于明文。未验证历史对象、KMS 策略、密钥可用性、复制和合规要求。"],
        "references": [_reference("AWS S3 默认加密范围", _S3_ENCRYPTION)],
    },
    "storage.bucket_context": {
        "prerequisites": ["确认上传文件所属桶和采集时间；当前只有存储桶本体，不足以判断其组合保护。", "从同一授权环境补充公共访问保护、桶/访问点策略、加密、对象所有权及账号级设置；不要提供访问密钥。"],
        "red_review": ["将此项作为覆盖缺口记录，不将资源缺席、未导出保护或未知值描述为已发现公开桶。", "区分未提供、未支持和确认不存在三种情况，记录需要资产所有者补充的证据。"],
        "blue_steps": ["优先补齐同桶关联配置及资源身份，再逐项评估公共访问、策略和加密；不根据文件缺口直接修改云端。", "对必须保留的公开或跨账号业务建立批准说明，确保后续导出能保留关联配置但不含凭据。"],
        "verification": ["重新上传完整导出并执行 storage 检查，确认新关联资源获得专用规则结果；本条缺口消失不应被自动解释为安全整改。", "人工核对关联资源是否确属同一真实桶，配置文件不能自行证明部署、访问或对象状态。"],
        "rollback": ["本项优先补充证据，无需直接变更云端；若后续实施配置调整，应各自保存原版本并使用对应规则的回退步骤。"],
        "limitations": ["资源本体缺少关联资料始终保持未知，不能通过空资源清单或删除配置使案例被判定已修复。"],
        "references": [_reference("AWS S3 公共访问保护", _S3_BLOCK), _reference("AWS S3 默认加密", _S3_ENCRYPTION)],
    },
}


def implementation_guide(check: dict[str, Any]) -> dict[str, Any] | None:
    """Bind original manual guidance only to an actually executed known rule."""
    identifier = check.get("id")
    if not isinstance(identifier, str) or identifier not in _GUIDES:
        return None
    guide = copy.deepcopy(_GUIDES[identifier])
    status = check.get("status")
    status = status if isinstance(status, str) and status in {"review", "unknown", "pass", "info", "not_applicable"} else "unknown"
    raw_evidence = check.get("evidence_ids")
    evidence_ids = [item for item in raw_evidence if isinstance(item, str)][:20] if isinstance(raw_evidence, list) else []
    proof = check.get("evidence")
    pointer = proof.get("pointer") if isinstance(proof, dict) else None
    resource = check.get("resource_id")
    guide.update(version=1, rule_id=identifier, resource_id=resource if isinstance(resource, str) else "",
                 evidence_ids=evidence_ids, source_pointer=pointer if isinstance(pointer, str) else "",
                 status=status, ai_required=False, executed=False, deployed_state_verified=False)
    if status == "unknown":
        guide["prerequisites"].insert(0, "本条为未知/资料不足：先补充可解析的对应配置，不能按已确认风险直接整改或把缺失当作安全。")
    elif status in {"pass", "info", "not_applicable"}:
        guide["prerequisites"].insert(0, "本次未命中待复核条件或仅保留信息；以下是按需人工复核指南，不要求为了通过检查修改已有正确配置。")
    guide["limitations"].append("指南不会执行命令、部署配置或自动关闭案例；AWS 真实环境和商业 AI 推理均未由本指南验证。")
    return guide
