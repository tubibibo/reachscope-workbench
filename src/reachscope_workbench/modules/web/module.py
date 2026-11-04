"""Web module adapter: active observation, imported assets and offline demonstration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...core.models import (
    Evidence,
    ModuleResult,
    ModuleSpec,
    Observation,
    RunContext,
    WorkbenchError,
)
from .importer import MAX_IMPORT_BYTES, parse_import
from .legacy.attack_path import build_paths, load_transition_rules
from .legacy.attack_surface import build_surfaces
from .legacy.classify import classify_assets
from .legacy.demo import website_demo_assets
from .legacy.models import Asset
from .probe import CHECKS, probe_url
from .scope import normalize_url

_UPLOAD_ID = re.compile(r"[0-9a-f]{32}\Z")
_LIMITATIONS = [
    "HTTP observations and missing security headers are not confirmed vulnerabilities.",
    "Fingerprint scores and investigation paths come from heuristic rules; they are not calibrated probabilities.",
    "Imported scanner findings are preserved as unverified third-party reports, not revalidated findings.",
    "Probing issues GET requests only to supplied URLs and in-scope redirects; it does not crawl, brute-force paths or execute exploits.",
]


def _selected_checks(value: Any, mode: str) -> list[str]:
    allowed = list(CHECKS) if mode == "probe" else ["fingerprints"]
    if value is None:
        return allowed
    if not isinstance(value, list) or not value or len(value) > len(allowed) or any(not isinstance(item, str) or item not in allowed for item in value):
        raise WorkbenchError("INVALID_CONFIG", "Web checks are incompatible with this input mode")
    selected = set(value)
    if mode == "probe":
        selected.add("http")
    return [item for item in allowed if item in selected]


def _id(kind: str, value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return kind + "-" + hashlib.sha256(data).hexdigest()[:20]


def _read_upload(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_IMPORT_BYTES + 1)
    except OSError as exc:
        raise WorkbenchError("INVALID_UPLOAD", "The asset upload cannot be read") from exc
    if len(data) > MAX_IMPORT_BYTES:
        raise WorkbenchError("IMPORT_LIMIT", "Asset import is limited to 2 MiB")
    return data


class WebModule:
    spec = ModuleSpec(
        id="web", name="Web 资产与探测", description="精确 URL 探测、资产导入、技术指纹与候选调查路径",
        capabilities=["http_observation", "asset_import", "fingerprint", "security_headers", "candidate_paths",
                      "response_checks", "page_inventory", "cookie_metadata", "historical_comparison", "inventory_csv"],
        input_modes=["probe", "import", "demo"],
        version="1.1",
    )

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = config.get("mode", "demo")
        if mode not in self.spec.input_modes:
            raise WorkbenchError("INVALID_CONFIG", "Web mode must be probe, import or demo")
        allowed = {"mode", "checks"} | ({"targets", "allow_private", "timeout", "concurrency"} if mode == "probe" else
                                        {"upload_id", "filename"} if mode == "import" else set())
        for key in config.keys() - allowed:
            value = config[key]
            if value is not None and value is not False and value != "" and value != [] and value != {}:
                raise WorkbenchError("INVALID_CONFIG", "Web input fields do not match the selected URL, file or synthetic demo mode")
        checks = _selected_checks(config.get("checks"), mode)
        if mode == "demo":
            return {"mode": "demo", "checks": checks}
        if mode == "import":
            upload_id, filename = config.get("upload_id"), config.get("filename")
            if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
                raise WorkbenchError("INVALID_CONFIG", "A valid uploaded file ID is required")
            if not isinstance(filename, str) or len(filename) > 255 or Path(filename).suffix.lower() not in {".csv", ".json", ".jsonl", ".ndjson"}:
                raise WorkbenchError("INVALID_CONFIG", "Import filename must have a JSON, CSV or JSONL extension")
            return {"mode": mode, "upload_id": upload_id, "filename": Path(filename).name, "checks": checks}
        targets = config.get("targets")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 20 or any(not isinstance(target, str) for target in targets):
            raise WorkbenchError("INVALID_CONFIG", "Provide between 1 and 20 exact HTTP(S) targets")
        allow_private = config.get("allow_private", False)
        timeout, concurrency = config.get("timeout", 8), config.get("concurrency", 3)
        if type(allow_private) is not bool:
            raise WorkbenchError("INVALID_CONFIG", "allow_private must be a boolean")
        if type(timeout) not in {int, float} or not 0.2 <= timeout <= 15:
            raise WorkbenchError("INVALID_CONFIG", "timeout must be between 0.2 and 15 seconds")
        if type(concurrency) is not int or not 1 <= concurrency <= 5:
            raise WorkbenchError("INVALID_CONFIG", "concurrency must be between 1 and 5")
        return {"mode": mode, "targets": list(dict.fromkeys(normalize_url(target) for target in targets)),
                "allow_private": allow_private, "timeout": float(timeout), "concurrency": concurrency, "checks": checks}

    async def run(self, config: dict[str, Any], context: RunContext) -> ModuleResult:
        clean = self.validate(config)
        context.progress(5, "准备 Web 输入与范围")
        warnings: list[str] = []
        mode = clean["mode"]
        if mode == "probe":
            assets, records = await self._probe(clean, context)
            target = ", ".join(clean["targets"])
        elif mode == "import":
            path = context.uploads / clean["upload_id"]
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMPORT_BYTES:
                raise WorkbenchError("INVALID_UPLOAD", "Asset upload is missing or exceeds 2 MiB")
            data = await asyncio.to_thread(_read_upload, path)
            assets, records, warnings = parse_import(data, clean["filename"])
            for record in records:
                record["upload_sha256"] = hashlib.sha256(data).hexdigest()
            target = clean["filename"]
        else:
            assets = website_demo_assets()
            records = [{"url": normalize_url(f"{asset.protocol}://{asset.host}" +
                        (f":{asset.port}" if asset.port not in {"80", "443"} else "") + "/"),
                        "status_code": None, "reachable": False, "synthetic": True,
                        "reachability_source": "synthetic_offline", "format": "demo"} for asset in assets]
            target = "网站合成样例 / example.com / 未发送网络请求"
        context.progress(70, f"整理 {len(assets)} 项资产与本次检查证据")
        # Rule evaluation is bounded and runs in a worker to keep task cancellation
        # and API handling responsive even for a large imported inventory.
        result = await asyncio.to_thread(self._assemble, assets, records, mode, target, warnings, clean["checks"])
        context.progress(100, "Web 分析完成")
        return result

    async def _probe(self, config: dict[str, Any], context: RunContext) -> tuple[list[Asset], list[dict[str, Any]]]:
        semaphore = asyncio.Semaphore(config["concurrency"])
        completed = 0

        async def observe(target: str) -> dict[str, Any]:
            nonlocal completed
            async with semaphore:
                result = await probe_url(target, allow_private=config["allow_private"], timeout=config["timeout"], checks=config["checks"])
                completed += 1
                context.progress(10 + int(55 * completed / len(config["targets"])), f"已探测 {completed}/{len(config['targets'])}")
                return result

        records = await asyncio.gather(*(observe(target) for target in config["targets"]))
        assets = []
        for record in records:
            parsed = urlsplit(record["url"])
            assets.append(Asset(
                host=parsed.hostname or "", ip=record.get("ip", ""),
                port=str(parsed.port or (443 if parsed.scheme == "https" else 80)),
                protocol=parsed.scheme, title=record["title"], server=record["server"],
            ))
        return assets, records

    def _assemble(
        self, assets: list[Asset], records: list[dict[str, Any]], mode: str,
        target: str, warnings: list[str], checks: list[str] | None = None,
    ) -> ModuleResult:
        selected = checks if checks is not None else list(CHECKS) if mode == "probe" else ["fingerprints"]
        if "fingerprints" in selected:
            classify_assets(assets)
        surfaces = build_surfaces(assets) if "fingerprints" in selected else []
        capabilities, _ = load_transition_rules() if "fingerprints" in selected else ({}, [])
        # Candidate-path enumeration has a separate explicit resource budget.
        paths = build_paths(assets[:100], max_depth=4, max_paths=60) if "fingerprints" in selected else []
        evidence: list[Evidence] = []
        observations: list[Observation] = []
        inventory: list[dict[str, Any]] = []
        check_summary = dict.fromkeys(("pass", "review", "info", "not_applicable"), 0)
        asset_evidence: dict[int, str] = {}
        for index, (asset, record) in enumerate(zip(assets, records, strict=True), 1):
            eid = _id("web", {"record": record, "index": index})
            if mode == "probe" and ("headers" in selected or "page" in selected):
                record = {**record, "checks": [{**check, "evidence_ids": [eid]} for check in record.get("checks", [])]}
                for check in record["checks"]:
                    if check["status"] in check_summary:
                        check_summary[check["status"]] += 1
            asset_evidence[id(asset)] = eid
            kind = "http_observation" if mode == "probe" else "synthetic_asset" if mode == "demo" else "imported_asset"
            evidence.append(Evidence(
                id=eid, kind=kind, title=asset.title or asset.host, source=record["url"],
                data={**record, "asset": asdict(asset), "fingerprint_evidence": asset.evidence},
                sha256=record.get("body_sha256", record.get("upload_sha256", "")),
            ))
            inventory.append({**asdict(asset), **record, "id": _id("asset", {"url": record["url"], "index": index}),
                              "evidence_ids": [eid], "fingerprint_confidence": asset.confidence})
            if asset.tech:
                observations.append(Observation(
                    id=_id("fingerprint", eid), title=f"技术线索：{asset.tech}", severity="info",
                    category="fingerprint", description="；".join(asset.evidence), evidence_ids=[eid],
                    confidence="heuristic", recommendation="结合页面用途与响应证据人工确认，不根据组件名称直接判断漏洞。",
                ))
            if mode == "probe":
                self._http_observations(record, eid, observations)
            finding = record.get("imported_finding")
            if finding:
                severity = finding["severity"] if finding["severity"] in {"info", "low", "medium", "high", "critical"} else "info"
                observations.append(Observation(
                    id=_id("imported", eid), title="导入扫描报告：" + (finding["name"] or finding["template_id"]),
                    severity=severity, category="imported_finding", confidence="imported_unverified",
                    description=f"外部工具报告 {finding['template_id']}，本次未主动验证。", evidence_ids=[eid],
                    recommendation="复核外部扫描记录、命中条件、目标归属及误报条件。",
                ))
        path_views = [{
            "id": _id("path", {"evidence": asset_evidence[id(path.asset)], "steps": [step.transition.id for step in path.steps]}),
            "asset": path.asset.host,
            "title": " → ".join(capabilities[step.gain].label or step.gain for step in path.steps),
            "target": path.target, "hops": path.hops, "priority_score": path.score,
            "status": "candidate_investigation", "confidence": "heuristic",
            "evidence_ids": [asset_evidence[id(path.asset)]],
            "steps": [{"id": step.transition.id, "name": step.transition.name, "action": step.transition.action,
                       "success_signal": step.transition.success_signal, "false_positives": step.transition.false_positive}
                      for step in path.steps],
            "cautions": path.cautions,
            "interpretation": "规则建议的调查顺序，步骤条件未被本工具主动验证。",
        } for path in paths]
        return ModuleResult(
            module="web", target=target,
            summary={"assets": len(assets), "online": sum(bool(r.get("reachable")) for r in records) if mode == "probe" else 0,
                     "imported_responses": sum(bool(r.get("reachable")) for r in records) if mode == "import" else 0,
                     "observations": len(observations), "paths": len(path_views),
                     "mode": mode, "synthetic": mode == "demo", "errors": sum(bool(r.get("error")) for r in records),
                     "import_warnings": len(warnings), "checks": sum(check_summary.values()),
                     "review_checks": check_summary["review"]},
            evidence=evidence, observations=observations,
            details={"assets": inventory, "paths": path_views,
                     "check_summary": check_summary,
                     "execution": self._execution(selected, records, mode),
                     "surfaces": [{"category": item.category, "name": item.display_name, "priority": item.priority,
                                   "tactics": item.tactics, "success_signal": item.success_signal,
                                   "false_positives": item.false_positive, "asset_count": len(item.assets)} for item in surfaces],
                     "import_warnings": warnings[:100],
                     "path_scope": {"assets_evaluated": min(len(assets), 100) if "fingerprints" in selected else 0, "max_depth": 4, "max_paths": 60},
                     "provenance": "ReachScope fingerprint rules + ReachScope Workbench bounded observation"},
            limitations=[*_LIMITATIONS, *warnings[:20], *(["Candidate paths evaluated only for the first 100 assets."] if len(assets) > 100 else [])],
        )

    @staticmethod
    def _execution(selected: list[str], records: list[dict[str, Any]], mode: str) -> list[dict[str, str]]:
        labels = {"http": "响应与连接", "headers": "响应头、Cookie 与证书", "page": "表单与页面资源", "fingerprints": "技术线索与调查路径"}
        failed = sum(not record.get("reachable") for record in records) if mode == "probe" else 0
        rows = []
        for check in CHECKS:
            status = "skipped" if check not in selected else "failed" if mode == "probe" and failed == len(records) else "completed"
            reason = "本次未选择，不运行对应解析或规则" if status == "skipped" else "所有目标均未取得响应，无法完成该检查" if status == "failed" else f"已执行；{failed} 个目标请求失败" if failed else "已执行"
            if mode != "probe" and check != "fingerprints":
                reason = "离线输入不进行网络响应检查"
            rows.append({"id": check, "label": labels[check], "status": status, "reason": reason})
        return rows

    @staticmethod
    def _http_observations(record: dict[str, Any], eid: str, items: list[Observation]) -> None:
        def add(code: str, title: str, description: str, severity: str = "info") -> None:
            items.append(Observation(id=_id(code, eid), title=title, severity=severity, category=code,
                                     description=description, evidence_ids=[eid], confidence="observed",
                                     recommendation="结合业务用途复核配置；本条观察不等于已确认漏洞。"))
        if not record["reachable"]:
            add("probe_error", "探测未完成", record["error"]["message"])
            return
        if record["url"].startswith("http://") and record["final_url"].startswith("http://"):
            add("cleartext_http", "响应使用明文 HTTP", "该精确 URL 未升级到 HTTPS。", "low")
        for check in record.get("checks", []):
            if check["status"] == "review":
                items.append(Observation(
                    id=_id("check-" + check["id"], eid), title=check["title"], severity=check["severity"],
                    category="security_headers" if check["id"] in {"csp", "frame_protection", "nosniff", "referrer_policy"} else check["id"],
                    description=check["description"], recommendation=check["recommendation"],
                    evidence_ids=[eid], confidence="observed",
                ))
        if record.get("body_truncated"):
            add("body_limit", "响应正文达到采集上限", "只采集最多 512 KiB，正文摘要针对已采集前缀。")
        if record.get("redirect_stopped"):
            reason = "Location 响应头达到采集上限，未把截断的地址当作实际跳转目标。" if record["redirect_stopped"] == "location_truncated" else "跳转超出原始主机/端口范围或达到跳数上限。"
            add("redirect_scope", "重定向已停止", reason)
        if record.get("cookies_truncated"):
            add("cookie_capture", "Cookie 属性采集不完整", "Cookie 响应头达到数量/长度上限或存在无法解析的记录，未保存其原始值。")
        if record.get("headers_truncated"):
            add("header_capture", "部分响应头达到采集上限", "这些响应头只保留前 4096 字符：" + ", ".join(record["headers_truncated"]))
