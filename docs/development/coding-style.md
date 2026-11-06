# 工程与日志约定

> 本文档约束**所有**源代码与测试。违反其中任一条意味着改 PR 会被退回。
> §9.2 是规则的源头；本文档是它在工程实践中的具体落地。

## 1. 日志级别

| 级别 | 何时使用 | 例子 |
|---|---|---|
| `ERROR` | **不可继续**（后续流程跑不了） | manifest 解析失败、保护检测强加固、apktool 调用返回非 0 |
| `WARNING` | **降级但继续**（分析结果可能不完整） | 跳过未知语法行、桥 obj 寄存器回溯不到 new-instance、apkid 不可用、apktool 版本不可读 |
| `INFO` | 流程节点（不是状态） | 进入哪一步、用了哪个 apktool、target_sdk 取自 manifest 还是 apktool.yml |
| `DEBUG` | 逐文件 / 逐指令的细节 | 单个 smali 的解析器命中、apkid 返回值结构 |

**禁止**：

- 改用 `print()`：stdout 只属于 CLI（`-q` 抑制 INFO 时也只剩 `ERROR`）。
- 把 `logger.warning` 当成“记得告诉用户”的工具：所有 `WARNING` 级别的事件**必须**同时进 `Meta.warnings`（或 `ManifestInfo.warnings` / `SmaliIndex.warnings` 等本模块的 warnings 列表），这样报告里能看见、CLI `--quiet` 之外也有输出。`logger.warning` 只是双写。
- 把 `ERROR` 当成“注意一下”的级别：ERROR 等于“退出码非 0 + 阻止后续报告生成”。
- 在 INFO 级别写**逐行/逐文件**细节：日志量会爆。

## 2. 错误约定

- **退出码**：`reachscope.exitcodes.ExitCode`，禁止硬编码整数。
- **`IngestError` / `IRDeserializeError` 等结构化错误**：带 `reason`（英文规范值）+ `detail`（中文或英文自然语言）+ 必要时的 `exit_code`。**只让 CLI 做用户面翻译**，库代码不要碰 `sys.exit`。
- **宽 `except Exception`**：仅限“可选依赖的调用”这一类，**必须**带 `# noqa: BLE001` 并紧接一行说明。其它地方（解析、判定）一律精确捕获。

## 3. 库代码规则

- 模块顶层**不调用** `print` / `exit` / `quit` / `open` / `Path.read_*` —— import 期不能有副作用。`tests/unit/test_architecture.py` 会自动守这条。
- **公开模块**（`ir/`, `exitcodes.py`, `cli.py`）必须显式声明 `__all__`。
- 类型标注严格 `mypy --strict`（见 `pyproject.toml` 的 `[tool.mypy]`），**禁止**无理由的 `# type: ignore`：每条都必须带“`# type: ignore[code] — 原因`”的行尾注释。
- `Any` 是**逃生舱**：`mypy` 报 `no-any-return` / `arg-type: Any` 时用 `cast(…, value)` 显式收窄，不要“直接返回 Any 然后补个 ignore”。
- IR dataclass（§4）用 `frozen=True`；可变状态只在 Builder 内部出现。
- IR 字段默认值只方便构造；**分析阶段必须显式写入所有状态**。不得用空列表或 `None` 表达“无法判定”，应使用 `unknown` 枚举或专门的 `present` 布尔。

## 4. 命名

- 前端业务规则集中在 `frontend/src/lib/workflow-rules.ts` 并与后端校验同步；后端校验是权威。

- 公开名字（`Bridge.impl_class` 之类）只用**英文 snake_case**。中文只允许出现在**面向用户的字符串**里：CLI 输出、报告模板、logging 自然语言。
- 稳定 ID 一律 `stable_id(kind, key)`，禁止自增。
- 决策记入[架构决策](../architecture/adr/)；规格与代码冲突时修订规格，不在代码里添加未说明的特例。
