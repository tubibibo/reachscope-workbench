"""Smali 行级解析与索引（PLAN §5.3 / TASKS T1.3）。

**不是**完整 smali 语法解析器：逐行扫描，只求“稳定拿到 opcode + 操作数文本”。
支持多 dex 合并（类名冲突保留第一个并记 warning）、未知语法跳过计数（§9.2）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..ir.model import SourceLoc
from .apk import smali_dirs

logger = logging.getLogger("reachscope.ingest.smali")

#: 方法体内可安全跳过的已知伪指令（不算“未知语法”）。
KNOWN_METHOD_DIRECTIVES = {
    ".param",
    ".local",
    ".restart",
    ".end-local",
    ".prologue",
    ".epilogue",
    # 异常处理（真实 APK 里大量出现，见 D-055）
    ".catch",
    ".catchall",
    ".packed-switch",
    ".end-packed-switch",
    ".sparse-switch",
    ".end-sparse-switch",
    ".array-data",
    ".end-array-data",
}

#: 类层级可安全跳过的已知伪指令。
KNOWN_CLASS_DIRECTIVES = {".source", ".field", ".enum"}

#: `.end <子块>` 形式的块结束伪指令（真实 smali 用**空格**而不是连字符，D-055）。
KNOWN_END_BLOCKS = {"packed-switch", "sparse-switch", "array-data", "field"}

#: 反引号/字符串中的 `#` 不算注释起点。
_QUOTE_CHARS = ("'", '"')


@dataclass(frozen=True, slots=True)
class Instruction:
    """一条 smali 指令。

    `line` 是 `.line N` 对应的 Java 源码行号（0 = 未标注），
    `file_line` 是 smali 文件的物理行号（T2.4 要拿“注册点 file:line”，D-028）。
    """

    index: int
    opcode: str
    operands_raw: str
    line: int
    file_line: int


@dataclass(frozen=True)
class AnnotationInfo:
    """一个 `.annotation` 块的骨架信息。"""

    visibility: str
    type: str
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class MethodInfo:
    """一个方法（`.method` 到 `.end method`）。"""

    name: str
    signature: str
    registers: int
    access: tuple[str, ...] = ()
    instructions: tuple[Instruction, ...] = ()
    annotations: tuple[AnnotationInfo, ...] = ()
    source: SourceLoc = field(default_factory=SourceLoc)

    @property
    def name_with_signature(self) -> str:
        """`name(sig)ret`。"""
        return f"{self.name}{self.signature}"

    def has_annotation(self, type_: str) -> bool:
        """是否带指定类型的注解（如 `Landroid/webkit/JavascriptInterface;`）。"""
        return any(annotation.type == type_ for annotation in self.annotations)


@dataclass(frozen=True)
class ClassInfo:
    """一个 smali 类文件。"""

    descriptor: str
    super_name: str
    interfaces: tuple[str, ...] = ()
    access: tuple[str, ...] = ()
    methods: tuple[MethodInfo, ...] = ()
    annotations: tuple[AnnotationInfo, ...] = ()
    source: SourceLoc = field(default_factory=SourceLoc)

    def method(self, name_with_signature: str) -> MethodInfo | None:
        """按 `name(sig)ret` 找方法。"""
        for method in self.methods:
            if method.name_with_signature == name_with_signature:
                return method
        return None

    @property
    def is_interface(self) -> bool:
        """`.class ... interface ...`。"""
        return "interface" in self.access

    @property
    def is_abstract(self) -> bool:
        """`.class ... abstract ...` 或含 abstract 方法且无实现。"""
        return "abstract" in self.access


@dataclass
class SmaliIndex:
    """整个 APK 的 smali 索引（多 dex 合并后）。"""

    class_by_descriptor: dict[str, ClassInfo] = field(default_factory=dict)
    method_index: dict[str, MethodInfo] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def class_count(self) -> int:
        return len(self.class_by_descriptor)

    @property
    def method_count(self) -> int:
        return len(self.method_index)

    def get_class(self, descriptor: str) -> ClassInfo | None:
        """按描述符取类。"""
        return self.class_by_descriptor.get(descriptor)

    def find_method(self, ref: str) -> MethodInfo | None:
        """按 `Lcls;->name(sig)ret` 找方法。"""
        return self.method_index.get(ref)


def build_index(workdir: str | Path) -> SmaliIndex:
    """扫描 workdir 下所有 `smali*/` 目录，构建合并索引。"""
    index = SmaliIndex()
    root = Path(workdir)
    for dex_dir in smali_dirs(root):
        for path in sorted(dex_dir.rglob("*.smali")):
            index_smali_file(index, path, base_dir=root)
    return index


def index_smali_file(index: SmaliIndex, path: str | Path, base_dir: str | Path | None = None) -> None:
    """解析一个 .smali 文件并合并进索引（冲突保留先注册者）。"""
    file_path = Path(path)
    rel = _relative(file_path, base_dir)
    classes, warnings, unknown_count = parse_smali_file(file_path, base_dir=base_dir)

    for class_info in classes:
        existing = index.class_by_descriptor.get(class_info.descriptor)
        if existing is not None:
            message = (
                f"smali 索引：类名冲突 {class_info.descriptor}"
                f"（保留 {existing.source.file}，忽略 {class_info.source.file}）"
            )
            logger.warning(message)
            index.warnings.append(message)
            continue
        index.class_by_descriptor[class_info.descriptor] = class_info
        for method in class_info.methods:
            index.method_index[method_key(class_info.descriptor, method)] = method

    if warnings:
        index.warnings.extend(warnings)
    if unknown_count:
        index.warnings.append(f"{rel}：跳过 {unknown_count} 行未知语法")


def parse_smali_file(
    path: str | Path, base_dir: str | Path | None = None
) -> tuple[list[ClassInfo], list[str], int]:
    """解析单个 smali 文件。

    返回 `(classes, warnings, unknown_syntax_count)`；未知语法不中断（§9.2）。

    `base_dir` 是解码根目录：所有 `SourceLoc.file` 都记**相对它的 posix 路径**
    （如 `smali/com/example/app/MainActivity.smali`），绝对路径会破坏 §9.3 确定性
    并让 T5.1 golden 漂移（D-036）。
    """
    file_path = Path(path)
    display = _relative(file_path, base_dir)
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"smali 解析失败 {display}：{exc}"], 0

    classes: list[ClassInfo] = []
    warnings: list[str] = []
    unknown = 0

    current_class = _ClassBuilder(display)
    current_method: _MethodBuilder | None = None
    annotation: _AnnotationBuilder | None = None
    java_line = 0

    for file_line, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw).strip()
        if not stripped:
            continue

        # 注解块内的行都是值，直到 .end annotation（含 .subannotation 等嵌套行）。
        if annotation is not None:
            if stripped == ".end annotation":
                finished = annotation.finish()
                if annotation.owner_method is not None and current_method is not None:
                    current_method.annotations.append(finished)
                elif current_class.descriptor:
                    current_class.annotations.append(finished)
                annotation = None
            else:
                annotation.values.append(stripped)
            continue

        if stripped.startswith("."):
            parts = stripped.split()
            directive = parts[0]
            if directive == ".class":
                current_class.set_header(parts[1:], file_line, stripped)
            elif directive == ".super":
                current_class.super_name = parts[1] if len(parts) > 1 else ""
            elif directive == ".implements":
                if len(parts) > 1:
                    current_class.interfaces.append(parts[1])
            elif directive == ".method":
                current_method = _MethodBuilder(display, file_line, parts[1:], stripped)
                java_line = 0
            elif directive == ".end" and len(parts) > 1 and parts[1] == "method":
                if current_method is None:
                    unknown += 1
                    continue
                current_class.methods.append(current_method.finish())
                current_method = None
            elif directive == ".end" and len(parts) > 1 and parts[1] in KNOWN_END_BLOCKS:
                # `.end packed-switch` / `.end field` …：块结束，静默跳过（D-055）。
                pass
            elif directive == ".line":
                java_line = int(parts[1]) if len(parts) > 1 else 0
            elif directive == ".registers":
                if current_method is not None and len(parts) > 1:
                    current_method.declared_registers = int(parts[1])
            elif directive == ".locals":
                if current_method is not None and len(parts) > 1:
                    current_method.locals = int(parts[1])
            elif directive == ".annotation":
                visibility = parts[1] if len(parts) > 1 else ""
                type_ = parts[2] if len(parts) > 2 else ""
                annotation = _AnnotationBuilder(visibility, type_, owner_method=current_method)
            elif directive in KNOWN_METHOD_DIRECTIVES or directive in KNOWN_CLASS_DIRECTIVES:
                pass
            else:
                unknown += 1
                logger.debug("未知伪指令 %s:%d：%s", file_path, file_line, stripped)
            continue

        # 非伪指令行：方法体内是指令，方法体外是异常布局。
        if current_method is not None:
            current_method.add_instruction(stripped, java_line, file_line)
        elif current_class.descriptor:
            unknown += 1
            logger.debug("方法体外的指令行 %s:%d：%s", file_path, file_line, stripped)

    if current_method is not None:
        warnings.append(f"{display}：方法未闭合（.end method 缺失），已按截断处理")
        current_class.methods.append(current_method.finish())
    if current_class.descriptor:
        classes.append(current_class.build())
    return classes, warnings, unknown


def method_key(descriptor: str, method: MethodInfo) -> str:
    """`method_index` 的键：`Lcls;->name(sig)ret`。"""
    return f"{descriptor}->{method.name_with_signature}"


def param_register_count(params_descriptor: str, is_static: bool) -> int:
    """按参数描述符算寄存器数：`J`/`D` 占 2，其余占 1；非静态再加 `this`。"""
    total = 0 if is_static else 1
    index = 0
    while index < len(params_descriptor):
        char = params_descriptor[index]
        if char == "[":
            while index < len(params_descriptor) and params_descriptor[index] == "[":
                index += 1
            if index < len(params_descriptor) and params_descriptor[index] == "L":
                while index < len(params_descriptor) and params_descriptor[index] != ";":
                    index += 1
                index += 1
            elif index < len(params_descriptor):
                index += 1
            total += 1  # 数组是引用，恒占 1
        elif char == "L":
            while index < len(params_descriptor) and params_descriptor[index] != ";":
                index += 1
            index += 1
            total += 1
        elif char in "JD":
            total += 2
            index += 1
        else:
            total += 1
            index += 1
    return total


# --- 内部构建器 -----------------------------------------------------------


class _ClassBuilder:
    """`.class` 声明的累加器。"""

    def __init__(self, display: str) -> None:
        self.display = display
        self.descriptor = ""
        self.super_name = ""
        self.access: list[str] = []
        self.interfaces: list[str] = []
        self.methods: list[MethodInfo] = []
        self.annotations: list[AnnotationInfo] = []
        self.header_line = 0
        self.header_snippet = ""

    def set_header(self, tokens: list[str], file_line: int, snippet: str) -> None:
        """解析 `.class <flags> <descriptor>`。"""
        if not tokens:
            return
        self.descriptor = tokens[-1]
        self.access = tokens[:-1]
        self.header_line = file_line
        self.header_snippet = snippet

    def build(self) -> ClassInfo:
        """生成不可变的 `ClassInfo`。"""
        return ClassInfo(
            descriptor=self.descriptor,
            super_name=self.super_name,
            interfaces=tuple(self.interfaces),
            access=tuple(self.access),
            methods=tuple(self.methods),
            annotations=tuple(self.annotations),
            source=SourceLoc(
                file=self.display, line=self.header_line, snippet=self.header_snippet
            ),
        )


class _MethodBuilder:
    """`.method` 声明的累加器。"""

    def __init__(self, display: str, file_line: int, tokens: list[str], snippet: str) -> None:
        self.display = display
        self.header_line = file_line
        self.header_snippet = snippet
        self.access: list[str] = tokens[:-1] if len(tokens) > 1 else []
        name_with_signature = tokens[-1] if tokens else ""
        paren = name_with_signature.find("(")
        if paren >= 0:
            self.name = name_with_signature[:paren]
            self.signature = name_with_signature[paren:]
        else:
            self.name = name_with_signature
            self.signature = ""
        self.declared_registers: int | None = None
        self.locals: int | None = None
        self.annotations: list[AnnotationInfo] = []
        self.instructions: list[Instruction] = []

    def add_instruction(self, stripped: str, java_line: int, file_line: int) -> None:
        """记录一条指令行，拆出 opcode 与操作数原文。"""
        opcode, _, operands = stripped.partition(" ")
        self.instructions.append(
            Instruction(
                index=len(self.instructions),
                opcode=opcode,
                operands_raw=operands.strip(),
                line=java_line,
                file_line=file_line,
            )
        )

    def finish(self) -> MethodInfo:
        """生成不可变的 `MethodInfo`，必要时用 `.locals` 推导寄存器数。"""
        registers = self.declared_registers or 0
        if self.declared_registers is None and self.locals is not None:
            registers = self.locals + param_register_count(
                _params_of(self.signature), is_static=("static" in self.access)
            )
        return MethodInfo(
            name=self.name,
            signature=self.signature,
            registers=registers,
            access=tuple(self.access),
            instructions=tuple(self.instructions),
            annotations=tuple(self.annotations),
            source=SourceLoc(
                file=self.display, line=self.header_line, snippet=self.header_snippet
            ),
        )


class _AnnotationBuilder:
    """`.annotation` 块的累加器。"""

    def __init__(
        self, visibility: str, type_: str, owner_method: _MethodBuilder | None
    ) -> None:
        self.visibility = visibility
        self.type = type_
        self.values: list[str] = []
        self.owner_method = owner_method

    def finish(self) -> AnnotationInfo:
        """生成不可变的 `AnnotationInfo`。"""
        return AnnotationInfo(
            visibility=self.visibility, type=self.type, values=tuple(self.values)
        )


def _params_of(signature: str) -> str:
    """取签名中的参数描述符（括号内）。"""
    start = signature.find("(")
    if start < 0:
        return ""
    end = signature.find(")", start)
    return signature[start + 1 : end if end > 0 else len(signature)]


def _strip_comment(raw: str) -> str:
    """去掉行注释：`#` 前有空白才视为注释起点，字符串里的 `#` 保留。

    绝大多数行没有 `#`，先走一次 `in` 判断的**快速路径**：否则对上千万行做逐字符
    扫描会让 `build_index` 慢一个数量级（真实 APK 实测，见 PROGRESS 的 M2 收尾）。
    """
    if "#" not in raw:
        return raw
    quote: str | None = None
    for index, char in enumerate(raw):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in _QUOTE_CHARS:
            quote = char
        elif char == "#" and (index == 0 or raw[index - 1].isspace()):
            return raw[:index]
    return raw


def _relative(file_path: Path, base_dir: str | Path | None) -> str:
    """`SourceLoc.file` 与日志用的相对 posix 路径（§9.3 确定性，D-036）。"""
    if base_dir is None:
        return file_path.name
    try:
        return file_path.relative_to(Path(base_dir)).as_posix()
    except ValueError:
        return file_path.name
