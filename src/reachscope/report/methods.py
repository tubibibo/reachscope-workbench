"""六条判据的一句话说明（PLAN §6.3）。

`reachscope rules list`（cli）与 HTML 报告第 8 章共用同一份文本，
避免两处各写一遍后逐渐漂移。
"""

from __future__ import annotations

RULE_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    (
        "J1",
        (
            "零特权可达性：组件 exported、权限非 signature 级，普通第三方 App 可触达；"
            "未 export → FAIL，权限保护级别未解析 → UNKNOWN。"
        ),
    ),
    (
        "J2",
        (
            "实现真实性：manifest 声明的组件类必须在 APK 内有具体实现；"
            "缺实现或抽象类无具体子类 → FAIL。"
        ),
    ),
    (
        "J3",
        (
            "数据归属：链上 sink 的归属取最高一档（own/shared/cross-app/high）；"
            "全为 own 则 impact 降为 low。"
        ),
    ),
    (
        "J4",
        (
            "WebView 桥暴露面：页面是否外部可控 + 来源校验强度 + 校验是否覆盖首次加载 "
            "+ 桥是否撤销 + 文件访问 + 高危 sink，逐项加减分映射到 exploitability。"
        ),
    ),
    (
        "J5",
        (
            "深链直灌：入口组件的 onCreate/onNewIntent/onStart/onResume 中，"
            "intent_data / deeplink_param 是否流入 loadUrl / 文件路径 / 桥方法。"
        ),
    ),
    (
        "J6",
        (
            "链式可达：每一步都要有调用图或寄存器流证据；"
            "出现 unknown 或深度超过 4 → confidence=low、evidence_complete=false。"
        ),
    ),
)

__all__ = ["RULE_DESCRIPTIONS"]
