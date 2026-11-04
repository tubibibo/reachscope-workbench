import { useEffect, useState } from "react";
import { ArrowRight, GitCompareArrows, LoaderCircle } from "lucide-react";
import { api, errorText } from "../../lib/api";
import type { Job, WebComparison } from "../../lib/types";
import { dateLabel, readable } from "../../lib/types";
import { ErrorBox, Loading } from "../Common";

const statuses: Record<string, string> = {
  added: "本轮新增目标",
  removed: "本轮未包含",
  changed: "存在变化",
  unchanged: "可比字段无变化",
  not_comparable: "请求不可比",
};

const fieldNames: Record<string, string> = {
  reachable: "请求是否完成",
  status_code: "响应状态",
  title: "页面标题",
  server: "服务器",
  ip: "连接 IP",
  final_url: "最终 URL",
  body_sha256: "完整正文摘要",
  checks: "配置检查",
  cookies: "Cookie 属性",
  content_type: "内容类型",
  redirects: "重定向路径",
};

function fieldLabel(field: string): string {
  const label = fieldNames[field];
  if (label) return label;
  const [prefix, ...parts] = field.split(".");
  const groups: Record<string, string> = {
    headers: "响应头",
    checks: "配置检查",
    tls: "TLS",
    page: "页面画像",
  };
  return prefix && groups[prefix]
    ? `${groups[prefix]} · ${parts.join(".")}`
    : field;
}

export function WebCompare({
  job,
  onEvidence,
}: {
  job: Job;
  onEvidence: (id: string) => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [historyRetry, setHistoryRetry] = useState(0);
  const [baseline, setBaseline] = useState("");
  const [requestedBaseline, setRequestedBaseline] = useState("");
  const [run, setRun] = useState(0);
  const [comparison, setComparison] = useState<WebComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [shown, setShown] = useState(30);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setHistoryLoading(true);
    setHistoryError("");
    void api
      .jobs("web", offset, controller.signal)
      .then((response) => {
        if (!active) return;
        setJobs((previous) =>
          Array.from(
            new Map(
              (offset ? [...previous, ...response.items] : response.items).map(
                (item) => [item.id, item],
              ),
            ).values(),
          ),
        );
        setTotal(response.total);
      })
      .catch((failure: unknown) => {
        if (active) setHistoryError(errorText(failure));
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [job.id, offset, historyRetry]);

  useEffect(() => {
    if (!requestedBaseline) {
      setComparison(null);
      setLoading(false);
      setError("");
      return;
    }
    const controller = new AbortController();
    let active = true;
    setComparison(null);
    setLoading(true);
    setError("");
    void api
      .compare(job.id, requestedBaseline, controller.signal)
      .then((result) => {
        if (active) {
          setComparison(result);
          setShown(30);
          setFilter("all");
        }
      })
      .catch((failure: unknown) => {
        if (active) setError(errorText(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [job.id, requestedBaseline, run]);

  const candidates = jobs.filter(
    (item) =>
      item.id !== job.id &&
      item.status === "completed" &&
      item.config.mode === "probe",
  );
  const selectedJob = jobs.find((item) => item.id === baseline);
  const matches =
    comparison?.assets.filter(
      (asset) => filter === "all" || asset.status === filter,
    ) || [];

  return (
    <section className="result-section web-comparison">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">SNAPSHOT COMPARISON</span>
          <h3>历史对比</h3>
        </div>
        <GitCompareArrows size={22} className="web-section-icon" />
      </div>
      <p className="section-description">
        按相同精确 URL
        比较保存的两次探测。状态、响应头、页面与正文摘要的变化可以帮助复查部署；目标缺席不代表服务下线。
      </p>
      {job.config.mode !== "probe" ? (
        <p className="inline-empty">
          仅 HTTP 探测任务可以比较快照。离线样例和文件导入不代表本次站点状态。
        </p>
      ) : (
        <>
          <div className="comparison-picker">
            <label>
              基线记录
              <select
                aria-label="选择比较基线"
                value={baseline}
                onChange={(event) => {
                  setBaseline(event.target.value);
                  setRequestedBaseline("");
                }}
              >
                <option value="">选择一条已完成的 HTTP 探测记录</option>
                {candidates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {dateLabel(item.created_at)} ·{" "}
                    {item.id.slice(0, 6)}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button button-primary"
              disabled={!baseline || loading}
              onClick={() => {
                setRequestedBaseline(baseline);
                setRun((value) => value + 1);
              }}
            >
              {loading ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <GitCompareArrows size={14} />
              )}
              比较快照
            </button>
          </div>
          <div className="comparison-history-info">
            <span>
              已载入 {jobs.length} / {total} 条 Web 记录，{candidates.length}{" "}
              条可选基线
            </span>
            {jobs.length < total && !historyError && (
              <button
                className="text-button"
                disabled={historyLoading}
                onClick={() => setOffset(offset + 100)}
              >
                {historyLoading ? "读取中…" : "再载入 100 条 ↓"}
              </button>
            )}
          </div>
          {historyLoading && jobs.length === 0 && (
            <Loading label="正在读取可比较的任务…" />
          )}
          {historyError && (
            <ErrorBox retry={() => setHistoryRetry((value) => value + 1)}>
              {historyError}
            </ErrorBox>
          )}
          {!historyLoading && !historyError && !candidates.length && (
            <p className="inline-empty">
              已载入范围内没有其他完成的 HTTP 探测。可以先对同一 URL
              再运行一次，或载入更早的记录。
            </p>
          )}
          {error && (
            <ErrorBox retry={() => setRun((value) => value + 1)}>
              {error}
            </ErrorBox>
          )}
          {loading && <Loading label="正在比较已保存的响应…" />}
          {comparison &&
            comparison.baseline_job_id === baseline &&
            requestedBaseline === baseline && (
              <>
                <div className="comparison-records">
                  <div>
                    <span className="eyebrow">BASELINE / 基线</span>
                    <strong>
                      {selectedJob?.name || comparison.baseline_job_id}
                    </strong>
                    <small>
                      {selectedJob ? dateLabel(selectedJob.created_at) : ""}
                    </small>
                  </div>
                  <ArrowRight size={19} />
                  <div>
                    <span className="eyebrow">CURRENT / 本轮</span>
                    <strong>{job.name}</strong>
                    <small>{dateLabel(job.created_at)}</small>
                  </div>
                </div>
                <div className="comparison-totals">
                  {Object.entries(statuses).map(([key, label]) => (
                    <button
                      key={key}
                      aria-pressed={filter === key}
                      onClick={() => {
                        setFilter(filter === key ? "all" : key);
                        setShown(30);
                      }}
                    >
                      <strong>
                        {
                          comparison.summary[
                            key as keyof WebComparison["summary"]
                          ]
                        }
                      </strong>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
                <div className="web-filter-bar">
                  <label>
                    变化类型
                    <select
                      aria-label="按变化类型筛选"
                      value={filter}
                      onChange={(event) => {
                        setFilter(event.target.value);
                        setShown(30);
                      }}
                    >
                      <option value="all">全部类型</option>
                      {Object.entries(statuses).map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="comparison-assets">
                  {matches.slice(0, shown).map((asset) => (
                    <details className="comparison-asset" key={asset.url}>
                      <summary>
                        <span className={`check-state diff-${asset.status}`}>
                          {statuses[asset.status]}
                        </span>
                        <code>{asset.url}</code>
                        <span className="mono">{asset.changes.length} 项</span>
                      </summary>
                      <div className="comparison-asset-body">
                        {asset.changes.length > 0 && (
                          <div className="table-scroll">
                            <table className="diff-table">
                              <thead>
                                <tr>
                                  <th>字段</th>
                                  <th>基线</th>
                                  <th>本轮</th>
                                </tr>
                              </thead>
                              <tbody>
                                {asset.changes.map((change) => (
                                  <tr key={change.field}>
                                    <td>{fieldLabel(change.field)}</td>
                                    <td>
                                      <pre>{readable(change.before)}</pre>
                                    </td>
                                    <td>
                                      <pre>{readable(change.after)}</pre>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                        {asset.notes?.map((note, index) => (
                          <p className="scope-note" key={index}>
                            {note}
                          </p>
                        ))}
                        <div className="observation-meta">
                          <a
                            className="text-button"
                            href={`#/jobs/${comparison.baseline_job_id}`}
                          >
                            打开基线记录 ↗
                          </a>
                          {asset.after_evidence_ids.map((id) => (
                            <button key={id} onClick={() => onEvidence(id)}>
                              查看本轮响应证据 <ArrowRight size={12} />
                            </button>
                          ))}
                        </div>
                      </div>
                    </details>
                  ))}
                </div>
                {!matches.length && (
                  <p className="inline-empty">没有这一类型的变化。</p>
                )}
                <div className="table-footer">
                  <span>
                    显示 {Math.min(shown, matches.length)} / {matches.length} 项
                  </span>
                  {matches.length > shown && (
                    <button onClick={() => setShown(shown + 30)}>
                      再显示 30 项 ↓
                    </button>
                  )}
                </div>
                {comparison.limitations.length > 0 && (
                  <ul className="comparison-limits">
                    {comparison.limitations.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
        </>
      )}
    </section>
  );
}
