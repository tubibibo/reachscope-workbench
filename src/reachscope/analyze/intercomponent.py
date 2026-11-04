"""跨组件可达（v0.3 / M1）：显式 Intent + 攻击者数据 → 目标组件入口。

只回答一个问题：**入口方法（或深度 ≤ 4 的 callee）里，有没有一条
「攻击者可控数据被放进 Intent，再显式启动本 APK 内另一个组件」的边？**

约束（刻意做小，避免把启发式扩成完整 Android 数据流）：

1. **只认显式目标**：`new Intent(ctx, Target.class)`、`setClass`、`setClassName`、
   `setComponent`。隐式 Intent（action/category）需要 intent-filter 匹配，容易歧义，
   v0.3 不跟。
2. **只认 Intent 携带了攻击者数据**：`putExtra*` / `setData*` 的实参标签必须是
   `intent_data` / `intent_extra` / `deeplink_param`（入口方法里的 `getIntent()`
   本身也带 `INTENT_OBJECT` / `INTENT_EXTRAS` 源锚点）。没有数据的 `startActivity`
   是正常页面跳转，不是一条链。
3. **记录载体与 key**（M1）：`IntentPayload` 记 `carrier`（extra/data）、extra 的
   key 与写入点；目标侧 sink 读取的 key 必须与源侧有交集（`chains.py` 做匹配）。
4. **不在这里判目标是否导出**：跨组件转发到未导出组件正是本能力要覆盖的场景；
   目标能否被第三方拉起由调用方（入口组件）的 J1 决定。
5. **启动方法与目标类型绑定**（M1）：`startActivity*` → Activity，
   `startService*` / `bindService` → Service，`sendBroadcast*` → Receiver。
6. **形参只走一层**：callee 形参的污点由 `regflow` 的过程间标签处理，调用方可以
   经 `initial=` 把实参标签送进被调方法；本模块只在单个方法内跟踪 Intent 对象状态。
   更深的传递、字段/容器转存不在模型内。

本模块只产出「边」；是否把边接成链、跳数上限与环检测在 `analyze/chains.py`。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..extract.components import descriptor_of
from ..graph import regflow
from ..ingest.smali import Instruction, MethodInfo, SmaliIndex
from ..ir.model import Component, ComponentType, SourceLoc

#: 可以直接接收 `startActivity` 的框架类型（receiver 的声明类型）。
CONTEXT_TYPES: frozenset[str] = frozenset({
    "Landroid/app/Activity;",
    "Landroid/content/Context;",
    "Landroid/content/ContextWrapper;",
})

#: 启动方法名 → 允许的目标组件类型（M1）。
START_METHODS: dict[str, ComponentType] = {
    "startActivity": ComponentType.ACTIVITY,
    "startActivityForResult": ComponentType.ACTIVITY,
    "startService": ComponentType.SERVICE,
    "startForegroundService": ComponentType.SERVICE,
    "bindService": ComponentType.SERVICE,
    "sendBroadcast": ComponentType.RECEIVER,
    "sendOrderedBroadcast": ComponentType.RECEIVER,
}

#: androidx 的静态包装：Intent 是第 2 个实参（第 1 个是 Context/Activity）。
COMPAT_CLASSES: frozenset[str] = frozenset({
    "Landroidx/core/content/ContextCompat;",
    "Landroidx/core/app/ActivityCompat;",
})

#: `put*` / `setData*` 里视为“携带数据”的调用前缀。
_DATA_PREFIXES = ("put", "setData")

_INTENT = "Landroid/content/Intent;"
_COMPONENT_NAME = "Landroid/content/ComponentName;"

#: 载体名（`IntentPayload.carrier`）。
CARRIER_EXTRA = "extra"
CARRIER_DATA = "data"


@dataclass(frozen=True)
class IntentPayload:
    """一条被放进 Intent 的攻击者可控数据（载体 + key + 写入点）。"""

    carrier: str
    key: str
    evidence: SourceLoc

    @property
    def is_extra(self) -> bool:
        return self.carrier == CARRIER_EXTRA

    @property
    def is_data(self) -> bool:
        return self.carrier == CARRIER_DATA


@dataclass(frozen=True)
class CrossComponentHop:
    """一条显式跨组件边（目标 + 目标类型 + 数据载荷 + 启动点）。"""

    target_descriptor: str
    target_type: ComponentType
    payloads: tuple[IntentPayload, ...]
    evidence: SourceLoc

    @property
    def extra_keys(self) -> frozenset[str]:
        """已知的 extra key 集合（``""`` 表示 key 不可判定，单独处理）。"""
        return frozenset(
            payload.key
            for payload in self.payloads
            if payload.is_extra and payload.key
        )

    @property
    def has_unknown_extra_key(self) -> bool:
        return any(payload.is_extra and not payload.key for payload in self.payloads)

    @property
    def has_data(self) -> bool:
        return any(payload.is_data for payload in self.payloads)


@dataclass
class _IntentState:
    """一条 Intent 寄存器的已知状态（只在本方法内传播）。"""

    target: str | None = None
    conflicted: bool = False
    payloads: tuple[IntentPayload, ...] = ()

    def set_target(self, target: str | None) -> None:
        """写入目标；已有目标且不同 → 标记冲突（分支互斥时不猜）。"""
        if not target:
            return
        if self.target is not None and self.target != target:
            self.conflicted = True
        self.target = target

    def add_payload(self, payload: IntentPayload) -> None:
        """同一 (carrier, key) 只记第一次写入点，避免链上重复。"""
        if any(
            item.carrier == payload.carrier and item.key == payload.key
            for item in self.payloads
        ):
            return
        self.payloads = self.payloads + (payload,)

    def copy(self) -> _IntentState:
        return _IntentState(self.target, self.conflicted, self.payloads)


def find_hops(
    method: MethodInfo,
    index: SmaliIndex,
    *,
    package: str = "",
    class_descriptor: str = "",
    initial: dict[str, regflow.Tag] | None = None,
) -> list[CrossComponentHop]:
    """扫描一个方法，返回所有「攻击者可控 Intent → 显式目标」的启动点。"""
    tags = regflow.propagate(method, smali=index, initial=initial).tags
    intents: dict[str, _IntentState] = {}
    classes: dict[str, str] = {}
    strings: dict[str, str] = {}
    component_names: dict[str, str] = {}
    owner = class_descriptor or _class_descriptor_of(method)
    hops: list[CrossComponentHop] = []

    for instruction in method.instructions:
        const = regflow.parse_const_string(instruction)
        if const is not None:
            _overwrite_register(const[0], intents, classes, strings, component_names)
            strings[const[0]] = const[1]
            continue

        class_const = _parse_const_class(instruction)
        if class_const is not None:
            _overwrite_register(class_const[0], intents, classes, strings, component_names)
            classes[class_const[0]] = class_const[1]
            continue

        new_instance = regflow.parse_new_instance(instruction)
        if new_instance is not None:
            register, descriptor = new_instance
            _overwrite_register(register, intents, classes, strings, component_names)
            if descriptor == _INTENT:
                intents[register] = _IntentState()
            elif descriptor == _COMPONENT_NAME:
                component_names[register] = ""
            continue

        if instruction.opcode.startswith("move-object"):
            _copy_move(instruction, intents, classes, strings, component_names)
            continue

        site = regflow.parse_invoke(instruction)
        if site is not None:
            if site.class_descriptor == _INTENT:
                _apply_intent_call(
                    method,
                    site,
                    tags,
                    strings,
                    classes,
                    component_names,
                    intents,
                    package,
                    _instruction_loc(method, instruction),
                )
                result = regflow.result_of_call(method, site.index)
                if result is not None and not _copy_result(site, method, intents):
                    _clear(result, intents, classes, strings, component_names)
            elif site.class_descriptor == _COMPONENT_NAME:
                _apply_component_name_call(
                    site, strings, classes, component_names, package
                )
                result = regflow.result_of_call(method, site.index)
                if result is not None:
                    _clear(result, intents, classes, strings, component_names)
            else:
                target_type = _start_kind(site, owner, index)
                if target_type is not None:
                    intent_register = (
                        site.value_args[0] if site.value_args else None
                    )
                    state = intents.get(intent_register) if intent_register else None
                    if (
                        state is not None
                        and state.target is not None
                        and not state.conflicted
                        and state.payloads
                    ):
                        hops.append(
                            CrossComponentHop(
                                target_descriptor=state.target,
                                target_type=target_type,
                                payloads=state.payloads,
                                evidence=_instruction_loc(method, instruction),
                            )
                        )
                result = regflow.result_of_call(method, site.index)
                if result is not None:
                    _clear(result, intents, classes, strings, component_names)
            continue

        # 其他会写寄存器的指令（const/4、iget、sget、aget…）：清掉旧状态。
        defined = _defined_register(instruction)
        if defined:
            _clear(defined, intents, classes, strings, component_names)

    return hops


def find_component_hops(
    component: Component,
    index: SmaliIndex,
    *,
    package: str = "",
) -> list[CrossComponentHop]:
    """一个组件所有入口方法上的跨组件边（反例归因用）。"""
    class_info = index.get_class(descriptor_of(component.name))
    if class_info is None:
        return []
    from .judgments import is_entry_method

    hops: list[CrossComponentHop] = []
    for method in class_info.methods:
        if not is_entry_method(method.name, component.type):
            continue
        hops.extend(
            find_hops(
                method,
                index,
                package=package,
                class_descriptor=class_info.descriptor,
            )
        )
    return hops


def _apply_intent_call(
    method: MethodInfo,
    site: regflow.InvokeSite,
    tags: dict[str, regflow.Tag],
    strings: dict[str, str],
    classes: dict[str, str],
    component_names: dict[str, str],
    intents: dict[str, _IntentState],
    package: str,
    evidence: SourceLoc,
) -> None:
    """更新 Intent 寄存器的目标与“是否携带攻击者数据”。"""
    receiver = site.receiver
    state = intents.get(receiver) if receiver else None
    if state is None:
        return

    params = regflow.param_types(site.signature)
    values = site.value_args
    if site.method == "<init>":
        if params == ["Landroid/content/Context;", "Ljava/lang/Class;"] and len(values) >= 2:
            state.set_target(classes.get(values[1]))
        elif params == [_INTENT] and values:
            source = intents.get(values[0])
            if source is not None:
                state.target = source.target
                state.conflicted = source.conflicted
                state.payloads = source.payloads
        return

    if site.method == "setClass":
        if len(values) >= 2:
            state.set_target(classes.get(values[1]))
        return

    if site.method == "setClassName":
        # 三种重载：`(Context, pkg, cls)` / `(pkg, cls)` / `(cls)`。
        if len(values) >= 3 and params[:1] == ["Landroid/content/Context;"]:
            state.set_target(
                _class_name_to_descriptor(
                    strings.get(values[1]), strings.get(values[2]), package
                )
            )
        elif len(values) >= 2:
            state.set_target(
                _class_name_to_descriptor(
                    strings.get(values[0]), strings.get(values[1]), package
                )
            )
        elif len(values) == 1:
            state.set_target(
                _class_name_to_descriptor(None, strings.get(values[0]), package)
            )
        return

    if site.method == "setComponent":
        if values:
            state.set_target(component_names.get(values[0]) or None)
        return

    if site.method in ("setData", "setDataAndType"):
        if any(_attacker_controlled(tags, value) for value in values):
            state.add_payload(IntentPayload(CARRIER_DATA, "", evidence))
        return

    if site.method.startswith(_DATA_PREFIXES):
        # `putExtra(key, value)` / `putExtras(bundle)` / `putStringArrayListExtra(...)`。
        key = ""
        if values:
            # 线性扫描会把别的分支里的重定义当成最后一次定义；key 必须按到达
            # 定义取（OVAA 的 v2 就是跨分支复用）。
            resolved = regflow.dominating_constant(method, site.index, values[0])
            key = resolved if resolved is not None else strings.get(values[0], "")
        payload_values = values[1:] if values else ()
        if any(_attacker_controlled(tags, value) for value in payload_values):
            state.add_payload(IntentPayload(CARRIER_EXTRA, key, evidence))


def _apply_component_name_call(
    site: regflow.InvokeSite,
    strings: dict[str, str],
    classes: dict[str, str],
    component_names: dict[str, str],
    package: str,
) -> None:
    """`new ComponentName(...)` 的目标解析。"""
    if site.method != "<init>" or not site.receiver:
        return
    params = regflow.param_types(site.signature)
    values = site.value_args
    target: str | None = None
    if params == ["Landroid/content/Context;", "Ljava/lang/Class;"] and len(values) >= 2:
        target = classes.get(values[1])
    elif params == ["Ljava/lang/String;", "Ljava/lang/String;"] and len(values) >= 2:
        target = _class_name_to_descriptor(
            strings.get(values[0]), strings.get(values[1]), package
        )
    elif params == ["Landroid/content/Context;", "Ljava/lang/String;"] and len(values) >= 2:
        target = _class_name_to_descriptor(None, strings.get(values[1]), package)
    elif params == ["Ljava/lang/String;"] and values:
        target = _class_name_to_descriptor(None, strings.get(values[0]), package)
    if target:
        component_names[site.receiver] = target


def _copy_move(
    instruction: Instruction,
    intents: dict[str, _IntentState],
    classes: dict[str, str],
    strings: dict[str, str],
    component_names: dict[str, str],
) -> None:
    """`move-object/from16 v0, v1` → 复制所有已知状态。"""
    target, _, source = instruction.operands_raw.partition(",")
    target = target.strip()
    source = source.strip()
    if not target or not source:
        return
    _overwrite_register(target, intents, classes, strings, component_names)
    if source in intents:
        intents[target] = intents[source].copy()
    if source in classes:
        classes[target] = classes[source]
    if source in strings:
        strings[target] = strings[source]
    if source in component_names:
        component_names[target] = component_names[source]


def _copy_result(
    site: regflow.InvokeSite, method: MethodInfo, intents: dict[str, _IntentState]
) -> bool:
    """`setClass` / `putExtra` 等返回 Intent 自身；`move-result-object` 后继续传播。

    返回是否复制成功——失败时调用方要清掉结果寄存器里的旧状态。
    """
    if site.receiver is None or site.receiver not in intents:
        return False
    result = regflow.result_of_call(method, site.index)
    if result is None:
        return False
    intents[result] = intents[site.receiver].copy()
    return True


def _start_kind(
    site: regflow.InvokeSite,
    owner: str,
    index: SmaliIndex,
) -> ComponentType | None:
    """是否为 Android 的跨组件启动调用，并返回允许的目标类型。

    允许三种 receiver 声明：
    1. 框架类型（`Activity` / `Context` / `ContextWrapper`）；
    2. 当前方法所属类（`this.startActivity(...)`，smali 里 owner 是子类）；
    3. 当前类的 APK 内父类（`super.startActivity(...)`）。
    另外支持 `ContextCompat` / `ActivityCompat` 的静态包装。
    """
    target_type = START_METHODS.get(site.method)
    if target_type is None:
        return None
    params = regflow.param_types(site.signature)

    if site.opcode.startswith("invoke-static"):
        if site.class_descriptor not in COMPAT_CLASSES:
            return None
        if len(params) < 2 or params[1] != _INTENT:
            return None
        return target_type

    if not params or params[0] != _INTENT:
        return None
    if site.class_descriptor in CONTEXT_TYPES or site.class_descriptor == owner:
        return target_type
    if site.class_descriptor in _super_chain(owner, index):
        return target_type
    return None


def _super_chain(descriptor: str, index: SmaliIndex) -> set[str]:
    """当前类在 APK 内的父类链（不到框架层，够覆盖 `super.xxx` 用法）。"""
    chain: set[str] = set()
    current = descriptor
    while current and current not in chain:
        chain.add(current)
        class_info = index.get_class(current)
        if class_info is None:
            break
        current = class_info.super_name
    return chain


def _attacker_controlled(tags: dict[str, regflow.Tag], register: str) -> bool:
    tag = tags.get(register)
    return tag is not None and tag.attacker_controlled


def _instruction_loc(method: MethodInfo, instruction: Instruction) -> SourceLoc:
    """调用 / 写入点的证据位置（与 `judgments._instruction_loc` 同口径）。"""
    snippet = f"{instruction.opcode} {instruction.operands_raw}".strip()
    if len(snippet) > 200:
        snippet = snippet[:200]
    return SourceLoc(file=method.source.file, line=instruction.file_line, snippet=snippet)


def _clear(
    register: str,
    intents: dict[str, _IntentState],
    classes: dict[str, str],
    strings: dict[str, str],
    component_names: dict[str, str],
) -> None:
    """寄存器被重新定义 → 清掉所有旧状态（M1：不再默默沿用）。"""
    intents.pop(register, None)
    classes.pop(register, None)
    strings.pop(register, None)
    component_names.pop(register, None)


def _overwrite_register(
    register: str,
    intents: dict[str, _IntentState],
    classes: dict[str, str],
    strings: dict[str, str],
    component_names: dict[str, str],
) -> None:
    _clear(register, intents, classes, strings, component_names)


def _defined_register(instruction: Instruction) -> str | None:
    """该指令写入的寄存器（只覆盖会定义值的 opcode）。"""
    if instruction.opcode.startswith("move-result"):
        return regflow.result_register(instruction)
    if not instruction.opcode.startswith(
        ("const", "move", "new-instance", "iget", "sget", "aget", "array-get")
    ):
        return None
    register = instruction.operands_raw.partition(",")[0].strip()
    return register or None


def _parse_const_class(instruction: Instruction) -> tuple[str, str] | None:
    """`const-class v0, Lcom/x/Y;` → `(v0, Lcom/x/Y;)`。"""
    if instruction.opcode != "const-class":
        return None
    register, separator, rest = instruction.operands_raw.partition(",")
    if not separator:
        return None
    return register.strip(), rest.strip()


def _class_name_to_descriptor(
    package: str | None, class_name: str | None, default_package: str
) -> str | None:
    """`setClassName` / `ComponentName` 的字符串 → smali 描述符。"""
    name = (class_name or "").strip()
    if not name:
        return None
    if name.startswith("."):
        prefix = (package or default_package).strip()
        if not prefix:
            return None
        name = f"{prefix}{name}"
    elif "." not in name:
        prefix = (package or default_package).strip()
        if not prefix:
            return None
        name = f"{prefix}.{name}"
    return descriptor_of(name)


def _class_descriptor_of(method: MethodInfo) -> str:
    """从 `SourceLoc.file` 反推方法所属类描述符（`smali*/com/x/Y.smali`）。"""
    parts = method.source.file.replace("\\", "/").split("/")
    if parts and parts[0].startswith("smali"):
        parts = parts[1:]
    if not parts or not parts[-1].endswith(".smali"):
        return ""
    return "L" + "/".join(parts)[: -len(".smali")] + ";"


__all__ = [
    "CARRIER_DATA",
    "CARRIER_EXTRA",
    "COMPAT_CLASSES",
    "CONTEXT_TYPES",
    "START_METHODS",
    "CrossComponentHop",
    "IntentPayload",
    "find_component_hops",
    "find_hops",
]
