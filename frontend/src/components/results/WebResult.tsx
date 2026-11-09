import { useEffect, useState } from "react";
import { ArrowRight, ChevronDown, Globe2 } from "lucide-react";
import { useDialog } from "../../hooks/useDialog";
import { api } from "../../lib/api";
import { GOTO_SECTION_EVENT } from "../../lib/section-nav";
import type { Data, Job, ModuleResult } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { Empty, KeyValues, SearchField } from "../Common";
import { Observations } from "./Observations";
import { JsonData } from "./JsonData";
import { WebChecks, checkCount } from "./WebChecks";
import { WebPages, PageProfile } from "./WebPage";
import { WebCompare } from "./WebCompare";
import { WebAdvisory } from "../ai/WebAdvisory";
import { JobControlGuides } from "./JobControlGuides";

const views = [
  ["assets", "资产与响应"],
  ["checks", "配置检查"],
  ["guides", "配置实施指南"],
  ["pages", "页面画像"],
  ["compare", "历史对比"],
  ["ai", "AI 研判"],
] as const;
type WebView = (typeof views)[number][0];

export function WebResult({
  job,
  result,
  onEvidence,
}: {
  job: Job;
  result: ModuleResult;
  onEvidence: (id: string) => void;
}) {
  const assets = records(result.details.assets);
  const paths = records(result.details.paths);
  const execution = records(result.details.execution);
  const skipped = (id: string) =>
    execution.some((item) => item.id === id && item.status === "skipped");
  const [search, setSearch] = useState("");
  const [panel, setPanel] = useState<WebView>("assets");
  const [assetFilter, setAssetFilter] = useState("all");
  const [selected, setSelected] = useState<Data | null>(null);
  const modalRef = useDialog(selected !== null, () => setSelected(null));
  const matches = assets.filter((asset) => {
    const status = Number(asset.status_code ?? asset.status);
    const statusMatch =
      assetFilter === "all" ||
      (assetFilter === "review" && checkCount(asset, "review") > 0) ||
      (assetFilter === "error" && Boolean(asset.error)) ||
      (assetFilter === "2xx" && status >= 200 && status < 300) ||
      (assetFilter === "3xx" && status >= 300 && status < 400) ||
      (assetFilter === "4xx" && status >= 400 && status < 500) ||
      (assetFilter === "5xx" && status >= 500 && status < 600);
    return (
      statusMatch &&
      Object.values(asset).some(
        (value) =>
          typeof value === "string" &&
          value.toLowerCase().includes(search.toLowerCase()),
      )
    );
  });
  const [shown, setShown] = useState(50);
  useEffect(() => {
    setShown(50);
  }, [search, assetFilter]);
  useEffect(() => {
    const goto = (event: WindowEventMap[typeof GOTO_SECTION_EVENT]) => {
      const target = event.detail;
      if (target === "result-section-checks") setPanel("checks");
      else if (
        target === "result-section-assets" ||
        target === "result-section-observations" ||
        target === "result-section-paths"
      ) {
        setPanel("assets");
      }
    };
    window.addEventListener(GOTO_SECTION_EVENT, goto);
    return () => window.removeEventListener(GOTO_SECTION_EVENT, goto);
  }, []);
  return (
    <>
      <div className="web-workspace-nav">
        <div
          className="web-inline-tabs"
          role="tablist"
          aria-label="Web 分析视图"
        >
          {views.map(([id, label], index) => (
            <button
              key={id}
              id={`web-${job.id}-tab-${id}`}
              role="tab"
              aria-selected={panel === id}
              aria-controls={`web-${job.id}-panel`}
              tabIndex={panel === id ? 0 : -1}
              onClick={() => setPanel(id)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % views.length
                    : event.key === "ArrowLeft"
                      ? (index + views.length - 1) % views.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? views.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                const nextView = views[next];
                if (nextView) {
                  setPanel(nextView[0]);
                  document
                    .getElementById(`web-${job.id}-tab-${nextView[0]}`)
                    ?.focus();
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <a
          className="text-button web-csv"
          href={api.exportUrl(job.id, "csv")}
          download
        >
          资产 CSV ↗
        </a>
      </div>
      <div
        role="tabpanel"
        id={`web-${job.id}-panel`}
        aria-labelledby={`web-${job.id}-tab-${panel}`}
      >
        {panel === "ai" && (
          <WebAdvisory jobId={job.id} onEvidence={onEvidence} />
        )}
        {panel === "guides" &&
          (job.asset_id &&
          (job.asset_snapshot?.kind === "website" ||
            (job.asset_snapshot?.kind === "cloud" &&
              job.asset_snapshot.source.profile_id === "cloud-external")) &&
          job.asset_snapshot.source.mode === "probe" ? (
            <JobControlGuides jobId={job.id} onEvidence={onEvidence} />
          ) : (
            <p className="scope-note">
              实施指南需要已保存网站或云服务地址的真实 HTTP
              检查。导入、合成样例和离线云配置不会被补记为网络实测。
            </p>
          ))}
        {panel === "assets" && (
          <>
            <section
              className="result-section"
              id="result-section-assets"
              tabIndex={-1}
            >
              {assets.length > 0 &&
                assets.every((asset) =>
                  String(
                    isRecord(asset.error)
                      ? textValue(asset.error.message)
                      : readable(asset.error),
                  ).includes("outside the selected network scope"),
                ) && (
                  <p className="scope-note" role="alert">
                    本次目标因内网限制未采集：目标属于本机/内网地址。请在“新建检查”第
                    2 步勾选「包含我的本机或内网地址」后重新分析。
                  </p>
                )}
              <div className="result-section-heading">
                <div>
                  <span className="eyebrow">ASSET INVENTORY</span>
                  <h3>
                    资产与响应 <span>{assets.length}</span>
                  </h3>
                </div>
                <SearchField
                  value={search}
                  onChange={setSearch}
                  label="搜索 Web 资产"
                  placeholder="搜索 URL、标题或技术"
                />
              </div>
              {!assets.length ? (
                <Empty
                  title="没有资产记录"
                  detail="查看执行日志和观察项，确认输入或探测结果。"
                />
              ) : (
                <>
                  <div className="web-filter-bar">
                    <label>
                      响应筛选
                      <select
                        aria-label="按资产响应筛选"
                        value={assetFilter}
                        onChange={(event) => setAssetFilter(event.target.value)}
                      >
                        <option value="all">全部资产</option>
                        <option value="review">含待复核检查</option>
                        <option value="error">请求失败</option>
                        <option value="2xx">2xx 响应</option>
                        <option value="3xx">3xx 响应</option>
                        <option value="4xx">4xx 响应</option>
                        <option value="5xx">5xx 响应</option>
                      </select>
                    </label>
                  </div>
                  <div className="table-scroll">
                    <table className="asset-table">
                      <thead>
                        <tr>
                          <th>目标 / 标题</th>
                          <th>响应</th>
                          <th>技术 / 分类</th>
                          <th>待复核</th>
                          <th>耗时</th>
                          <th aria-label="查看" />
                        </tr>
                      </thead>
                      <tbody>
                        {matches.slice(0, shown).map((asset, index) => {
                          const status = asset.status_code ?? asset.status;
                          const imported =
                            asset.reachability_source === "imported_unverified";
                          return (
                            <tr
                              key={
                                textValue(asset.id) ||
                                `${readable(asset.url || asset.host)}-${index}`
                              }
                            >
                              <td>
                                <button
                                  className="asset-name"
                                  onClick={() => setSelected(asset)}
                                >
                                  <Globe2 size={13} />
                                  <span>
                                    {readable(
                                      asset.url || asset.host || asset.target,
                                    )}
                                    <small>{readable(asset.title)}</small>
                                  </span>
                                </button>
                              </td>
                              <td>
                                <span
                                  className={`http-status ${Number(status) >= 400 ? "bad" : ""}`}
                                >
                                  {readable(status)}
                                </span>
                                {imported && <small>历史导入 / 未复测</small>}
                                {Boolean(asset.error) && (
                                  <small className="asset-error">
                                    {isRecord(asset.error)
                                      ? textValue(asset.error.message)
                                      : readable(asset.error)}
                                  </small>
                                )}
                              </td>
                              <td>
                                <span>
                                  {readable(asset.tech || asset.server)}
                                </span>
                                <small>{readable(asset.category)}</small>
                              </td>
                              <td className="mono">
                                {Array.isArray(asset.checks) ? (
                                  <span
                                    className={`check-state ${checkCount(asset, "review") ? "check-review" : "check-pass"}`}
                                  >
                                    {checkCount(asset, "review")}
                                  </span>
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                              <td className="mono">
                                {typeof asset.response_time_ms === "number"
                                  ? `${asset.response_time_ms} ms`
                                  : typeof asset.elapsed_ms === "number"
                                    ? `${asset.elapsed_ms} ms`
                                    : readable(asset.duration_ms)}
                              </td>
                              <td>
                                <button
                                  className="icon-button"
                                  onClick={() => setSelected(asset)}
                                  aria-label={`查看 ${readable(asset.url || asset.host)}`}
                                >
                                  <ArrowRight size={15} />
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {!matches.length && (
                    <p className="inline-empty">没有匹配的资产。</p>
                  )}
                  <div className="table-footer">
                    <span>
                      显示 {Math.min(matches.length, shown)} / {matches.length}{" "}
                      条
                    </span>
                    {matches.length > shown && (
                      <button onClick={() => setShown(shown + 50)}>
                        再显示 50 条 ↓
                      </button>
                    )}
                  </div>
                </>
              )}
            </section>
            <Observations
              observations={result.observations}
              onEvidence={onEvidence}
            />
            <CandidatePaths paths={paths} />
          </>
        )}
        {panel === "checks" &&
          (skipped("headers") && skipped("page") ? (
            <p className="scope-note">
              本次未选择响应配置与页面检查，没有执行这些规则。
            </p>
          ) : (
            <WebChecks assets={assets} onEvidence={onEvidence} />
          ))}
        {panel === "pages" &&
          (skipped("page") ? (
            <p className="scope-note">
              本次未选择页面表单与资源检查，没有解析页面画像。
            </p>
          ) : (
            <WebPages assets={assets} onEvidence={onEvidence} />
          ))}
        {panel === "compare" && (
          <WebCompare job={job} onEvidence={onEvidence} />
        )}
      </div>
      {selected && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelected(null);
          }}
        >
          <div
            className="asset-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="资产响应详情"
            ref={modalRef}
          >
            <header>
              <div>
                <span className="eyebrow">ASSET DETAIL</span>
                <h3>
                  {readable(selected.url || selected.host || selected.target)}
                </h3>
              </div>
              <button
                className="icon-button"
                onClick={() => setSelected(null)}
                aria-label="关闭资产详情"
              >
                ×
              </button>
            </header>
            <p className="section-description">{readable(selected.title)}</p>
            {isRecord(selected.page) && (
              <details className="asset-detail-group">
                <summary>页面画像与 Cookie 属性</summary>
                <PageProfile asset={selected} />
              </details>
            )}
            {records(selected.checks).length > 0 && (
              <details className="asset-detail-group">
                <summary>
                  配置检查 · {checkCount(selected, "review")} 项待复核
                </summary>
                <WebChecks
                  assets={[selected]}
                  onEvidence={(id) => {
                    setSelected(null);
                    onEvidence(id);
                  }}
                />
              </details>
            )}
            <details className="asset-detail-group" open>
              <summary>响应与原始字段</summary>
              <KeyValues
                data={Object.fromEntries(
                  Object.entries(selected).filter(
                    ([key]) => !["checks", "page", "cookies"].includes(key),
                  ),
                )}
              />
            </details>
            {strings(selected.evidence_ids).map((id) => (
              <button
                className="text-button"
                key={id}
                onClick={() => {
                  setSelected(null);
                  onEvidence(id);
                }}
              >
                查看原始证据 ↗
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function CandidatePaths({ paths }: { paths: Data[] }) {
  const [limit, setLimit] = useState(10);
  return (
    <section className="result-section" id="result-section-paths" tabIndex={-1}>
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">INVESTIGATION HYPOTHESES</span>
          <h3>
            候选调查路径 <span>{paths.length}</span>
          </h3>
        </div>
        <span className="subtle-tag">待验证</span>
      </div>
      <p className="section-description">
        由资产指纹和规则推导的调查顺序。前置条件、成功信号仍需逐步验证。
      </p>
      {!paths.length ? (
        <p className="inline-empty">当前规则没有生成候选路径。</p>
      ) : (
        <div className="candidate-paths">
          {paths.slice(0, limit).map((path, index) => (
            <details key={textValue(path.id) || index}>
              <summary>
                <span className="mono">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <strong>
                    {readable(
                      path.title ||
                        path.chain ||
                        path.name ||
                        path.target ||
                        path.host,
                    )}
                  </strong>
                  <small>
                    {readable(path.host || path.asset || path.target)}
                  </small>
                </div>
                <ChevronDown size={15} />
              </summary>
              <div className="candidate-body">
                {records(path.steps).map((step, stepNumber) => (
                  <div
                    className="investigation-step"
                    key={textValue(step.id) || stepNumber}
                  >
                    <span className="mono">
                      {String(stepNumber + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <h4>{readable(step.name)}</h4>
                      <p>{readable(step.action)}</p>
                      {Boolean(step.success_signal) && (
                        <p>
                          <strong>验证信号</strong>{" "}
                          {readable(step.success_signal)}
                        </p>
                      )}
                      {strings(step.false_positives).length > 0 && (
                        <p>
                          <strong>排除条件</strong>{" "}
                          {strings(step.false_positives).join("；")}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
                {strings(path.cautions).length > 0 && (
                  <p className="scope-note">
                    {strings(path.cautions).join("；")}
                  </p>
                )}
                <details className="raw-record">
                  <summary>查看原始路径数据</summary>
                  <JsonData data={path} />
                </details>
              </div>
            </details>
          ))}
          {paths.length > limit && (
            <button
              className="text-button"
              onClick={() => setLimit(limit + 10)}
            >
              展开更多路径 ↓
            </button>
          )}
        </div>
      )}
    </section>
  );
}
