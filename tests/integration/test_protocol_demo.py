"""端到端回放 `examples/protocol/`：golden 报告 + 示例 claim → 逐字节裁决。

不依赖 APK / apktool：输入直接用 `tests/golden/*.json`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from reachscope.protocol.answer import load_answers
from reachscope.protocol.claims import load_claim
from reachscope.protocol.verdict import render_verdict, verify_claim
from reachscope.report.json_report import load_json

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples" / "protocol"


@dataclass(frozen=True)
class Demo:
    report: str
    claim: str
    answers: str | None
    status: str
    reason_code: str


DEMOS = [
    Demo(
        "01_positive_deeplink_bridge_sink.json",
        "supported.json",
        None,
        "SUPPORTED",
        "CHAIN_FOUND",
    ),
    Demo(
        "02_signature_permission.json",
        "refuted_permission.json",
        None,
        "REFUTED",
        "NOT_ZERO_PERMISSION",
    ),
    Demo(
        "01_positive_deeplink_bridge_sink.json",
        "step_mismatch.json",
        None,
        "UNDECIDABLE",
        "STEP_MISMATCH",
    ),
    Demo(
        "08_hardened_app.json",
        "undecidable_hardened.json",
        None,
        "UNDECIDABLE",
        "OUTSIDE_COVERAGE",
    ),
    Demo(
        "01_positive_deeplink_bridge_sink.json",
        "with_assumptions.json",
        None,
        "SUPPORTED_WITH_ASSUMPTIONS",
        "CHAIN_FOUND",
    ),
    Demo(
        "09_origin_check_before_load.json",
        "blocked_deeplink.json",
        "answers.json",
        "SUPPORTED_WITH_ASSUMPTIONS",
        "CHAIN_FOUND",
    ),
]


@pytest.mark.parametrize("demo", DEMOS, ids=lambda item: item.claim)
def test_example_replay_is_deterministic(demo: Demo) -> None:
    report = load_json(GOLDEN / demo.report)
    claim = load_claim(EXAMPLES / "claims" / demo.claim)
    answers = load_answers(EXAMPLES / demo.answers) if demo.answers else None

    first = render_verdict(verify_claim(report, claim, answers))
    second = render_verdict(verify_claim(report, claim, answers))
    assert first == second

    payload = json.loads(first)
    assert payload["schema_version"] == "0.2"
    assert payload["claim_id"] == claim.claim_id
    assert payload["status"] == demo.status
    assert payload["reason_code"] == demo.reason_code


def test_answers_are_only_assumptions() -> None:
    report = load_json(GOLDEN / "09_origin_check_before_load.json")
    claim = load_claim(EXAMPLES / "claims" / "blocked_deeplink.json")
    answers = load_answers(EXAMPLES / "answers.json")
    verdict = verify_claim(report, claim, answers)
    assert verdict.assumptions_used == [
        f"answer:{answers.answers[0].question_id}"
    ]
    assert verdict.status.value == "SUPPORTED_WITH_ASSUMPTIONS"
    assert verdict.scope == "static_analysis_report"


def test_supported_demo_carries_real_evidence() -> None:
    report = load_json(GOLDEN / "01_positive_deeplink_bridge_sink.json")
    claim = load_claim(EXAMPLES / "claims" / "supported.json")
    verdict = verify_claim(report, claim)
    assert [item.sink for item in verdict.evidence] == [
        "webview",
        "bridge_method",
        "bridge_method",
        "file",
        "file",
    ]
    assert all(item.file for item in verdict.evidence)
