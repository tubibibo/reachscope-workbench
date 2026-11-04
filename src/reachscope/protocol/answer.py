"""模型对开放问题的回答（协议 v0.1）。

回答**只作为假设**进入裁决，绝不写回事实：`verify` 会把每条回答转成一条
`assumption`，并把结论上限压到 `SUPPORTED_WITH_ASSUMPTIONS`。

```json
{
  "schema_version": "0.1",
  "answers": [{"question_id": "1a2b3c4d", "value": "false", "source": "model"}]
}
```

引用不存在的问题、重复 `question_id`、空回答 → :class:`ClaimError`（退出码 2）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self

from ..ir.serialize import IRDeserializeError, IRSerializable, deserialize
from .claims import PROTOCOL_SCHEMA_VERSION, SUPPORTED_INPUT_VERSIONS, ClaimError


@dataclass(frozen=True)
class Answer(IRSerializable):
    """一条回答。`value` 一律用字符串承载，语义由问题的 `answer_type` 决定。"""

    question_id: str = ""
    value: str = ""
    source: str = "model"


@dataclass(frozen=True)
class AnswersDoc(IRSerializable):
    """回答文件。"""

    schema_version: str = PROTOCOL_SCHEMA_VERSION
    answers: list[Answer] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """解析并做结构校验。"""
        try:
            doc = deserialize(cls, data)
        except IRDeserializeError as exc:
            raise ClaimError(f"answers 解析失败：{exc}") from exc
        _validate(doc)
        return replace(doc, schema_version=PROTOCOL_SCHEMA_VERSION)


def load_answers(path: str | Path) -> AnswersDoc:
    """从 JSON 文件读取回答。"""
    answers_path = Path(path)
    try:
        raw = answers_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClaimError(f"answers 文件无法读取：{answers_path}（{exc}）") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaimError(f"answers 不是合法 JSON（{answers_path}）：{exc}") from exc
    if not isinstance(data, dict):
        raise ClaimError(f"answers 顶层必须是 JSON 对象（{answers_path}）")
    return AnswersDoc.from_dict(data)


def _validate(doc: AnswersDoc) -> None:
    """结构校验；取值语义（boolean/enum）在 `verdict` 里按问题类型校验。"""
    if doc.schema_version not in SUPPORTED_INPUT_VERSIONS:
        raise ClaimError(
            f"不支持的 answers.schema_version：{doc.schema_version!r}"
            f"（接受 {', '.join(sorted(SUPPORTED_INPUT_VERSIONS))}）"
        )
    seen: set[str] = set()
    for answer in doc.answers:
        if not answer.question_id.strip():
            raise ClaimError("answers[].question_id 不能为空")
        if not answer.value.strip():
            raise ClaimError(
                f"answers[{answer.question_id}].value 不能为空"
            )
        if answer.question_id in seen:
            raise ClaimError(f"answers 的 question_id 重复：{answer.question_id!r}")
        seen.add(answer.question_id)


__all__ = ["Answer", "AnswersDoc", "load_answers"]
