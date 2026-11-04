"""方法内寄存器流（PLAN §6.1 / TASKS T3.1）。

**本模块是全项目唯一的寄存器回溯 / 标签传播实现。**

M2 时 `extract/regtrace.py` 有一份单步回溯实现，被 webview / origin / sinks / bridge
四张卡共用（D-041）。T3.1 把那份实现**整体搬进本模块并删除原文件**，四张卡改为
`from ..graph import regflow` —— 不允许两份实现并存（D-056）。

两件事：

1. **指令解析与单步回溯**（`parse_invoke` / `backtrack_*`）：M2 的既有能力，行为逐字未改。
2. **§6.1 的标签传播**（`propagate` / `Tag`）：T3.1 新增，给方法内每个寄存器打来源标签。

传播规则（只在本方法内，按指令顺序单遍扫描）：

1. `const-string vX, "..."` → `const`
2. `move-object* vA, vB` → 复制 B 的标签到 A
3. `invoke-*` 后紧跟 `move-result-object vX` → `call_result`
4. `Landroid/content/Intent;->getData()` → `intent_data`
5. `Landroid/content/Intent;->getStringExtra(...)` → `intent_extra(arg)`
6. `Landroid/net/Uri;->getQueryParameter(...)` → `deeplink_param(arg)`
7. 其他赋值 → `unknown`

**跨方法边界**（§6.1 原文）：v0.1 只跟进一层 —— 若 `call_result` 的方法在本 APK 内
且方法体 ≤ 80 条指令，则进入该方法做同样的标签传播，并把返回值标签带回；
**超过一层、或方法体超过 80 条指令 → `unknown` 且 `incomplete=True`**，
由调用方写进 `evidence_complete=false`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..ingest.smali import Instruction, MethodInfo, SmaliIndex

#: 视为“给寄存器赋值”的 opcode 前缀（invoke 的结果走 move-result*，不算）。
DEFINING_PREFIXES = ("const", "move", "new-instance", "iget", "sget", "aget", "array-get")

#: 回溯链的最大步数（防止异常 smali 里打转）。
MAX_BACKTRACK_STEPS = 4

#: §6.1：跨方法只跟进一层。
MAX_CROSS_METHOD_DEPTH = 1

#: §6.1：只进入方法体 ≤ 80 条指令的目标方法。
MAX_CROSS_METHOD_INSTRUCTIONS = 80


class TagKind(StrEnum):
    """§6.1 的六类标签 + `unknown`（不是“猜不出来就不写”，而是显式写出）。

    M1 增补两个**非攻击者可控**的对象标签，用来锚定“来源”：

    - `INTENT_OBJECT`：寄存器持有 Intent 对象；`value` 为 `entry`（来自
      `getIntent()` 或它的克隆）或 `local`（方法内 `new Intent(...)`）。
    - `INTENT_EXTRAS`：寄存器持有入口 Intent 的 `Bundle`（`getExtras()`）。
    """

    CONST = "const"
    INTENT_DATA = "intent_data"
    INTENT_EXTRA = "intent_extra"
    DEEPLINK_PARAM = "deeplink_param"
    INTENT_OBJECT = "intent_object"
    INTENT_EXTRAS = "intent_extras"
    FIELD = "field"
    CALL_RESULT = "call_result"
    UNKNOWN = "unknown"


#: `Tag.value` 的两个取值：入口 Intent / 方法内本地构造的 Intent。
INTENT_ENTRY = "entry"
INTENT_LOCAL = "local"

#: Intent 的 extra 读取方法（返回值 → `intent_extra(key)`）。
_EXTRA_GETTERS: frozenset[str] = frozenset({
    "getStringExtra",
    "getIntExtra",
    "getLongExtra",
    "getFloatExtra",
    "getDoubleExtra",
    "getShortExtra",
    "getByteExtra",
    "getCharExtra",
    "getBooleanExtra",
    "getCharSequenceExtra",
    "getStringArrayExtra",
    "getIntArrayExtra",
    "getStringArrayListExtra",
    "getIntegerArrayListExtra",
    "getParcelableExtra",
    "getParcelableArrayListExtra",
    "getSerializableExtra",
    "getBundleExtra",
})

#: `Bundle` 的读取方法（receiver 必须是入口 Intent 的 extras）。
_BUNDLE_GETTERS: frozenset[str] = frozenset({
    "get",
    "getString",
    "getCharSequence",
    "getInt",
    "getLong",
    "getFloat",
    "getDouble",
    "getShort",
    "getByte",
    "getBoolean",
    "getStringArray",
    "getIntArray",
    "getStringArrayList",
    "getIntegerArrayList",
    "getParcelable",
    "getParcelableArrayList",
    "getSerializable",
    "getBundle",
})

#: 把任意攻击者可控实参带进返回值的静态调用（`Uri.parse` / `String.format` 等）。
_STATIC_DERIVATIONS: frozenset[tuple[str, str]] = frozenset({
    ("Landroid/net/Uri;", "parse"),
    ("Ljava/lang/String;", "valueOf"),
    ("Ljava/lang/String;", "format"),
    ("Landroid/text/TextUtils;", "join"),
})

#: 同上，但 receiver 与实参都可能带污点（`String.concat` / `StringBuilder.append`）。
_INSTANCE_DERIVATIONS: frozenset[tuple[str, str]] = frozenset({
    ("Ljava/lang/String;", "concat"),
    ("Ljava/lang/StringBuilder;", "append"),
    ("Ljava/lang/StringBuffer;", "append"),
})


#: §6.1 里“攻击者可控”的三类标签（T3.4 的 J4-4b、T3.5 找 attacker-controlled 用）。
ATTACKER_CONTROLLED = (
    TagKind.INTENT_DATA,
    TagKind.INTENT_EXTRA,
    TagKind.DEEPLINK_PARAM,
)


@dataclass(frozen=True)
class Tag:
    """一个寄存器的来源标签（§6.1）。

    `value` 的语义随 `kind`：`const` 是字面量、`intent_extra`/`deeplink_param` 是键名、
    `call_result` 是 `Lcls;->name(sig)ret`、`field` 是字段名（`owner` 是所属类）。
    `incomplete=True` 表示**因为深度或体积限制没能跟到底**，调用方必须据此
    把 `evidence_complete` 置 False（不许当成“判出来了”）。
    """

    kind: TagKind = TagKind.UNKNOWN
    value: str = ""
    owner: str = ""
    incomplete: bool = False

    @property
    def attacker_controlled(self) -> bool:
        """是否来自攻击者可控的输入（intent / 深链参数）。"""
        return self.kind in ATTACKER_CONTROLLED


UNKNOWN = Tag(TagKind.UNKNOWN)


@dataclass(frozen=True)
class FlowResult:
    """一次 `propagate` 的结果。"""

    tags: dict[str, Tag] = field(default_factory=dict)
    #: 是否出现过“跟不下去”的情况（跨方法超限 / 方法体过大）。
    incomplete: bool = False

    def tag_of(self, register: str | None) -> Tag:
        """查寄存器的标签；寄存器为空或从未赋值 → `unknown`（不猜）。"""
        if not register:
            return UNKNOWN
        return self.tags.get(register, UNKNOWN)


@dataclass(frozen=True)
class InvokeSite:
    """一条 `invoke-*` 指令的解析结果。"""

    index: int
    opcode: str
    class_descriptor: str
    method: str
    signature: str
    args: tuple[str, ...]

    @property
    def ref(self) -> str:
        """`Lcls;->name(sig)ret`。"""
        return f"{self.class_descriptor}->{self.method}{self.signature}"

    @property
    def receiver(self) -> str | None:
        """实例方法的 receiver 寄存器（静态方法为 None）。"""
        return self.args[0] if self.args else None

    @property
    def value_args(self) -> tuple[str, ...]:
        """除 receiver 之外的实参寄存器。"""
        return self.args[1:]


# --- §6.1：标签传播 -------------------------------------------------------


def propagate(
    method: MethodInfo,
    *,
    stop: int | None = None,
    smali: SmaliIndex | None = None,
    depth: int = 0,
    initial: dict[str, Tag] | None = None,
) -> FlowResult:
    """单遍扫描 `method`，返回每个寄存器的来源标签。

    - `stop`：只扫描 `instructions[:stop]`（用于“到某条指令为止”的查询）
    - `smali`：给了才会做跨方法跟进（§6.1 的一层），不给则 `call_result` 到此为止
    - `depth`：当前已跟进的层数，外部调用恒为 0
    - `initial`：调用方传入的形参标签（过程间污点）。**传入即完全覆盖默认值**；
      不传时按形参类型给 Intent / Uri 参数一个保守默认（见 `_default_param_tags`），
      这是为了让单方法回放（fixture / 单测）保持 §6.1 的口径。
    """
    limit = len(method.instructions) if stop is None else min(stop, len(method.instructions))
    tags: dict[str, Tag] = _default_param_tags(method) if initial is None else dict(initial)
    incomplete = False
    consumed: set[int] = set()

    for index in range(limit):
        if index in consumed:
            continue
        instruction = method.instructions[index]

        site = parse_invoke(instruction)
        if site is not None:
            if site.method == "<init>":
                _apply_intent_constructor(site, tags)
                continue
            result = _result_after(method, site.index)
            if result is not None:
                result_index, register = result
                tag = _tag_for_call(site, tags, smali, depth)
                tags[register] = tag
                consumed.add(result_index)
                if tag.incomplete:
                    incomplete = True
            continue

        const = parse_const_string(instruction)
        if const is not None:
            tags[const[0]] = Tag(TagKind.CONST, value=const[1])
            continue

        new_instance = parse_new_instance(instruction)
        if new_instance is not None:
            register, descriptor = new_instance
            tags[register] = (
                Tag(TagKind.INTENT_OBJECT, value=INTENT_LOCAL)
                if descriptor == "Landroid/content/Intent;"
                else UNKNOWN
            )
            continue

        if instruction.opcode.startswith("move-object"):
            target, _, source = instruction.operands_raw.partition(",")
            target = target.strip()
            source = source.strip()
            if target and source:
                tags[target] = tags.get(source, UNKNOWN)
            continue

        field_ref = _parse_field(instruction)
        if field_ref is not None:
            tags[field_ref[0]] = Tag(TagKind.FIELD, value=field_ref[2], owner=field_ref[1])
            continue

        if instruction.opcode.startswith("move-result"):
            # 未与任何 invoke 配对（异常 smali）：显式 unknown，不猜。
            move_register = result_register(instruction)
            if move_register:
                tags[move_register] = UNKNOWN
            continue

        if _defines(instruction, target := _target_register(instruction)):
            tags[target] = UNKNOWN

    return FlowResult(tags=tags, incomplete=incomplete)


def tag_at(
    method: MethodInfo,
    index: int,
    register: str | None,
    *,
    smali: SmaliIndex | None = None,
) -> Tag:
    """`index` 处（不含该指令）`register` 的标签；查不到 → `unknown`。"""
    return propagate(method, stop=index, smali=smali).tag_of(register)


def return_tag(method: MethodInfo, tags: dict[str, Tag]) -> Tag:
    """方法返回值的标签：取 `return*` 的操作数寄存器。

    `return-void` 或找不到 → `unknown`（**不用空标签冒充“无返回值”**）。
    """
    for instruction in reversed(method.instructions):
        if not instruction.opcode.startswith("return"):
            continue
        if instruction.opcode == "return-void":
            return UNKNOWN
        return tags.get(instruction.operands_raw.strip(), UNKNOWN)
    return UNKNOWN


def _tag_for_call(
    site: InvokeSite, tags: dict[str, Tag], smali: SmaliIndex | None, depth: int
) -> Tag:
    """一条调用的返回值标签（规则 3–6 + 跨方法一层 + M1 来源锚定）。"""
    # M1：`getIntent()` 是入口 Intent 的唯一可信来源；克隆构造函数见
    # `_apply_intent_constructor`。方法名 + 签名匹配，因为 smali 常把 owner 写成子类。
    if site.method == "getIntent" and site.signature == "()Landroid/content/Intent;":
        return Tag(TagKind.INTENT_OBJECT, value=INTENT_ENTRY)

    receiver_tag = tags.get(site.receiver) if site.receiver else None
    entry_intent = _is_entry_intent(receiver_tag)
    entry_extras = _is_entry_extras(receiver_tag)

    if site.class_descriptor == "Landroid/content/Intent;":
        if site.method in ("getData", "getDataString"):
            return Tag(TagKind.INTENT_DATA) if entry_intent else UNKNOWN
        if site.method == "getExtras":
            return (
                Tag(TagKind.INTENT_EXTRAS, value=INTENT_ENTRY) if entry_intent else UNKNOWN
            )
        if site.method in _EXTRA_GETTERS:
            return (
                Tag(TagKind.INTENT_EXTRA, value=_arg_const(site, tags))
                if entry_intent
                else UNKNOWN
            )

    if (
        site.class_descriptor == "Landroid/os/Bundle;"
        and site.method in _BUNDLE_GETTERS
    ):
        return (
            Tag(TagKind.INTENT_EXTRA, value=_arg_const(site, tags))
            if entry_extras
            else UNKNOWN
        )

    if site.class_descriptor == "Landroid/net/Uri;" and site.method == "getQueryParameter":
        # M1：只有“从入口 Intent 数据 / 攻击者可控字符串派生出的 Uri”才算深链参数。
        # 本地常量 Uri（例如 `Uri.parse("https://safe/?next=x")`）不再是攻击者可控。
        if receiver_tag is not None and receiver_tag.attacker_controlled:
            # `owner` 记 Uri 的来源载体：`data`（getData）/ `extra`（extra 字符串
            # 派生）/ 已派生的 DEEPLINK_PARAM 沿用原来源。跨组件 join 用它区分
            # “读的是 Intent data”还是“读的是 extra 里的 URL”。
            origin = "data" if receiver_tag.kind is TagKind.INTENT_DATA else "extra"
            if receiver_tag.kind is TagKind.DEEPLINK_PARAM and receiver_tag.owner:
                origin = receiver_tag.owner
            return Tag(
                TagKind.DEEPLINK_PARAM,
                value=_arg_const(site, tags),
                owner=origin,
            )
        return UNKNOWN

    # 规则 6（T3.6 补）：**派生调用**——返回值仍由 receiver / 实参派生。
    # `getIntent().getData().toString()` 是真实现象（M2 `extract/webview.py` 用
    # `DERIVATION_METHODS` 处理过同类写法）；标签不传下去，J5 会把
    # `deeplink → loadUrl` 整条链漏掉（9 case 的 01/04/05/06/07 全军覆没）。
    derived = _derive_from_receiver(site, tags)
    if derived is None:
        derived = _derive_from_args(site, tags)

    # 规则 3：invoke 之后紧跟 move-result-object → call_result
    if smali is None:
        return derived if derived is not None else Tag(TagKind.CALL_RESULT, value=site.ref)

    # 跨方法：只跟进一层，且目标方法体 ≤ 80 条指令
    if depth >= MAX_CROSS_METHOD_DEPTH:
        return derived if derived is not None else Tag(TagKind.UNKNOWN, value=site.ref, incomplete=True)
    callee = smali.find_method(site.ref)
    if callee is None:
        # 框架方法 / 未解析：到此为止，不算不完整；receiver 派生要传下去
        return derived if derived is not None else Tag(TagKind.CALL_RESULT, value=site.ref)
    if len(callee.instructions) > MAX_CROSS_METHOD_INSTRUCTIONS:
        return Tag(TagKind.UNKNOWN, value=site.ref, incomplete=True)

    # M1：过程间参数污点——把调用点实参的标签映射到 callee 形参。
    nested = propagate(
        callee,
        smali=smali,
        depth=depth + 1,
        initial=_param_tags_for(site, tags, callee),
    )
    value = return_tag(callee, nested.tags)
    return Tag(value.kind, value=value.value, owner=value.owner, incomplete=nested.incomplete)


def _derive_from_receiver(site: InvokeSite, tags: dict[str, Tag]) -> Tag | None:
    """receiver 是 attacker-controlled → 返回值继承它的标签；否则 None。

    只对**实例方法**生效：`invoke-static` 的 `args[0]` 是第一个实参而不是 receiver，
    顺着它传播会把 `Log.d(attacker, "tag")` 的返回值误标成可控。
    """
    if site.opcode.startswith("invoke-static"):
        return None
    receiver = site.receiver
    if receiver is None:
        return None
    tag = tags.get(receiver)
    if tag is None or not tag.attacker_controlled:
        return None
    return Tag(tag.kind, value=tag.value, owner=tag.owner)


def _is_entry_intent(tag: Tag | None) -> bool:
    """寄存器是否持有**入口** Intent（`getIntent()` 或其克隆）。"""
    return (
        tag is not None
        and tag.kind is TagKind.INTENT_OBJECT
        and tag.value == INTENT_ENTRY
    )


def _is_entry_extras(tag: Tag | None) -> bool:
    """寄存器是否持有入口 Intent 的 `Bundle`（`getExtras()`）。"""
    return (
        tag is not None
        and tag.kind is TagKind.INTENT_EXTRAS
        and tag.value == INTENT_ENTRY
    )


def _derive_from_args(site: InvokeSite, tags: dict[str, Tag]) -> Tag | None:
    """实参带污点 → 返回值继承（`Uri.parse` / `String.format` / `StringBuilder.append`）。

    M1 之前静态调用（`Uri.parse`）与“receiver 干净、实参脏”（`format(tainted)`）
    都会退化成 `call_result`，导致 `setData(Uri.parse(tainted))`、字符串拼接等
    常见写法整类漏报。
    """
    pair = (site.class_descriptor, site.method)
    if site.opcode.startswith("invoke-static"):
        if pair not in _STATIC_DERIVATIONS:
            return None
        candidates = site.args
    else:
        if pair not in _INSTANCE_DERIVATIONS:
            return None
        candidates = site.value_args
    for register in candidates:
        tag = tags.get(register)
        if tag is not None and tag.attacker_controlled:
            return Tag(tag.kind, value=tag.value, owner=tag.owner)
    return None


def param_registers(method: MethodInfo) -> list[str]:
    """方法形参对应的寄存器名（`p1..` / 静态方法 `p0..`）。

    口径：apktool 产物使用 `.locals` 时，形参固定落在 `pN`；`p0` 是实例方法的
    `this`。这里不处理 `.registers` 的 v 寄存器别名——那是已知限制。
    """
    params = param_types(method.signature)
    offset = 0 if "static" in method.access else 1
    return [f"p{offset + index}" for index in range(len(params))]


def _default_param_tags(method: MethodInfo) -> dict[str, Tag]:
    """单方法回放时的形参默认标签（§6.1 口径）。

    - `Intent` 形参按入口 Intent 处理（`fromIntentExtra` 这类 fixture / 单测）；
    - `Uri` 形参按入口深链做处理（`fromDeeplinkParam`）。

    过程间分析（`_chains_from_entry` / `_tag_for_call`）会显式传入 `initial`，
    **覆盖**这份默认值，因此不会把“调用方传了本地常量”误判成攻击者可控。
    """
    tags: dict[str, Tag] = {}
    for register, type_ in zip(param_registers(method), param_types(method.signature)):
        if type_ == "Landroid/content/Intent;":
            tags[register] = Tag(TagKind.INTENT_OBJECT, value=INTENT_ENTRY)
        elif type_ == "Landroid/net/Uri;":
            tags[register] = Tag(TagKind.INTENT_DATA)
    return tags


def param_tags_for(
    site: InvokeSite, tags: dict[str, Tag], callee: MethodInfo
) -> dict[str, Tag]:
    """把调用点实参标签映射到 callee 形参（一层过程间污点，外部可复用）。

    `chains` 沿调用路径逐跳调用它，保证 callee 的形参标签来自真实调用点，
    而不是“Intent 形参一律入口 Intent”的保守默认。
    """
    return _param_tags_for(site, tags, callee)


def _param_tags_for(
    site: InvokeSite, tags: dict[str, Tag], callee: MethodInfo
) -> dict[str, Tag]:
    """把调用点实参标签映射到 callee 形参（一层过程间污点）。"""
    arguments = site.args if site.opcode.startswith("invoke-static") else site.value_args
    initial: dict[str, Tag] = {}
    if "static" not in callee.access:
        initial["p0"] = UNKNOWN
    for register, argument in zip(param_registers(callee), arguments):
        initial[register] = tags.get(argument, UNKNOWN)
    return initial


def _apply_intent_constructor(site: InvokeSite, tags: dict[str, Tag]) -> None:
    """`new Intent(entryIntent)` 克隆：新对象仍是入口 Intent 的标签。"""
    if site.class_descriptor != "Landroid/content/Intent;" or site.receiver is None:
        return
    if param_types(site.signature) != ["Landroid/content/Intent;"] or not site.value_args:
        return
    source = tags.get(site.value_args[0])
    if source is not None and source.kind is TagKind.INTENT_OBJECT:
        tags[site.receiver] = Tag(TagKind.INTENT_OBJECT, value=source.value)


def _arg_const(site: InvokeSite, tags: dict[str, Tag]) -> str:
    """取第一个实参的常量字符串作为键名；不是常量 → 空串（不猜）。"""
    if not site.value_args:
        return ""
    tag = tags.get(site.value_args[0])
    if tag is None or tag.kind is not TagKind.CONST:
        return ""
    return tag.value


def _result_after(method: MethodInfo, site_index: int) -> tuple[int, str] | None:
    """`site_index` 之后紧跟的 `move-result*` → `(指令下标, 目标寄存器)`。"""
    for offset in (1, 2):
        position = site_index + offset
        if position >= len(method.instructions):
            break
        instruction = method.instructions[position]
        register = result_register(instruction)
        if register:
            return position, register
        if instruction.opcode.startswith(("invoke-", "const")):
            break
    return None


def _parse_field(instruction: Instruction) -> tuple[str, str, str] | None:
    """`iget-object v0, v1, Lcom/x;->f:T` → `(v0, Lcom/x;, f)`。"""
    if not instruction.opcode.startswith(("iget", "sget")):
        return None
    parts = [part.strip() for part in instruction.operands_raw.split(",")]
    if len(parts) < 2:
        return None
    reference = parts[-1]
    arrow = reference.find("->")
    if arrow < 0:
        return None
    owner = reference[:arrow]
    remainder = reference[arrow + 2 :]
    name = remainder.split(":", 1)[0]
    return parts[0], owner, name


# --- 指令解析（M2 的既有能力，行为未改） ---------------------------------


def parse_invoke(instruction: Instruction) -> InvokeSite | None:
    """解析 `invoke-* {regs}, Lcls;->method(sig)ret`；非 invoke 返回 None。"""
    if not instruction.opcode.startswith("invoke-"):
        return None
    registers_text, separator, target = instruction.operands_raw.partition("},")
    if not separator:
        return None
    args = _parse_registers(registers_text.strip().removeprefix("{").removesuffix("}"))
    target = target.strip()
    arrow = target.find("->")
    if arrow < 0:
        return None
    class_descriptor = target[:arrow]
    remainder = target[arrow + 2 :]
    paren = remainder.find("(")
    if paren < 0:
        return None
    return InvokeSite(
        index=instruction.index,
        opcode=instruction.opcode,
        class_descriptor=class_descriptor,
        method=remainder[:paren],
        signature=remainder[paren:],
        args=args,
    )


def parse_const_string(instruction: Instruction) -> tuple[str, str] | None:
    """`const-string v0, "text"` → `(寄存器, 文本)`。"""
    if not instruction.opcode.startswith("const-string"):
        return None
    register, separator, rest = instruction.operands_raw.partition(",")
    if not separator:
        return None
    text = rest.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return register.strip(), text


def parse_const_number(instruction: Instruction) -> tuple[str, int] | None:
    """`const/4 v0, 0x1` → `(寄存器, 1)`；只认能解析出整数的常量。"""
    if not instruction.opcode.startswith("const"):
        return None
    register, separator, rest = instruction.operands_raw.partition(",")
    if not separator:
        return None
    raw = rest.strip().lower()
    try:
        return register.strip(), int(raw.removeprefix("0x"), 16) if "-" not in raw else int(raw, 0)
    except ValueError:
        return None


def parse_new_instance(instruction: Instruction) -> tuple[str, str] | None:
    """`new-instance v0, Lcom/x;` → `(寄存器, 描述符)`。"""
    if instruction.opcode != "new-instance":
        return None
    register, separator, rest = instruction.operands_raw.partition(",")
    if not separator:
        return None
    return register.strip(), rest.strip()


def result_register(instruction: Instruction) -> str | None:
    """`move-result-object v0` → `v0`；非 move-result 返回 None。"""
    if instruction.opcode.startswith("move-result"):
        return instruction.operands_raw.strip() or None
    return None


# --- 单步回溯（M2 的既有能力，行为未改） ---------------------------------


def backtrack_definition(method: MethodInfo, index: int, register: str) -> Instruction | None:
    """向前找**最近一次**写入该寄存器的指令（不跨方法）。"""
    for instruction in reversed(method.instructions[:index]):
        if _defines(instruction, register):
            return instruction
    return None


def backtrack_const_string(method: MethodInfo, index: int, register: str) -> tuple[str, str] | None:
    """寄存器是否由 `const-string` 直接赋值。"""
    instruction = backtrack_definition(method, index, register)
    if instruction is None:
        return None
    return parse_const_string(instruction)


def backtrack_const_number(method: MethodInfo, index: int, register: str) -> int | None:
    """寄存器是否由整数常量赋值（`const/4` 等）。取不到返回 None，不猜（D-016）。"""
    instruction = backtrack_definition(method, index, register)
    if instruction is None:
        return None
    parsed = parse_const_number(instruction)
    return parsed[1] if parsed else None


def backtrack_new_instance(method: MethodInfo, index: int, register: str) -> str | None:
    """寄存器是否由 `new-instance` 赋值 → 返回类描述符。"""
    instruction = backtrack_definition(method, index, register)
    if instruction is None:
        return None
    parsed = parse_new_instance(instruction)
    return parsed[1] if parsed else None


def result_of_call(method: MethodInfo, index: int) -> str | None:
    """`index` 处调用之后紧跟的 `move-result*` 的目标寄存器。"""
    for instruction in method.instructions[index + 1 : index + 3]:
        register = result_register(instruction)
        if register:
            return register
        if instruction.opcode.startswith("invoke-") or instruction.opcode.startswith("const"):
            break
    return None


def invoke_before(method: MethodInfo, index: int) -> InvokeSite | None:
    """`index` 之前最近的一条 `invoke-*`（用于从 move-result 反推来源调用）。"""
    for instruction in reversed(method.instructions[:index]):
        parsed = parse_invoke(instruction)
        if parsed is not None:
            return parsed
    return None


def param_types(signature: str) -> list[str]:
    """`(Ljava/lang/String;I)V` → `["Ljava/lang/String;", "I"]`。"""
    start = signature.find("(")
    end = signature.find(")")
    if start < 0 or end < 0:
        return []
    types: list[str] = []
    index = start + 1
    while index < end:
        char = signature[index]
        if char == "[":
            cursor = index
            while cursor < end and signature[cursor] == "[":
                cursor += 1
            if cursor < end and signature[cursor] == "L":
                semicolon = signature.find(";", cursor)
                if semicolon < 0 or semicolon >= end:
                    break
                types.append(signature[index : semicolon + 1])
                index = semicolon + 1
            else:
                types.append(signature[index : cursor + 1])
                index = cursor + 1
        elif char == "L":
            semicolon = signature.find(";", index)
            if semicolon < 0 or semicolon >= end:
                break
            types.append(signature[index : semicolon + 1])
            index = semicolon + 1
        else:
            types.append(char)
            index += 1
    return types


#: 支配分析的分块上限；超过就不做（返回 `None`，调用方退回线性结果）。
MAX_DOMINANCE_BLOCKS = 1500


def dominating_constant(method: MethodInfo, index: int, register: str) -> str | None:
    """`index` 处读取 `register` 的常量字符串，且该定义**真的到达**这次读取。

    线性扫描会按文本顺序取“最后一次定义”，把别的分支里的重定义也算进来。
    OVAA 的 `processDeeplink` 就是典型：入口处 `v2 = "url"`，grant 分支里复用
    `v2` 放别的字符串，但该分支 `goto` 去了别处，到不了 `/webview` 分支里的
    `putExtra`。这里按基本块做到达定义（reaching definitions）：

    - 只有唯一一个到达定义、且是 `const-string`（或经 `move-object` 转手）才返回；
    - 多条到达定义取值相同 → 返回该值；
    - 否则返回 `None`（不猜）。
    """
    if not 0 < index < len(method.instructions):
        return None
    return _constant_from_reaching(method, index, register, depth=0)


def _constant_from_reaching(
    method: MethodInfo, index: int, register: str, *, depth: int
) -> str | None:
    definitions = _reaching_definitions(method, index, register)
    if not definitions:
        return None
    values: set[str] = set()
    for definition in definitions:
        instruction = method.instructions[definition]
        const = parse_const_string(instruction)
        if const is not None and const[0] == register:
            values.add(const[1])
            continue
        if instruction.opcode.startswith("move-object"):
            source = instruction.operands_raw.partition(",")[2].strip()
            if not source or depth >= 3:
                return None
            value = _constant_from_reaching(method, index, source, depth=depth + 1)
            if value is None:
                return None
            values.add(value)
            continue
        return None
    return values.pop() if len(values) == 1 else None


def _reaching_definitions(
    method: MethodInfo, use_index: int, register: str
) -> tuple[int, ...]:
    """到达 `use_index` 处 `register` 读取的定义指令下标（控制流感知）。"""
    cfg = _build_cfg(method)
    if cfg is None:
        return ()
    blocks, successors, block_of = cfg
    # 每个块里该寄存器的定义；只有块内最后一个定义能流到块外。
    defs_by_block: list[list[int]] = []
    for start, end in blocks:
        defs_by_block.append(
            [i for i in range(start, end) if _defines(method.instructions[i], register)]
        )

    predecessors: list[list[int]] = [[] for _ in blocks]
    for block, targets in enumerate(successors):
        for target in targets:
            predecessors[target].append(block)

    incoming: list[frozenset[int]] = [frozenset() for _ in blocks]
    outgoing: list[frozenset[int]] = [frozenset() for _ in blocks]
    pending = list(range(len(blocks)))
    queued = [True] * len(blocks)
    while pending:
        block = pending.pop()
        queued[block] = False
        if block == 0:
            new_in: frozenset[int] = frozenset()
        else:
            merged: set[int] = set()
            for predecessor in predecessors[block]:
                merged.update(outgoing[predecessor])
            new_in = frozenset(merged)
        definitions = defs_by_block[block]
        new_out = (new_in - set(definitions)) | ({definitions[-1]} if definitions else set())
        if new_in != incoming[block] or frozenset(new_out) != outgoing[block]:
            incoming[block] = new_in
            outgoing[block] = frozenset(new_out)
            for target in successors[block]:
                if not queued[target]:
                    queued[target] = True
                    pending.append(target)

    block = block_of[use_index]
    definitions = defs_by_block[block]
    reaching = set(incoming[block]) - set(definitions)
    before = [definition for definition in definitions if definition < use_index]
    if before:
        # 块内线性执行：只有最后一个定义能活到 use。
        reaching.add(max(before))
    return tuple(sorted(reaching))


def _build_cfg(
    method: MethodInfo,
) -> tuple[list[tuple[int, int]], list[tuple[int, ...]], list[int]] | None:
    """指令级基本块：`([(start, end)], successors, block_of)`；不支持则 `None`。"""
    instructions = method.instructions
    total = len(instructions)
    if not total:
        return None
    labels: dict[str, int] = {}
    for position, instruction in enumerate(instructions):
        if instruction.opcode.startswith(":"):
            labels.setdefault(instruction.opcode.strip(), position)

    leaders = {0}
    targets: dict[int, int] = {}
    for position, instruction in enumerate(instructions):
        opcode = instruction.opcode
        if opcode.startswith(("packed-switch", "sparse-switch")):
            return None
        if opcode.startswith(":"):
            leaders.add(position)
        if _ends_block(opcode) and position + 1 < total:
            leaders.add(position + 1)
        target = _branch_target(instruction)
        if target is not None:
            resolved = labels.get(target)
            if resolved is None:
                return None
            targets[position] = resolved
            leaders.add(resolved)

    starts = sorted(leaders)
    if len(starts) > MAX_DOMINANCE_BLOCKS:
        return None
    blocks = [
        (start, starts[position + 1] if position + 1 < len(starts) else total)
        for position, start in enumerate(starts)
    ]
    block_of = [0] * total
    for block, (start, end) in enumerate(blocks):
        for position in range(start, end):
            block_of[position] = block

    successors: list[tuple[int, ...]] = []
    for block, (start, end) in enumerate(blocks):
        last = end - 1
        opcode = instructions[last].opcode
        following = (block + 1,) if block + 1 < len(blocks) else ()
        if opcode.startswith("goto"):
            successors.append((block_of[targets[last]],))
        elif opcode.startswith("if-"):
            successors.append((block_of[targets[last]],) + following)
        elif opcode.startswith(("return", "throw")):
            successors.append(())
        else:
            successors.append(following)
    return blocks, successors, block_of


def _ends_block(opcode: str) -> bool:
    return opcode.startswith(("goto", "if-", "return", "throw"))


def _branch_target(instruction: Instruction) -> str | None:
    opcode = instruction.opcode
    if opcode.startswith("goto"):
        return instruction.operands_raw.strip() or None
    if opcode.startswith("if-"):
        parts = [part.strip() for part in instruction.operands_raw.split(",")]
        return parts[-1] if parts else None
    return None


def _defines(instruction: Instruction, register: str) -> bool:
    """该指令是否把结果写进 `register`。"""
    if instruction.opcode.startswith("move-result"):
        return result_register(instruction) == register
    if not instruction.opcode.startswith(DEFINING_PREFIXES):
        return False
    return _target_register(instruction) == register


def _target_register(instruction: Instruction) -> str:
    """指令写入的目标寄存器（`v0, ...` 的第一个）。"""
    return instruction.operands_raw.partition(",")[0].strip()


def _parse_registers(text: str) -> tuple[str, ...]:
    """`{v0, v1}` / `{v0 .. v3}` → `("v0", "v1", ...)`。"""
    items = [item.strip() for item in text.replace("{", "").replace("}", "").split(",") if item.strip()]
    registers: list[str] = []
    for item in items:
        if ".." in item:
            start, _, end = item.partition("..")
            registers.extend(_expand(start.strip(), end.strip()))
        else:
            registers.append(item)
    return tuple(registers)


def _expand(start: str, end: str) -> list[str]:
    """展开 `v0 .. v3`（同一前缀，按数字递增）。"""
    prefix_start = _prefix(start)
    prefix_end = _prefix(end)
    if prefix_start != prefix_end:
        return [start, end]
    try:
        first, last = int(start[len(prefix_start) :]), int(end[len(prefix_end) :])
    except ValueError:
        return [start, end]
    return [f"{prefix_start}{value}" for value in range(first, last + 1)]


def _prefix(register: str) -> str:
    """寄存器名前缀：`v3` → `v`，`p1` → `p`。"""
    return register[:1]


__all__ = [
    "ATTACKER_CONTROLLED",
    "DEFINING_PREFIXES",
    "INTENT_ENTRY",
    "INTENT_LOCAL",
    "MAX_BACKTRACK_STEPS",
    "MAX_CROSS_METHOD_DEPTH",
    "MAX_CROSS_METHOD_INSTRUCTIONS",
    "UNKNOWN",
    "FlowResult",
    "InvokeSite",
    "Tag",
    "TagKind",
    "backtrack_const_number",
    "backtrack_const_string",
    "backtrack_definition",
    "backtrack_new_instance",
    "dominating_constant",
    "invoke_before",
    "param_registers",
    "param_tags_for",
    "param_types",
    "parse_const_number",
    "parse_const_string",
    "parse_invoke",
    "parse_new_instance",
    "propagate",
    "result_of_call",
    "result_register",
    "return_tag",
    "tag_at",
]
