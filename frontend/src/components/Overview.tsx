import { SourceBadge } from "../components/SourceBadge";
import { jobAssetKind } from "../lib/hash-route";
import type { View } from "../lib/hash-route";
import { matchesSource, sourceOfJob } from "../lib/inspection-source";
import {
  dateLabel,
  isActive,
  moduleLabel,
  statusLabelText,
} from "../lib/types";
import type { Job, ModuleSpec } from "../lib/types";
import { useEffect, useState } from "react";
import {
  Empty,
  ErrorBox,
  Loading,
  ProgressBar,
  SearchField,
  StatusTag,
} from "../components/Common";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  CheckCircle2,
  CircleHelp,
  Cloud,
  FolderOpen,
  Globe2,
  LoaderCircle,
  RefreshCw,
  Server,
  Smartphone,
} from "lucide-react";

export function Overview({
  view,
  jobs,
  total,
  loadingMore,
  loadMore,
  loading,
  error,
  refresh,
  modules,
  module,
  create,
  open,
}: {
  view: View;
  jobs: Job[];
  total: number;
  loadingMore: boolean;
  loadMore: () => void;
  loading: boolean;
  error: string;
  refresh: () => void;
  modules: ModuleSpec[];
  module?: ModuleSpec;
  create: () => void;
  open: (job: Job) => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sourceScope, setSourceScope] = useState("work");
  useEffect(() => {
    setSourceScope("work");
    setSearch("");
    setStatus("all");
  }, [view]);
  const scoped = jobs.filter(
    (job) =>
      (view === "all" ||
        jobAssetKind(job) === (view === "web" ? "website" : view)) &&
      matchesSource(sourceOfJob(job), sourceScope),
  );
  const selected = scoped.filter(
    (job) =>
      (status === "all" || job.status === status) &&
      `${job.name} ${job.id} ${job.module}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const completed = scoped.filter((job) => job.status === "completed");
  const current = scoped.filter(isActive);
  return (
    <>
      <section className="overview-heading">
        <div>
          <div className="eyebrow">
            {view === "all"
              ? "OVERVIEW / 工作区"
              : `${view.toUpperCase()} / ANALYSIS MODULE`}
          </div>
          <h1>
            {view === "all"
              ? "检查防御状态，跟进每一项整改。"
              : view === "host"
                ? "主机基线与日志复核。"
                : view === "android"
                  ? "Android 静态检查。"
                  : view === "cloud"
                    ? "云配置与服务检查。"
                    : "网站响应与配置检查。"}
            <span>↗</span>
          </h1>
          <p>
            {module?.description ||
              (view === "all"
                ? "从待复核的配置与日志线索开始，核对证据、处理偏差、保存复测。主机、应用、网站和云配置共用可追溯记录。"
                : view === "host"
                  ? "导入主机配置或日志，查看有限规则的依据与覆盖缺口；没有持续监控或远程命令执行。"
                  : view === "android"
                    ? "检查组件、深链、WebView 与候选数据路径，逐步查看保存的源码。"
                    : view === "cloud"
                      ? "审查上传的资源配置与权限策略，保留未知条件与原始字段依据。"
                      : "执行有边界的 HTTP 探测，或导入已有资产，整理指纹和候选调查方向。")}
          </p>
        </div>
        <div className="workspace-seal" aria-hidden="true">
          <span>R—S</span>
          <svg viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="40" />
            <path d="M12 50h76M50 12v76M23 70h22V31h27v29h15" />
            <circle className="seal-point" cx="72" cy="31" r="4" />
          </svg>
          <small>INSPECT / RECORD / REVIEW</small>
        </div>
      </section>
      {view === "all" && (
        <ol className="defense-workflow" aria-label="防御工作流程">
          <li>
            <span>01 / REVIEW</span>
            <h3>先处理待复核项</h3>
            <p>从配置与日志线索回到证据，确认检查范围和未知条件。</p>
          </li>
          <li>
            <span>02 / HARDEN</span>
            <h3>记录加固决定</h3>
            <p>
              将需要跟进的条目纳入验证与整改，保留负责人、处理说明和例外依据。
            </p>
          </li>
          <li>
            <span>03 / RETEST</span>
            <h3>用新资料复测</h3>
            <p>
              保留原始输入，比较同主机、同规则的新结果，再由你记录关闭结论。
            </p>
          </li>
        </ol>
      )}
      <section className="workspace-stats" aria-label="任务统计">
        <div>
          <span>
            <FolderOpen size={14} />
            分析记录
          </span>
          <strong>{scoped.length.toString().padStart(2, "0")}</strong>
          <small>
            {jobs.length < total
              ? "当前已载入的模块记录"
              : "当前工作区的模块记录"}
          </small>
        </div>
        <div>
          <span>
            <Activity size={14} />
            正在执行
          </span>
          <strong>{current.length.toString().padStart(2, "0")}</strong>
          <small>已载入记录中的执行任务</small>
        </div>
        <div>
          <span>
            <CheckCircle2 size={14} />
            已完成
          </span>
          <strong>{completed.length.toString().padStart(2, "0")}</strong>
          <small>已载入记录中的完成任务</small>
        </div>
        <div>
          <span>
            <Boxes size={14} />
            可用模块
          </span>
          <strong>
            {(view === "all"
              ? modules.length
              : modules.filter((item) => item.id === view).length
            )
              .toString()
              .padStart(2, "0")}
          </strong>
          <small>
            {view === "all"
              ? modules.map((item) => item.name).join(" / ") || "等待模块信息"
              : module?.capabilities.slice(0, 2).join(" / ") ||
                "模块化执行与证据查询"}
          </small>
        </div>
      </section>
      {view !== "all" && module && (
        <div className="capability-strip">
          <span className="mono">CAPABILITIES</span>
          {module.capabilities.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      )}
      <section className="jobs-section">
        <div className="section-title">
          <div>
            <span className="eyebrow">ANALYSIS RECORDS</span>
            <h2>
              分析记录<span>{scoped.length}</span>
            </h2>
          </div>
          <button className="text-button" onClick={refresh}>
            <RefreshCw size={13} />
            刷新
          </button>
        </div>
        <div className="jobs-toolbar">
          <label className="source-scope-filter">
            来源
            <select
              aria-label="分析记录来源"
              value={sourceScope}
              onChange={(event) => setSourceScope(event.target.value)}
            >
              <option value="work">手动输入</option>
              <option value="demo">示例</option>
              <option value="training">本地教学</option>
              <option value="all">全部来源</option>
            </select>
          </label>
          <div
            className="status-filters"
            role="group"
            aria-label="按任务状态筛选"
          >
            {[
              ["all", "全部"],
              ["running", "执行中"],
              ["completed", "已完成"],
              ["failed", "失败"],
            ].map(([value, label]) => (
              <button
                key={value}
                aria-pressed={status === value}
                onClick={() => setStatus(value || "all")}
              >
                {label}
              </button>
            ))}
          </div>
          <SearchField
            value={search}
            onChange={setSearch}
            placeholder="搜索名称或任务 ID"
            label="搜索分析任务"
          />
        </div>
        {error && <ErrorBox retry={refresh}>{error}</ErrorBox>}
        {loading ? (
          <Loading label="正在读取本地任务…" />
        ) : !scoped.length ? (
          <Empty
            title="还没有分析任务"
            detail={
              view === "web"
                ? "输入一个自有 URL 或导入资产文件，也可以先运行离线样例。"
                : "运行一个源码样例，或上传 APK，开始检查代码和路径。"
            }
            action={
              <button className="button button-primary" onClick={create}>
                新建检查
                <ArrowRight size={15} />
              </button>
            }
          />
        ) : !selected.length ? (
          <Empty title="没有匹配的记录" detail="换一个关键词或状态筛选。" />
        ) : (
          <div className="table-scroll">
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>任务 / 模块</th>
                  <th>状态</th>
                  <th>进度与消息</th>
                  <th>创建时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selected.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <button className="job-name" onClick={() => open(job)}>
                        {jobAssetKind(job) === "android" ? (
                          <Smartphone size={17} />
                        ) : jobAssetKind(job) === "host" ? (
                          <Server size={17} />
                        ) : jobAssetKind(job) === "cloud" ? (
                          <Cloud size={17} />
                        ) : (
                          <Globe2 size={17} />
                        )}
                        <span>
                          <strong>{job.name}</strong>
                          <SourceBadge source={sourceOfJob(job)} />
                          <small>
                            {jobAssetKind(job) === "cloud"
                              ? "云资产"
                              : moduleLabel[job.module]}{" "}
                            / {job.id.slice(0, 12)}
                          </small>
                        </span>
                      </button>
                    </td>
                    <td>
                      <StatusTag status={job.status} />
                    </td>
                    <td className="job-progress-cell">
                      {isActive(job) ? (
                        <ProgressBar job={job} />
                      ) : (
                        <span className="job-message">
                          {job.error?.message ||
                            job.message ||
                            statusLabelText(job.status)}
                        </span>
                      )}
                    </td>
                    <td className="mono table-date">
                      {dateLabel(job.created_at)}
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        onClick={() => open(job)}
                        aria-label={`打开任务 ${job.name}`}
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && total > 0 && (
          <div className="history-pagination">
            <span>
              工作区已载入 {jobs.length} / {total} 条 · 当前筛选{" "}
              {selected.length} 条
              {jobs.length < total ? " · 统计与搜索仅覆盖已载入记录" : ""}
            </span>
            {jobs.length < total && (
              <button
                type="button"
                className="text-button"
                disabled={loadingMore}
                onClick={loadMore}
              >
                {loadingMore ? (
                  <LoaderCircle size={13} className="spin" />
                ) : (
                  <ArrowDown size={13} />
                )}
                {loadingMore ? "正在读取历史" : "加载更多历史记录"}
              </button>
            )}
          </div>
        )}
      </section>
      <div className="workspace-note">
        <CircleHelp size={15} />
        <p>
          分析输出分为原始证据、观察项和候选路径。候选关系及规则提示需要复核，不能直接视为漏洞已确认。
        </p>
      </div>
    </>
  );
}
