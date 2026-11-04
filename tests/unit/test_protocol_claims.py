"""协议输入模型：claim / question / answer 的校验与稳定 ID。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reachscope.protocol.answer import AnswersDoc, load_answers
from reachscope.protocol.claims import (
    Claim,
    ClaimError,
    load_claim,
    parse_claim,
)
from reachscope.protocol.question import AnswerType, make_question


def _base_claim(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": "0.1",
        "kind": "reachability",
        "entry": {"kind": "component", "name": "com.example.app.MainActivity"},
        "sink": {"kind": "file"},
    }
    data.update(overrides)
    return data


def test_claim_roundtrip_and_stable_id() -> None:
    claim = Claim.from_dict(_base_claim())
    assert claim.claim_id
    assert claim.to_dict()["claim_id"] == claim.claim_id
    again = Claim.from_dict(claim.to_dict())
    assert again == claim


def test_claim_id_is_key_order_independent() -> None:
    data = _base_claim(
        asserted_steps=[{"sink": "webview"}, {"sink": "file"}],
        assumptions=[{"id": "a-1", "text": "page is attacker controlled"}],
    )
    reordered = json.loads(json.dumps(data, sort_keys=True))
    assert Claim.from_dict(data).claim_id == Claim.from_dict(reordered).claim_id
    assert Claim.from_dict(data).claim_id != Claim.from_dict(_base_claim()).claim_id


def test_explicit_claim_id_is_kept() -> None:
    claim = Claim.from_dict(_base_claim(claim_id="deadbeef"))
    assert claim.claim_id == "deadbeef"


def test_unknown_keys_are_ignored() -> None:
    claim = Claim.from_dict(_base_claim(future_field={"x": 1}))
    assert claim.entry.name.endswith("MainActivity")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "9.9"}, "schema_version"),
        ({"kind": "exploitability"}, "解析失败"),
        ({"entry": {"kind": "component"}}, "entry"),
        ({"entry": {"kind": "intent", "name": "x"}}, "解析失败"),
        ({"sink": {}}, "sink.kind"),
        ({"sink": {"kind": "sql"}}, "sink.kind"),
        ({"asserted_steps": [{}]}, "asserted_steps"),
        ({"asserted_steps": [{"sink": "rce"}]}, "asserted_steps"),
        (
            {
                "assumptions": [
                    {"id": "a", "text": "x"},
                    {"id": "a", "text": "y"},
                ]
            },
            "重复",
        ),
        ({"assumptions": [{"id": "", "text": "x"}]}, "assumptions"),
        ({"assumptions": [{"id": "a", "text": ""}]}, "assumptions"),
    ],
)
def test_claim_validation_errors(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ClaimError, match=message):
        Claim.from_dict(_base_claim(**overrides))


def test_parse_claim_rejects_invalid_json_and_non_object() -> None:
    with pytest.raises(ClaimError, match="合法 JSON"):
        parse_claim("{not json")
    with pytest.raises(ClaimError, match="JSON 对象"):
        parse_claim("[]")


def test_load_claim_missing_file() -> None:
    with pytest.raises(ClaimError, match="无法读取"):
        load_claim(Path("does-not-exist.json"))


def test_load_claim_from_file(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    path.write_text(json.dumps(_base_claim()), encoding="utf-8")
    assert load_claim(path).entry.name.endswith("MainActivity")


def test_question_id_is_stable_and_key_suffix_distinguishes() -> None:
    first = make_question(
        code="JUDGMENT_UNKNOWN",
        subject_kind="chain",
        subject_id="c1",
        question="q",
        why="w",
        answer_type=AnswerType.FREE_TEXT,
        key_suffix="J4:0",
    )
    same = make_question(
        code="JUDGMENT_UNKNOWN",
        subject_kind="chain",
        subject_id="c1",
        question="q",
        why="w",
        answer_type=AnswerType.FREE_TEXT,
        key_suffix="J4:0",
    )
    other = make_question(
        code="JUDGMENT_UNKNOWN",
        subject_kind="chain",
        subject_id="c1",
        question="q",
        why="w",
        answer_type=AnswerType.FREE_TEXT,
        key_suffix="J4:1",
    )
    assert first.question_id == same.question_id
    assert first.question_id != other.question_id
    assert len(first.question_id) == 8


def test_answers_document_validation() -> None:
    doc = AnswersDoc.from_dict(
        {
            "schema_version": "0.1",
            "answers": [{"question_id": "abc12345", "value": "false"}],
        }
    )
    assert doc.answers[0].source == "model"
    assert doc.answers[0].value == "false"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": "9", "answers": []}, "schema_version"),
        ({"answers": [{"value": "x"}]}, "question_id"),
        ({"answers": [{"question_id": "a", "value": " "}]}, "value"),
        (
            {
                "answers": [
                    {"question_id": "a", "value": "x"},
                    {"question_id": "a", "value": "y"},
                ]
            },
            "重复",
        ),
    ],
)
def test_answers_document_errors(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ClaimError, match=message):
        AnswersDoc.from_dict(payload)


def test_load_answers_missing_file_and_bad_json(tmp_path: Path) -> None:
    with pytest.raises(ClaimError, match="无法读取"):
        load_answers(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ClaimError, match="合法 JSON"):
        load_answers(bad)
    not_object = tmp_path / "list.json"
    not_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ClaimError, match="JSON 对象"):
        load_answers(not_object)
