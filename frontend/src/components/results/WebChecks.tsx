import { useState } from "react";
import { ArrowRight, ChevronDown, ShieldCheck } from "lucide-react";
import type { Data } from "../../lib/types";
import { severityLabelText } from "../../lib/display-labels";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { JsonData } from "./JsonData";

const labels: Record<string, string> = {
  pass: "满足检查条件",
  review: "待复核",
  info: "记录信息",
  not_applicable: "不适用",
};

export function checkCount(asset: Data, status: string): number {
  return records(asset.checks).filter((check) => check.status === status)
    .length;
}

export function WebChecks({
  assets,
  onEvidence,
}: {
  assets: Data[];
  onEvidence: (id: string) => void;
}) {
  const [status, setStatus] = useState("all");
  const [assetId, setAssetId] = useState("all");
  const [limit, setLimit] = useState(30);
  const checks = assets.flatMap((asset) =>
    records(asset.checks).map((check) => ({ asset, check })),
  );
  const matches = checks.filter(
    ({ asset, check }) =>
      (status === "all" || check.status === status) &&
      (assetId === "all" || textValue(asset.id) === assetId),
  );
  return (
    <section
      className="result-section web-checks"
      id="result-section-checks"
      tabIndex={-1}
    >
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">RESPONSE CONFIGURATION</span>
          <h3>
            配置检查 <span>{checks.length}</span>
          </h3>
        </div>
        <ShieldCheck size={22} className="web-section-icon" />
      </div>
      <p className="section-description">
        根据本次保存的响应检查配置条件。每条都保留观察依据；“满足检查条件”仅描述这一项，“待复核”需要结合业务确认。
      </p>
      {checks.length === 0 ? (
        <p className="inline-empty">
          此记录没有结构化配置检查。文件导入和旧版结果不会被补记为本次探测；可重新创建
          HTTP 探测任务。
        </p>
      ) : (
        <>
          <div className="check-totals" aria-label="配置检查统计">
            {Object.entries(labels).map(([value, label]) => (
              <button
                key={value}
                className={`check-total check-${value}`}
                aria-pressed={status === value}
                onClick={() => {
                  setStatus(status === value ? "all" : value);
                  setLimit(30);
                }}
              >
                <strong>
                  {checks.filter(({ check }) => check.status === value).length}
                </strong>
                <span>{label}</span>
              </button>
            ))}
          </div>
          <div className="web-filter-bar">
            <label>
              检查状态
              <select
                aria-label="按配置检查状态筛选"
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
              资产
              <select
                aria-label="按检查资产筛选"
                value={assetId}
                onChange={(event) => {
                  setAssetId(event.target.value);
                  setLimit(30);
                }}
              >
                <option value="all">全部资产</option>
                {assets
                  .filter((asset) => records(asset.checks).length > 0)
                  .map((asset) => (
                    <option
                      key={textValue(asset.id)}
                      value={textValue(asset.id)}
                    >
                      {readable(asset.url || asset.host)}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <div className="web-check-list">
            {matches.slice(0, limit).map(({ asset, check }, index) => (
              <details
                className="web-check"
                key={`${textValue(asset.id)}-${textValue(check.id) || index}`}
              >
                <summary>
                  <span
                    className={`check-state check-${textValue(check.status)}`}
                  >
                    {labels[textValue(check.status)] || readable(check.status)}
                  </span>
                  <div>
                    <strong>{readable(check.title)}</strong>
                    <small>{readable(asset.url || asset.host)}</small>
                  </div>
                  <span className="web-check-severity mono">
                    {severityLabelText(readable(check.severity))}
                  </span>
                  <ChevronDown size={14} />
                </summary>
                <div className="web-check-body">
                  <p>{readable(check.description)}</p>
                  {Boolean(check.recommendation) && (
                    <p className="recommendation">
                      {readable(check.recommendation)}
                    </p>
                  )}
                  <details className="raw-record">
                    <summary>展开检查依据</summary>
                    <JsonData
                      data={
                        isRecord(check.evidence)
                          ? check.evidence
                          : { value: check.evidence }
                      }
                    />
                  </details>
                  {strings(asset.evidence_ids).map((id) => (
                    <button
                      key={id}
                      className="text-button"
                      onClick={() => onEvidence(id)}
                    >
                      查看响应证据 <ArrowRight size={12} />
                    </button>
                  ))}
                </div>
              </details>
            ))}
          </div>
          {!matches.length && (
            <p className="inline-empty">没有符合条件的配置检查。</p>
          )}
          <div className="table-footer">
            <span>
              显示 {Math.min(matches.length, limit)} / {matches.length} 项
            </span>
            {matches.length > limit && (
              <button onClick={() => setLimit(limit + 30)}>
                再显示 30 项 ↓
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
