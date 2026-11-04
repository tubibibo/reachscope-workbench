import { useState } from "react";
import { ArrowRight, Cloud, ChevronDown } from "lucide-react";
import type { ModuleResult } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { SearchField } from "../Common";
import { JsonData } from "./JsonData";
import { CloudGuidance } from "./CloudGuidance";
import "./cloud-review.css";

const labels: Record<string, string> = {
  pass: "满足检查条件",
  review: "待复核",
  unknown: "信息不足",
  info: "记录信息",
  not_applicable: "不适用",
};
export function CloudResult({
  result,
  onEvidence,
}: {
  result: ModuleResult;
  onEvidence: (id: string) => void;
}) {
  const resources = records(result.details.resources),
    checks = records(result.details.checks);
  const [resource, setResource] = useState("all"),
    [status, setStatus] = useState("all"),
    [search, setSearch] = useState(""),
    [tab, setTab] = useState("checks"),
    [limit, setLimit] = useState(30);
  const matches = checks.filter(
    (item) =>
      (resource === "all" || item.resource_id === resource) &&
      (status === "all" || item.status === status) &&
      `${readable(item.title)} ${readable(item.resource_id)}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const selectedResources = resources.filter((item) =>
    `${readable(item.address)} ${readable(item.type)} ${readable(item.name)}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const evidenceIds = new Set(result.evidence.map((item) => item.id));
  const execution = records(result.details.execution);
  const completed = execution.filter((item) => item.status === "completed");
  const skipped = execution.filter((item) => item.status === "skipped");
  const unsupported = resources.filter(
    (item) => item.supported === false,
  ).length;
  const cloudTabs = [
    ["checks", "配置检查"],
    ["resources", "资源清单"],
  ] as const;
  return (
    <>
      <div className="cloud-input-note">
        <Cloud size={19} />
        <p>
          本次审查依据上传的云配置或合成样例。检查描述配置条件，不表示资源已部署或风险已被利用；未知值会保留为“信息不足”。
        </p>
      </div>
      <section className="cloud-results-brief" aria-label="云配置覆盖摘要">
        <span className="eyebrow">OFFLINE / REVIEW COVERAGE</span>
        <h3>
          {resources.length} 个配置资源 · {checks.length} 项实际检查
        </h3>
        <div className="cloud-results-counts">
          {["review", "unknown", "pass", "not_applicable"].map((state) => (
            <button
              type="button"
              key={state}
              aria-pressed={status === state}
              onClick={() => {
                setTab("checks");
                setResource("all");
                setSearch("");
                setStatus(status === state ? "all" : state);
                setLimit(30);
              }}
            >
              <strong>
                {checks.filter((check) => check.status === state).length}
              </strong>
              <span>{labels[state]}</span>
            </button>
          ))}
        </div>
        <p className="cloud-guide-note">
          本次执行：
          {completed
            .map((item) => textValue(item.label) || textValue(item.id))
            .join("、") || "历史结果未保存执行组"}
          {skipped.length > 0
            ? `；未选择：${skipped.map((item) => textValue(item.label) || textValue(item.id)).join("、")}`
            : ""}
          。仅列入清单、无专用规则覆盖的资源：{unsupported} 个。
        </p>
        <p className="cloud-guide-note">
          未知字段先补证据，待复核项先确认适用条件。静态通过不代表公网不可达、完整
          IAM 权限安全或云端已生效；实际环境仍需另行验收。
        </p>
      </section>
      <div className="web-workspace-nav">
        <div className="web-inline-tabs" role="tablist" aria-label="云配置结果">
          {cloudTabs.map(([id, label], index) => (
            <button
              key={id}
              id={`cloud-tab-${id}`}
              role="tab"
              aria-selected={tab === id}
              aria-controls="cloud-result-panel"
              tabIndex={tab === id ? 0 : -1}
              onClick={() => {
                setTab(id);
                setSearch("");
              }}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % cloudTabs.length
                    : event.key === "ArrowLeft"
                      ? (index + cloudTabs.length - 1) % cloudTabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? cloudTabs.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                const target = cloudTabs[next];
                if (target) {
                  setTab(target[0]);
                  setSearch("");
                  document.getElementById(`cloud-tab-${target[0]}`)?.focus();
                }
              }}
            >
              {label}{" "}
              <span>{id === "checks" ? checks.length : resources.length}</span>
            </button>
          ))}
        </div>
      </div>
      <section
        className="result-section cloud-results"
        role="tabpanel"
        id="cloud-result-panel"
        aria-labelledby={`cloud-tab-${tab}`}
      >
        <div className="result-section-heading">
          <div>
            <span className="eyebrow">
              CLOUD CONFIGURATION / SAVED EVIDENCE
            </span>
            <h3>{tab === "checks" ? "配置检查" : "资源清单"}</h3>
          </div>
          <SearchField
            value={search}
            onChange={(value) => {
              setSearch(value);
              setLimit(30);
            }}
            placeholder="搜索资源或检查项"
            label="搜索云配置结果"
          />
        </div>
        {tab === "checks" ? (
          <>
            <div className="web-filter-bar">
              <label>
                检查状态
                <select
                  aria-label="云检查状态"
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value);
                    setLimit(30);
                  }}
                >
                  <option value="all">全部状态</option>
                  {Object.entries(labels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                资源
                <select
                  aria-label="云检查资源"
                  value={resource}
                  onChange={(event) => {
                    setResource(event.target.value);
                    setLimit(30);
                  }}
                >
                  <option value="all">全部资源</option>
                  {resources.map((item) => (
                    <option key={textValue(item.id)} value={textValue(item.id)}>
                      {readable(item.address || item.name)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="web-check-list">
              {matches.slice(0, limit).map((item, index) => (
                <details
                  className="web-check"
                  data-cloud-rule={textValue(item.id)}
                  key={`${textValue(item.id)}-${textValue(item.resource_id)}-${index}`}
                >
                  <summary>
                    <span
                      className={`check-state check-${textValue(item.status)}`}
                    >
                      {labels[textValue(item.status)] || readable(item.status)}
                    </span>
                    <div>
                      <strong>{readable(item.title)}</strong>
                      <small>
                        {readable(
                          resources.find((row) => row.id === item.resource_id)
                            ?.address || item.resource_id,
                        )}
                      </small>
                    </div>
                    <span className="mono">{readable(item.severity)}</span>
                    <ChevronDown size={14} />
                  </summary>
                  <div className="web-check-body">
                    <p>{readable(item.description)}</p>
                    <p className="recommendation">
                      {readable(item.recommendation)}
                    </p>
                    <details className="raw-record">
                      <summary>查看配置依据</summary>
                      <JsonData
                        data={isRecord(item.evidence) ? item.evidence : {}}
                      />
                    </details>
                    {strings(item.evidence_ids)
                      .filter((id) => evidenceIds.has(id))
                      .map((id) => (
                        <button
                          className="text-button"
                          key={id}
                          onClick={() => onEvidence(id)}
                        >
                          查看原始证据 <ArrowRight size={13} />
                        </button>
                      ))}
                    <CloudGuidance value={item.guidance} />
                  </div>
                </details>
              ))}
            </div>
            {!matches.length && (
              <p className="inline-empty">没有符合当前筛选的检查项。</p>
            )}
            {matches.length > limit && (
              <button
                className="text-button"
                onClick={() => setLimit(limit + 30)}
              >
                展开更多检查 ↓
              </button>
            )}
          </>
        ) : (
          <div className="cloud-resource-list">
            {selectedResources.map((item) => (
              <details className="cloud-resource" key={textValue(item.id)}>
                <summary>
                  <Cloud size={17} />
                  <div>
                    <strong>{readable(item.address || item.name)}</strong>
                    <small>{readable(item.type)}</small>
                  </div>
                  <span className="subtle-tag">
                    {item.supported === true
                      ? "可审查资源"
                      : item.supported === false
                        ? "未覆盖资源"
                        : "支持状态未记录"}
                  </span>
                  <ChevronDown size={14} />
                </summary>
                <div>
                  <p className="mono">{readable(item.source_pointer)}</p>
                  <JsonData data={item} />
                  {strings(item.evidence_ids)
                    .filter((id) => evidenceIds.has(id))
                    .map((id) => (
                      <button
                        key={id}
                        className="text-button"
                        onClick={() => onEvidence(id)}
                      >
                        查看配置证据 <ArrowRight size={13} />
                      </button>
                    ))}
                </div>
              </details>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
