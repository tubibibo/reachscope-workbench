"""Evidence-backed red/blue workflows over immutable asset inspection results."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .assets import AssetRepository
from .case_sources import candidates, compare_retest, source
from .catalog import profile_by_id
from .collaboration import CollaborationRepository
from .models import WorkbenchError
from .pagination import validate_page
from .repository import JobRepository

_LIMITATIONS = [
    "红队与蓝队是同一工作区的阅读和处理视角，不是账号、权限或多人身份隔离。",
    "线索来自已保存的分析与配置证据，不自动证明漏洞可利用或真实云权限已生效。",
    "工作区范围由操作者记录；范围说明不是外部法律授权的证明。",
    "复测只比较明确可比的检查条件；未再观察到该条件不等于整体安全。",
]


def _assessment_reference(assessment: dict[str, Any]) -> dict[str, Any]:
    """Store immutable job/evidence references, not another copy of target bodies."""
    return {"outcome": assessment["outcome"], "reason": str(assessment["reason"])[:1000],
            "source_job_id": assessment["source_job_id"], "retest_job_id": assessment["retest_job_id"],
            "input_revision": bool(assessment.get("input_revision")),
            "evidence_ids": [item["id"] for item in assessment.get("evidence", [])][:100]}


def _recorded_interval(job: dict[str, Any]) -> tuple[datetime, datetime]:
    """Terminal jobs retain their completion timestamp in updated_at."""
    try:
        start = datetime.fromisoformat(job["created_at"])
        end = datetime.fromisoformat(job["updated_at"])
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError("invalid inspection interval")
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkbenchError("INVALID_RETEST", "检查记录时间无法验证，不能作为复测依据") from exc
    return start, end


class CaseService:
    def __init__(self, repository: JobRepository) -> None:
        self.jobs = repository
        self.inventory = AssetRepository(repository)
        self.collaboration = CollaborationRepository(repository)

    def candidate_list(self, engagement_id: str, job_id: str) -> dict[str, Any]:
        engagement = self.collaboration.get_engagement(engagement_id)
        job = self.jobs.get(job_id)
        if job.get("asset_id") not in engagement["asset_ids"]:
            raise WorkbenchError("OUT_OF_SCOPE", "该任务不属于工作区记录的资产范围")
        return {"items": candidates(job), "job": {key: job.get(key) for key in ("id", "name", "module", "asset_id", "created_at")},
                "limitations": list(_LIMITATIONS)}

    def create_case(self, engagement_id: str, job_id: str, source_kind: str, source_ref: str,
                    *, idempotency_key: str | None = None) -> dict[str, Any]:
        # Only derive case content from saved, in-scope observations; callers
        # cannot promote arbitrary text to a scanner's finding or forge evidence.
        self.candidate_list(engagement_id, job_id)
        job = self.jobs.get(job_id)
        item = source(job, source_kind, source_ref)
        case = self.collaboration.create_case(
            engagement_id, str(job["asset_id"]), job_id, source_ref, source_kind,
            item["title"][:300], item["severity"], item["confidence"], idempotency_key=idempotency_key,
        )
        return self.detail(case["id"])

    def detail(self, case_id: str) -> dict[str, Any]:
        case = self.collaboration.get_case(case_id)
        job = self.jobs.get(case["job_id"])
        original = source(job, case["source_kind"], case["source_ref"])
        ids = set(original["evidence_ids"])
        events = self.collaboration.get_events(case_id, limit=100)
        return {
            **case, "source": original,
            "evidence": [record for record in job["result"]["evidence"] if record["id"] in ids],
            "events": events["items"], "event_pagination": {"next_cursor": events["next_cursor"], "limit": 100},
            "retests": [event for event in events["items"] if event["event_type"] in {"retest", "resolved"}],
            "retest_inputs": self.collaboration.get_retest_inputs(case_id), "limitations": list(_LIMITATIONS),
        }

    def assessment(self, case_id: str, retest_job_id: str) -> dict[str, Any]:
        case = self.collaboration.get_case(case_id)
        original, current = self.jobs.get(case["job_id"]), self.jobs.get(retest_job_id)
        if original["id"] == current["id"]:
            raise WorkbenchError("INVALID_RETEST", "复测必须选择另一次已完成检查，不能使用原记录")
        _, before_completed = _recorded_interval(original)
        after_started, _ = _recorded_interval(current)
        if after_started < before_completed:
            raise WorkbenchError("INVALID_RETEST", "复测须在原始检查完成后开始，请重新执行检查")
        revisions = {asset["id"] for asset in self.collaboration.get_retest_inputs(case_id)}
        return compare_retest(original, case["source_kind"], case["source_ref"], current,
                              related_asset_ids=revisions)

    def record_retest(self, case_id: str, expected_version: int, retest_job_id: str, note: str = "") -> dict[str, Any]:
        assessment = self.assessment(case_id, retest_job_id)
        self.collaboration.update_case(case_id, expected_version, {}, event_type="retest",
                                       event_data={"assessment": _assessment_reference(assessment), "note": note.strip()})
        return self.detail(case_id)

    def update(self, case_id: str, expected_version: int, patch: dict[str, Any], *, retest_job_id: str | None = None) -> dict[str, Any]:
        current = self.collaboration.get_case(case_id)
        if type(expected_version) is not int or expected_version < 1:
            raise WorkbenchError("INVALID_CASE", "请提供当前记录版本")
        # Bind decision checks to the exact snapshot the caller reviewed. The
        # final repository CAS separately rejects changes after this read.
        if current["version"] != expected_version:
            raise WorkbenchError("CASE_CONFLICT", "记录已被更新，请重新读取后再提交")
        if not patch:
            raise WorkbenchError("INVALID_CASE", "请提供要更新的状态、负责人、日期或说明")
        patch = {key: "" if value is None and key != "status" else value for key, value in patch.items()}
        if "status" in patch and patch["status"] is None:
            raise WorkbenchError("INVALID_CASE", "处理状态不能为空")
        status = patch.get("status", current["status"])
        event: dict[str, Any] = {"previous_status": current["status"], "changed_fields": sorted(patch)}
        if status == "resolved" and current["status"] != "resolved":
            if not retest_job_id or not str(patch.get("note", "")).strip():
                raise WorkbenchError("RETEST_REQUIRED", "关闭事项前需选择可比复测并填写处理依据")
            assessment = self.assessment(case_id, retest_job_id)
            if assessment["outcome"] != "not_observed_in_scope":
                raise WorkbenchError("RETEST_NOT_CLEARED", "该复测仍观察到条件或信息不可比，不能据此标记已整改")
            event["assessment"] = _assessment_reference(assessment)
        elif retest_job_id:
            raise WorkbenchError("INVALID_RETEST", "此处复测依据仅用于关闭事项；其他复测请单独记录")
        # Reopening a final decision needs an explicit explanation as well.
        if (current["status"] in {"resolved", "accepted_risk", "false_positive"}
                and status != current["status"] and not str(patch.get("note", "")).strip()):
            raise WorkbenchError("DECISION_NOTE_REQUIRED", "重新打开已决事项时请说明原因")
        self.collaboration.update_case(case_id, expected_version, patch,
                                       event_type="resolved" if status == "resolved" and current["status"] != status else "updated",
                                       event_data=event)
        return self.detail(case_id)

    def link_revised_input(self, case_id: str, expected_version: int, asset_id: str, note: str) -> dict[str, Any]:
        case = self.collaboration.get_case(case_id)
        original, revised = self.inventory.get(case["asset_id"]), self.inventory.get(asset_id)
        old_profile = profile_by_id(original["source"]["profile_id"])
        new_profile = profile_by_id(revised["source"]["profile_id"])
        if original["id"] == revised["id"]:
            raise WorkbenchError("INVALID_RETEST_INPUT", "原资产已在复测范围中，无需重复关联")
        if old_profile["id"] != new_profile["id"] or original["kind"] != revised["kind"]:
            raise WorkbenchError("INVALID_RETEST_INPUT", "修订文件必须使用相同的资产类别和输入格式")
        if old_profile["network"] or old_profile["input"] not in {"apk", "json"} or old_profile["mode"] not in {"apk", "import", "baseline"}:
            raise WorkbenchError("INVALID_RETEST_INPUT", "只有本地文件输入可关联修订；网络目标不能借复测更换范围")
        if original["kind"] == "host" and original["source"].get("host_id") != revised["source"].get("host_id"):
            raise WorkbenchError("INVALID_RETEST_INPUT", "修订资料必须保留同一稳定主机标识；文件关联不允许更换主机范围")
        if not note.strip():
            raise WorkbenchError("DECISION_NOTE_REQUIRED", "请说明修订文件与原实际资源的对应关系")
        self.collaboration.add_retest_input(case_id, expected_version, asset_id, note)
        return self.detail(case_id)

    def retest_jobs(self, case_id: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        validate_page(limit, offset)
        case = self.collaboration.get_case(case_id)
        original = self.jobs.get(case["job_id"])
        _recorded_interval(original)
        asset_ids = [case["asset_id"], *[asset["id"] for asset in self.collaboration.get_retest_inputs(case_id)]]
        placeholders = ",".join("?" for _ in asset_ids)
        with self.jobs.connection() as connection:
            connection.execute("BEGIN")
            where = f"ja.asset_id IN ({placeholders}) AND j.status='completed' AND j.id<>? AND j.created_at>=?"
            arguments = (*asset_ids, case["job_id"], original["updated_at"])
            total = connection.execute(f"SELECT COUNT(*) FROM jobs j JOIN job_assets ja ON ja.job_id=j.id WHERE {where}", arguments).fetchone()[0]
            rows = connection.execute(
                "SELECT j.id,j.module,j.name,j.config,j.status,j.progress,j.message,j.created_at,j.updated_at,j.error,"
                f"ja.asset_id,ja.snapshot AS asset_snapshot_json FROM jobs j JOIN job_assets ja ON ja.job_id=j.id WHERE {where} "
                "ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?", (*arguments, limit, offset),
            ).fetchall()
        return {"items": [self.jobs._decode(row, include_result=False) for row in rows], "total": total, "limit": limit, "offset": offset}

    def export(self, engagement_id: str) -> dict[str, Any]:
        engagement = self.collaboration.get_engagement(engagement_id)
        output: list[dict[str, Any]] = []
        offset, budget = 0, 0
        truncated = False
        while True:
            page = self.collaboration.list_cases(engagement_id=engagement_id, limit=100, offset=offset)
            for case in page["items"]:
                detail = self.detail(case["id"])
                size = len(json.dumps(detail, ensure_ascii=False).encode("utf-8"))
                if len(output) >= 500 or budget + size > 8 * 1024 * 1024:
                    truncated = True
                    break
                output.append(detail)
                budget += size
            offset += len(page["items"])
            if truncated or offset >= page["total"]:
                break
        return {"schema_version": "1.0", "engagement": engagement, "cases": output,
                "perspectives": {"red": "范围、原始线索、证据、验证记录", "blue": "负责人、处理决定、复测依据、审计历史"},
                "export_scope": {"total_cases": page["total"], "exported_cases": len(output), "truncated": truncated,
                                 "max_cases": 500, "case_bytes_limit": 8 * 1024 * 1024,
                                 "events_per_case": 100},
                "limitations": [*_LIMITATIONS,
                                "每项导出最多包含最早 100 条历史；通过 events 接口及 event_pagination 游标继续读取。",
                                *(["导出达到数量或数据预算，只含明确列出的部分事项。"] if truncated else [])]}
