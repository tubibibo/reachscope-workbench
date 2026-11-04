"""Read-only views that separate code locations, inferred paths and risk judgments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..artifacts import Artifact, ArtifactError
from ..ir.model import Chain, Component, Deeplink, Judgment, SourceLoc
from ..ir.serialize import stable_id
from ..ir.validation import validate_identifiers
from ..protocol.claims import Claim, ClaimError
from ..protocol.questions import questions_document
from ..protocol.verdict import verify_claim

QUERY_SCHEMA_VERSION = "1.0"
MAX_PAGE_SIZE = 100
MAX_CHAIN_ITEMS = 100
MAX_FINDINGS = 20
MAX_CODE_CHARACTERS = 24_000
MAX_WARNING_ITEMS = 20

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "Paths are static-analysis candidates, not confirmed vulnerabilities.",
    "Call paths are limited to depth 4 and one explicit intra-APK component hop.",
    "Analysis is not fully path-sensitive; reflection, JNI and dynamic loading are not resolved.",
    "Absence from this report does not prove that a program path does not exist.",
)


class QueryError(ValueError):
    """A caller-visible query failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EvidenceSession:
    """Query an existing artifact without decoding or analyzing the APK again.

    Every result is scoped to one artifact. Unqualified IDs are accepted only
    within this session; returned references always include the artifact ID.
    """

    def __init__(self, artifact: Artifact) -> None:
        validate_identifiers(artifact.report.components, artifact.report.chains)
        self.artifact = artifact
        self._metadata = artifact.metadata
        self._source_hashes: dict[str, str] = {}
        source_files = self._metadata.get("files", [])
        if isinstance(source_files, list):
            for source in source_files:
                if isinstance(source, dict):
                    path, digest = source.get("path"), source.get("sha256")
                    if isinstance(path, str) and isinstance(digest, str):
                        self._source_hashes[path] = digest

    def overview(self) -> dict[str, Any]:
        """Return analysis identity, counts, limitations and discoverable operations."""
        report = self.artifact.report
        return self._response(
            {
                "package": report.meta.package,
                "apk_sha256": report.meta.apk_sha256,
                "tool_version": report.meta.tool_version,
                "counts": report.summary(),
                "protection": report.protection.to_dict(),
                "metadata": {
                    key: deepcopy(self._metadata[key])
                    for key in (
                        "artifact_schema_version", "report_schema_version", "tool_version",
                        "report_tool_version", "apktool_version", "decoded_sha256",
                        "method_count", "source_bytes", "config",
                    )
                    if key in self._metadata
                },
                "operations": [
                    "entries", "chains", "chain", "methods", "method", "check", "questions"
                ],
                "interpretation": "Query candidate paths, then read their code before drawing conclusions.",
            }
        )

    def entries(
        self, query: str = "", *, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """List manifest components and deep links, optionally filtered by text."""
        self._validate_text(query, "query", allow_empty=True)
        items = [self._component(item) for item in self.artifact.report.components]
        items.extend(self._deeplink(item) for item in self.artifact.report.deeplinks)
        needle = query.casefold()
        if needle:
            items = [
                item for item in items
                if any(needle in str(item.get(field, "")).casefold()
                       for field in ("name", "id", "component", "uri", "reference"))
            ]
        items.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
        return self._page(items, offset, limit)

    def chains(
        self, entry: str | None = None, *, offset: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        """List compact summaries of paths already found by this analysis.

        ``entry`` accepts a component name/ID, deep-link ID/URI or scoped
        reference. This is a filter over report paths, not a new taint query.
        """
        names = self._entry_names(entry) if entry is not None else None
        selected = [
            item for item in self.artifact.report.chains
            if names is None or any(name in names for name in item.entries)
        ]
        items = [self._chain_summary(item) for item in sorted(selected, key=lambda item: item.id)]
        return self._page(items, offset, limit)

    def chain(self, chain_id: str) -> dict[str, Any]:
        """Expand a candidate chain, preserving code locations and judgment categories."""
        local_id = self._local_reference(chain_id, "chain")
        selected = next(
            (item for item in self.artifact.report.chains if item.id == local_id), None
        )
        if selected is None:
            raise QueryError("CHAIN_NOT_FOUND", f"No chain {local_id!r} in this artifact")
        findings = [
            item.to_dict() for item in self.artifact.report.findings
            if item.chain_id == selected.id
        ]
        steps: list[dict[str, Any]] = []
        for item in selected.steps[:MAX_CHAIN_ITEMS]:
            step = item.to_dict()
            step["reference"] = self._reference("step", f"{selected.id}/{item.order}")
            step["evidence_type"] = "static_inference"
            step["source"] = self._source(item.source)
            steps.append(step)
        judgments = [self._judgment(item) for item in selected.judgments[:MAX_CHAIN_ITEMS]]
        data = self._chain_summary(selected)
        data.update(
            {
                "steps": steps,
                "judgments": judgments,
                "risk_assessment": {
                    "evidence_type": "risk_judgment",
                    "rank": selected.rank.to_dict(),
                    "findings": findings[:MAX_FINDINGS],
                    "interpretation": "Risk rules are distinct from path evidence; findings require review.",
                },
                "detail_limits": {
                    "steps_total": len(selected.steps),
                    "steps_returned": len(steps),
                    "judgments_total": len(selected.judgments),
                    "judgments_returned": len(judgments),
                    "findings_total": len(findings),
                    "findings_returned": min(len(findings), MAX_FINDINGS),
                    "truncated": (
                        len(selected.steps) > MAX_CHAIN_ITEMS
                        or len(selected.judgments) > MAX_CHAIN_ITEMS
                        or len(findings) > MAX_FINDINGS
                    ),
                    "continuation": "Use method queries to inspect source; the persisted report contains full detail.",
                },
            }
        )
        return self._response(data)

    def methods(
        self, query: str = "", *, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """Search the artifact's persisted method catalogue."""
        self._validate_text(query, "query", allow_empty=True)
        self._validate_page(offset, limit)
        try:
            result = self.artifact.list_methods(query=query, offset=offset, limit=limit)
        except ArtifactError as exc:
            raise QueryError(exc.code, str(exc)) from exc
        items = result.get("methods", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item["reference"] = self._reference("method", str(item["method_ref"]))
                    item["evidence_type"] = "code_location"
                    item["sha256"] = self._source_hashes.get(str(item.get("file", "")))
        response = self._response(items)
        response["pagination"] = self._artifact_pagination(result, "total")
        return response

    def method(
        self, ref: str, *, offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        """Read a bounded, hash-checked page of original method code."""
        self._validate_text(ref, "ref")
        self._validate_page(offset, limit)
        # Dalvik descriptors contain ':' only inside strings; a scoped method
        # reference has the unambiguous ':method:' delimiter before the ref.
        if ":method:" in ref:
            prefix, ref = ref.split(":method:", 1)
            if prefix != self.artifact.id:
                raise QueryError("ARTIFACT_MISMATCH", "Method reference belongs to another artifact")
        try:
            result = self.artifact.read_method(ref, offset=offset, limit=limit)
        except ArtifactError as exc:
            raise QueryError(exc.code, str(exc)) from exc
        code = result.get("code", "")
        if isinstance(code, str) and len(code) > MAX_CODE_CHARACTERS:
            raise QueryError(
                "OUTPUT_LIMIT",
                f"Method page exceeds {MAX_CODE_CHARACTERS} characters; reduce the line limit "
                "or inspect the saved source locally if one line alone exceeds the budget.",
            )
        response = self._response({
            **result,
            "reference": self._reference("method", ref),
            "evidence_type": "code_fact",
        })
        response["pagination"] = self._artifact_pagination(result, "total_lines")
        return response

    def check(self, claim: dict[str, Any]) -> dict[str, Any]:
        """Check claim consistency with the report, without proving a vulnerability."""
        if not isinstance(claim, dict):
            raise QueryError("INVALID_CLAIM", "claim must be a JSON object")
        payload = deepcopy(claim)
        supplied_artifact = payload.pop("artifact_id", self.artifact.id)
        if supplied_artifact != self.artifact.id:
            raise QueryError("ARTIFACT_MISMATCH", "Claim belongs to another artifact")
        entry = payload.get("entry")
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
            kind = "deeplink" if entry.get("kind") == "deeplink" else "component"
            entry["id"] = self._local_reference(entry["id"], kind)
        try:
            parsed = Claim.from_dict(payload)
            verdict = verify_claim(self.artifact.report, parsed)
        except ClaimError as exc:
            raise QueryError("INVALID_CLAIM", str(exc)) from exc
        verdict_data = verdict.to_dict()
        all_evidence = verdict_data.get("evidence", [])
        all_missing = verdict_data.get("missing_facts", [])
        verdict_data["evidence"] = all_evidence[:MAX_CHAIN_ITEMS]
        verdict_data["missing_facts"] = all_missing[:MAX_CHAIN_ITEMS]
        for evidence in verdict_data["evidence"]:
            source = self._source(SourceLoc(
                file=str(evidence.get("file", "")),
                line=int(evidence.get("line", 0)),
                snippet=str(evidence.get("snippet", "")),
            ))
            evidence["source"] = source
        return self._response(
            {
                "evidence_type": "report_consistency_check",
                "verdict": verdict_data,
                "detail_limits": {
                    "evidence_total": len(all_evidence),
                    "missing_facts_total": len(all_missing),
                    "truncated": len(all_evidence) > MAX_CHAIN_ITEMS or len(all_missing) > MAX_CHAIN_ITEMS,
                },
                "interpretation": (
                    "This checks a claim against the persisted static-analysis report. "
                    "It does not independently establish runtime reachability or exploitability."
                ),
            }
        )

    def questions(self) -> dict[str, Any]:
        """Return report-derived gaps; model answers do not become code facts."""
        document = questions_document(self.artifact.report).to_dict()
        all_items = document.get("questions", [])
        items = all_items[:MAX_CHAIN_ITEMS]
        for item in items:
            item["reference"] = self._reference("question", str(item["question_id"]))
            evidence = item.get("evidence")
            if isinstance(evidence, dict):
                item["evidence"] = self._source(SourceLoc.from_dict(evidence))
        return self._response(
            {
                **document,
                "questions": items,
                "detail_limits": {
                    "total": len(all_items),
                    "returned": len(items),
                    "truncated": len(all_items) > len(items),
                    "continuation": "Query specific chains or methods to inspect remaining analysis gaps.",
                },
                "evidence_type": "analysis_gap",
                "interpretation": "Answers are assumptions until independently checked against evidence.",
            }
        )

    def _component(self, item: Component) -> dict[str, Any]:
        return {
            "kind": "component",
            "id": item.id,
            "reference": self._reference("component", item.id),
            "name": item.name,
            "component_type": item.type.value,
            "evidence_type": "manifest_configuration",
            "exported": item.exported,
            "exported_inferred": item.exported_inferred,
            "permission": item.permission,
            "permission_protection": item.permission_protection,
            "implementation": {
                "present": item.impl_present,
                "reason": item.impl_reason,
                "evidence_type": "static_inference",
            },
            "source": self._source(item.source),
            "candidate_chain_count": sum(
                item.name in chain.entries for chain in self.artifact.report.chains
            ),
        }

    def _deeplink(self, item: Deeplink) -> dict[str, Any]:
        return {
            "kind": "deeplink",
            "id": item.id,
            "reference": self._reference("deeplink", item.id),
            "uri": f"{item.scheme}://{item.host}{item.path}",
            "component": item.component,
            "auto_verify": item.auto_verify,
            "evidence_type": "manifest_configuration",
            "source": self._source(item.source),
        }

    def _chain_summary(self, item: Chain) -> dict[str, Any]:
        return {
            "id": item.id,
            "reference": self._reference("chain", item.id),
            "evidence_type": "static_inference",
            "entries": list(item.entries),
            "step_count": len(item.steps),
            "sinks": sorted({step.sink for step in item.steps}),
            "evidence_complete": item.evidence_complete,
            "interpretation": "Candidate path within the recorded analysis scope.",
        }

    def _judgment(self, item: Judgment) -> dict[str, Any]:
        data = item.to_dict()
        data["source"] = self._source(item.source)
        data["evidence_type"] = (
            "risk_judgment" if item.name.startswith(("J3", "J4")) else "static_inference"
        )
        return data

    def _source(self, item: SourceLoc | None) -> dict[str, Any] | None:
        if item is None:
            return None
        data = item.to_dict()
        data["reference"] = self._reference("source", stable_id("location", f"{item.file}:{item.line}"))
        data["evidence_type"] = "code_location"
        data["snippet_is_context"] = False
        data["sha256"] = self._source_hashes.get(item.file)
        data["saved_source_available"] = item.file in self._source_hashes
        return data

    def _entry_names(self, entry: str) -> set[str]:
        self._validate_text(entry, "entry")
        scoped_kind: str | None = None
        if ":component:" in entry or ":deeplink:" in entry:
            kind = "component" if ":component:" in entry else "deeplink"
            entry = self._local_reference(entry, kind)
            scoped_kind = kind
        names: set[str] = set()
        if scoped_kind != "deeplink":
            for item in self.artifact.report.components:
                if entry in (item.id, item.name):
                    names.add(item.name)
        if scoped_kind != "component":
            for link in self.artifact.report.deeplinks:
                if entry in (link.id, f"{link.scheme}://{link.host}{link.path}"):
                    names.add(link.component)
        if not names:
            raise QueryError("ENTRY_NOT_FOUND", f"No entry {entry!r} in this artifact")
        return names

    def _reference(self, kind: str, local_id: str) -> str:
        return f"{self.artifact.id}:{kind}:{local_id}"

    def _local_reference(self, value: str, kind: str) -> str:
        self._validate_text(value, kind)
        if ":" not in value:
            return value
        parts = value.split(":", 2)
        if len(parts) != 3 or parts[0] != self.artifact.id:
            raise QueryError("ARTIFACT_MISMATCH", "Reference belongs to another artifact or is malformed")
        if parts[1] != kind or not parts[2]:
            raise QueryError("INVALID_REFERENCE", f"Expected a {kind} reference")
        return parts[2]

    def _response(self, data: Any) -> dict[str, Any]:
        limitations = list(DEFAULT_LIMITATIONS)
        metadata_limits = self._metadata.get("limitations", [])
        if isinstance(metadata_limits, list):
            limitations.extend(item for item in metadata_limits if isinstance(item, str))
        warnings = list(self.artifact.report.meta.warnings)
        artifact_warnings = self._metadata.get("warnings", [])
        if isinstance(artifact_warnings, list):
            warnings.extend(item for item in artifact_warnings if isinstance(item, str))
        warnings = list(dict.fromkeys(warnings))
        limitations.extend(f"Analysis warning: {item}" for item in warnings[:MAX_WARNING_ITEMS])
        if len(warnings) > MAX_WARNING_ITEMS:
            limitations.append(
                f"{len(warnings) - MAX_WARNING_ITEMS} further analysis warnings are saved in this artifact."
            )
        if not self.artifact.report.protection.analyzable:
            limitations.append("Protection prevented analysis of this artifact.")
        return {
            "schema_version": QUERY_SCHEMA_VERSION,
            "artifact_id": self.artifact.id,
            "scope": "static_analysis_report",
            "limitations": list(dict.fromkeys(limitations)),
            "warning_count": len(warnings),
            "data": data,
        }

    def _page(self, items: list[dict[str, Any]], offset: int, limit: int) -> dict[str, Any]:
        self._validate_page(offset, limit)
        stop = offset + limit
        response = self._response(items[offset:stop])
        response["pagination"] = {
            "offset": offset,
            "limit": limit,
            "total": len(items),
            "truncated": stop < len(items),
            "next_offset": stop if stop < len(items) else None,
        }
        return response

    @staticmethod
    def _artifact_pagination(result: dict[str, object], total_key: str) -> dict[str, object]:
        return {
            "offset": result.get("offset", 0),
            "limit": result.get("limit", 0),
            "total": result.get(total_key, 0),
            "truncated": result.get("truncated", False),
            "next_offset": result.get("next_offset"),
        }

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if type(offset) is not int or offset < 0:
            raise QueryError("INVALID_PAGE", "offset must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise QueryError("INVALID_PAGE", f"limit must be between 1 and {MAX_PAGE_SIZE}")

    @staticmethod
    def _validate_text(value: str, name: str, *, allow_empty: bool = False) -> None:
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise QueryError("INVALID_QUERY", f"{name} must be {'a' if allow_empty else 'a nonempty'} string")
        if len(value) > 1000:
            raise QueryError("INVALID_QUERY", f"{name} must be at most 1000 characters")
