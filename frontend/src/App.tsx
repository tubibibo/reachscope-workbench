import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Boxes,
  CheckCircle2,
  Cloud,
  CircleHelp,
  FileCode2,
  FolderOpen,
  Globe2,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  Plus,
  RefreshCw,
  Smartphone,
  Server,
  Square,
  GitCompareArrows,
  Plug2,
  FlaskConical,
} from "lucide-react";
import { api, errorRequestId, errorText } from "./lib/api";
import { useJob, useJobs } from "./hooks/useJobs";
import type { Asset, Job, ModuleId, ModuleSpec } from "./lib/types";
import { dateLabel, isActive, moduleLabel, statusLabelText } from "./lib/types";
import {
  Empty,
  ErrorBox,
  KeyValues,
  LinkButton,
  Loading,
  ProgressBar,
  SearchField,
  StatusTag,
} from "./components/Common";
import { NewJob } from "./components/NewJob";
import { Assets } from "./components/Assets";
import { Collaboration } from "./components/Collaboration";
import { AIPreferences } from "./components/ai/AIPreferences";
import { GettingStarted } from "./components/GettingStarted";
import { LocalLab } from "./components/LocalLab";
import { SourceBadge } from "./components/SourceBadge";
import { matchesSource, sourceOfJob } from "./lib/inspection-source";
import {
  AndroidResult,
  CloudResult,
  HostResult,
  Execution,
  EvidenceView,
  Limitations,
  ResultSummary,
  ResultBrief,
  WebResult,
} from "./components/ResultViews";

type View =
  | "all"
  | "assets"
  | "collaboration"
  | "ai"
  | "guide"
  | "lab"
  | ModuleId;
const routeView = (): View => {
  const hash = window.location.hash;
  if (hash.startsWith("#/settings/ai")) return "ai";
  if (hash.startsWith("#/engagements")) return "collaboration";
  if (hash.startsWith("#/guide")) return "guide";
  if (hash.startsWith("#/lab")) return "lab";
  const module = hash.match(/^#\/modules\/(android|web|cloud|host)$/)?.[1];
  if (module) return module as ModuleId;
  if (hash.startsWith("#/jobs/") || hash === "#/") return "all";
  return "assets";
};
type DetailTab = "result" | "evidence" | "events" | "input";
const decodedId = (value: string): string | null => {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
};
const initialId = () =>
  window.location.hash.startsWith("#/jobs/")
    ? decodedId(window.location.hash.slice(7))
    : null;
const initialAssetId = () =>
  window.location.hash.startsWith("#/assets/")
    ? decodedId(window.location.hash.slice(9))
    : null;
const initialEngagementId = () =>
  window.location.hash.match(/^#\/engagements\/([^/]+)/)?.[1] || null;
const initialCaseId = () =>
  window.location.hash.match(/^#\/engagements\/[^/]+\/cases\/([^/]+)/)?.[1] ||
  null;
const jobAssetKind = (job: Job) =>
  job.asset_snapshot?.kind || (job.module === "web" ? "website" : job.module);

export default function App() {
  const [view, setView] = useState<View>(routeView);
  const [engagementId, setEngagementId] = useState<string | null>(
    initialEngagementId,
  );
  const [caseId, setCaseId] = useState<string | null>(initialCaseId);
  const [assetId, setAssetId] = useState<string | null>(initialAssetId);
  const [assetRefresh, setAssetRefresh] = useState(0);
  const [initialAsset, setInitialAsset] = useState<Asset | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [newJob, setNewJob] = useState(false);
  const [newModule, setNewModule] = useState<ModuleId>("web");
  const [modules, setModules] = useState<ModuleSpec[]>([]);
  const [version, setVersion] = useState("");
  const [connected, setConnected] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const { jobs, total, loading, loadingMore, error, refresh, loadMore } =
    useJobs();
  useEffect(() => {
    let active = true;
    void api
      .modules()
      .then((data) => {
        if (active) setModules(data.items);
      })
      .catch(() => undefined);
    const check = () => {
      void api
        .health()
        .then((health) => {
          if (active) {
            setConnected(health.status === "ok" || health.status === "healthy");
            setVersion(health.version);
          }
        })
        .catch(() => {
          if (active) setConnected(false);
        });
    };
    check();
    const timer = window.setInterval(check, 12000);
    const route = () => {
      setSelectedId(initialId());
      setAssetId(initialAssetId());
      setEngagementId(initialEngagementId());
      setCaseId(initialCaseId());
      if (!initialId()) setView(routeView());
    };
    window.addEventListener("hashchange", route);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("hashchange", route);
    };
  }, []);
  const closeNew = useCallback(() => setNewJob(false), []);
  function openJob(job: Job) {
    window.location.hash = `/jobs/${encodeURIComponent(job.id)}`;
    setSelectedId(job.id);
    setMobileNav(false);
  }
  function navigate(next: View) {
    setView(next);
    setSelectedId(null);
    setAssetId(null);
    setEngagementId(null);
    setCaseId(null);
    window.location.hash =
      next === "ai"
        ? "/settings/ai"
        : next === "collaboration"
          ? "/engagements"
          : next === "assets"
            ? "/assets"
            : next === "guide"
              ? "/guide"
              : next === "lab"
                ? "/lab"
                : next === "all"
                  ? "/"
                  : `/modules/${next}`;
    setMobileNav(false);
  }
  const currentModule = modules.find((item) => item.id === view);
  function openAsset(id: string | null) {
    setSelectedId(null);
    setView("assets");
    setAssetId(id);
    window.location.hash = id ? `/assets/${encodeURIComponent(id)}` : "/assets";
    setMobileNav(false);
  }
  function startCheck(asset?: Asset, module?: ModuleId) {
    setInitialAsset(asset || null);
    setNewModule(
      module ||
        (asset
          ? asset.kind === "website"
            ? "web"
            : asset.kind
          : view === "android" || view === "cloud" || view === "host"
            ? view
            : "web"),
    );
    setNewJob(true);
  }
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        跳到主内容
      </a>
      <aside className={`sidebar ${mobileNav ? "is-open" : ""}`}>
        <a
          href="#/"
          onClick={() => navigate("all")}
          className="brand"
          aria-label="ReachScope 总览"
        >
          <span className="brand-mark">
            <svg viewBox="0 0 28 28" width="26" height="26" aria-hidden="true">
              <path
                d="M2 19V2h17M9 26h17V9M2 2l24 24M9 9h10v10"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            </svg>
          </span>
          <span>
            reachscope<small>WORKBENCH / 本地分析</small>
          </span>
        </a>
        <div className="sidebar-label mono">WORKSPACE</div>
        <nav aria-label="工作台导航">
          <button
            className={view === "lab" && !selectedId ? "active" : ""}
            onClick={() => navigate("lab")}
          >
            <FlaskConical size={17} />
            <span>本地教学</span>
          </button>
          <button
            className={view === "guide" && !selectedId ? "active" : ""}
            onClick={() => navigate("guide")}
          >
            <BookOpen size={17} />
            <span>上手指南</span>
          </button>
          <button
            className={view === "assets" && !selectedId ? "active" : ""}
            onClick={() => navigate("assets")}
          >
            <FolderOpen size={17} />
            <span>我的资产</span>
          </button>
          <button
            className={view === "collaboration" && !selectedId ? "active" : ""}
            onClick={() => navigate("collaboration")}
          >
            <GitCompareArrows size={17} />
            <span>验证与整改</span>
          </button>
          <button
            className={view === "all" && !selectedId ? "active" : ""}
            onClick={() => navigate("all")}
          >
            <LayoutDashboard size={17} />
            <span>分析总览</span>
            <span className="nav-count">{jobs.length}</span>
          </button>
          <button
            className={view === "ai" && !selectedId ? "active" : ""}
            onClick={() => navigate("ai")}
          >
            <Plug2 size={17} />
            <span>AI 接口</span>
          </button>
          <button
            className={view === "android" && !selectedId ? "active" : ""}
            onClick={() => navigate("android")}
          >
            <Smartphone size={17} />
            <span>Android</span>
            <span className="nav-count">
              {jobs.filter((job) => jobAssetKind(job) === "android").length}
            </span>
          </button>
          <button
            className={view === "web" && !selectedId ? "active" : ""}
            onClick={() => navigate("web")}
          >
            <Globe2 size={17} />
            <span>Web</span>
            <span className="nav-count">
              {jobs.filter((job) => jobAssetKind(job) === "website").length}
            </span>
          </button>
          <button
            className={view === "cloud" && !selectedId ? "active" : ""}
            onClick={() => navigate("cloud")}
          >
            <Cloud size={17} />
            <span>云资产</span>
            <span className="nav-count">
              {jobs.filter((job) => jobAssetKind(job) === "cloud").length}
            </span>
          </button>
          <button
            className={view === "host" && !selectedId ? "active" : ""}
            onClick={() => navigate("host")}
          >
            <Server size={17} />
            <span>主机防御</span>
            <span className="nav-count">
              {jobs.filter((job) => jobAssetKind(job) === "host").length}
            </span>
          </button>
        </nav>
        <div className="sidebar-divider" />
        <div className="sidebar-label mono">RECENT / 最近任务</div>
        <div className="recent-jobs">
          {jobs
            .filter((job) => matchesSource(sourceOfJob(job), "work"))
            .slice(0, 5)
            .map((job) => (
              <button
                key={job.id}
                className={job.id === selectedId ? "selected" : ""}
                onClick={() => openJob(job)}
              >
                <span className={`recent-dot status-${job.status}`} />
                <span>{job.name}</span>
                <SourceBadge source={sourceOfJob(job)} />
              </button>
            ))}
          {!jobs.length && <span className="sidebar-empty">尚无分析记录</span>}
        </div>
        <div className="sidebar-bottom">
          <div className="local-indicator">
            <i className={connected ? "online" : ""} />
            <span>{connected ? "本地服务已连接" : "正在连接本地服务"}</span>
          </div>
          <div className="sidebar-version mono">
            <span>v{version || "—"}</span>
            <span>LOCAL FIRST ↗</span>
          </div>
        </div>
      </aside>
      {mobileNav && (
        <button
          className="nav-backdrop"
          aria-label="关闭导航"
          onClick={() => setMobileNav(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="展开导航"
              aria-expanded={mobileNav}
              onClick={() => setMobileNav(!mobileNav)}
            >
              <Menu size={20} />
            </button>
            <span>工作区</span>
            <span className="breadcrumb-slash">/</span>
            <strong>
              {selectedId
                ? "任务详情"
                : view === "assets"
                  ? "我的资产"
                  : view === "guide"
                    ? "上手指南"
                    : view === "lab"
                      ? "本地教学"
                      : view === "ai"
                        ? "AI 接口设置"
                        : view === "collaboration"
                          ? "验证与整改"
                          : view === "all"
                            ? "分析总览"
                            : `${moduleLabel[view]} 模块`}
            </strong>
          </div>
          <div className="topbar-actions">
            <span className="topbar-status">
              <i className={connected ? "online" : ""} />
              {connected ? "LOCAL ENGINE" : "CONNECTING"}
            </span>
            <button
              className="button button-primary"
              onClick={() => startCheck()}
            >
              <Plus size={15} />
              新建检查
            </button>
          </div>
        </header>
        <main className="content" id="main-content" tabIndex={-1}>
          {selectedId ? (
            <JobDetail
              key={selectedId}
              id={selectedId}
              back={() => navigate(view)}
              changed={() => {
                void refresh();
              }}
            />
          ) : view === "ai" ? (
            <AIPreferences />
          ) : view === "guide" ? (
            <GettingStarted
              start={(module) => startCheck(undefined, module)}
              assets={() => navigate("assets")}
              records={() => navigate("all")}
              collaboration={() => navigate("collaboration")}
              ai={() => navigate("ai")}
            />
          ) : view === "lab" ? (
            <LocalLab
              openJob={openJob}
              openAsset={(id) => openAsset(id)}
              openCase={(engagement, id) => {
                window.location.hash = `/engagements/${engagement}/cases/${id}`;
              }}
              changed={() => {
                setAssetRefresh((value) => value + 1);
                void refresh();
              }}
            />
          ) : view === "collaboration" ? (
            <Collaboration
              id={engagementId}
              caseId={caseId}
              open={(id, selectedCase) => {
                setSelectedId(null);
                setEngagementId(id);
                setCaseId(selectedCase || null);
                setView("collaboration");
                window.location.hash = id
                  ? `/engagements/${id}${selectedCase ? `/cases/${selectedCase}` : ""}`
                  : "/engagements";
                setMobileNav(false);
              }}
            />
          ) : view === "assets" ? (
            <Assets
              id={assetId}
              refreshKey={assetRefresh}
              open={openAsset}
              openJob={openJob}
              create={startCheck}
              guide={() => navigate("guide")}
            />
          ) : (
            <Overview
              view={view}
              jobs={jobs}
              total={total}
              loadingMore={loadingMore}
              loadMore={loadMore}
              loading={loading}
              error={error}
              refresh={() => {
                void refresh();
              }}
              modules={modules}
              module={currentModule}
              create={() => startCheck()}
              open={openJob}
            />
          )}
        </main>
        <footer className="app-footer">
          <span>REACHSCOPE / 证据工作台</span>
          <span>数据保存在本机 · 结论可回查到原始依据</span>
          <span className="mono">HOST + ANDROID + WEB + CLOUD</span>
        </footer>
      </div>
      {newJob && (
        <NewJob
          initialModule={newModule}
          initialAsset={initialAsset}
          close={closeNew}
          created={(job) => {
            setNewJob(false);
            setAssetRefresh((value) => value + 1);
            openJob(job);
            void refresh();
          }}
        />
      )}
    </div>
  );
}

function Overview({
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
            记录来源
            <select
              aria-label="分析记录来源"
              value={sourceScope}
              onChange={(event) => setSourceScope(event.target.value)}
            >
              <option value="work">实际输入</option>
              <option value="demo">合成演示</option>
              <option value="training">本地教学 / 实际采集</option>
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

function JobDetail({
  id,
  back,
  changed,
}: {
  id: string;
  back: () => void;
  changed: () => void;
}) {
  const { job, events, error, loading, refresh } = useJob(id);
  const [tab, setTab] = useState<DetailTab>("result");
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionRequestId, setActionRequestId] = useState<string>();
  const retryRequest = useRef<{ id: string; key: string } | null>(null);
  const failedAction = useRef<"cancel" | "retry">("retry");
  const actionBusy = useRef(false);
  const [busy, setBusy] = useState(false);
  async function action(mode: "cancel" | "retry") {
    if (actionBusy.current) return;
    actionBusy.current = true;
    setBusy(true);
    setActionError("");
    setActionRequestId(undefined);
    failedAction.current = mode;
    try {
      if (mode === "retry" && retryRequest.current?.id !== id)
        retryRequest.current = { id, key: crypto.randomUUID() };
      const next =
        mode === "cancel"
          ? await api.cancel(id)
          : await api.retry(id, retryRequest.current!.key);
      changed();
      if (mode === "retry" && next.id !== id)
        window.location.hash = `/jobs/${next.id}`;
      else await refresh();
    } catch (failure) {
      setActionError(errorText(failure));
      setActionRequestId(errorRequestId(failure));
    } finally {
      actionBusy.current = false;
      setBusy(false);
    }
  }
  function showEvidence(evidenceId: string) {
    setSelectedEvidence(evidenceId);
    setTab("evidence");
  }
  if (loading && !job) return <Loading label="正在读取分析任务…" />;
  if (!job)
    return (
      <>
        <button className="back-link" onClick={back}>
          <ArrowLeft size={14} />
          返回任务列表
        </button>
        {error && (
          <ErrorBox
            retry={() => {
              void refresh();
            }}
          >
            {error}
          </ErrorBox>
        )}
      </>
    );
  const result = job.result;
  const tabs: { id: DetailTab; label: string; count?: number }[] = [
    { id: "result", label: "分析结果" },
    { id: "evidence", label: "证据索引", count: result?.evidence.length },
    { id: "events", label: "执行记录", count: events.length },
    { id: "input", label: "输入与配置" },
  ];
  return (
    <>
      <button className="back-link" onClick={back}>
        <ArrowLeft size={14} />
        返回任务列表
      </button>
      <section className="detail-heading">
        <div>
          <span className="eyebrow">
            {jobAssetKind(job) === "cloud" && job.module === "web"
              ? "云服务 HTTP"
              : moduleLabel[job.module].toUpperCase()}{" "}
            / ANALYSIS RECORD
          </span>
          <h1>{job.name}</h1>
          <SourceBadge source={sourceOfJob(job)} />
          <p className="inspection-source-note">{sourceOfJob(job).detail}</p>
          <div className="detail-meta">
            <StatusTag status={job.status} />
            <span className="mono">{job.id}</span>
            <span>{dateLabel(job.created_at)}</span>
            {job.asset_id && (
              <a className="text-button" href={`#/assets/${job.asset_id}`}>
                查看所属资产 <ArrowUpRight size={12} />
              </a>
            )}
          </div>
        </div>
        <div className="detail-actions">
          {result && job.status === "completed" && (
            <>
              <LinkButton href={api.exportUrl(id, "json")}>JSON</LinkButton>
              <LinkButton href={api.exportUrl(id, "html")}>报告</LinkButton>
            </>
          )}
          {isActive(job) ? (
            <button
              className="button button-secondary"
              disabled={busy}
              onClick={() => {
                void action("cancel");
              }}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Square size={12} />
              )}
              取消任务
            </button>
          ) : (
            <button
              className="button button-secondary"
              disabled={busy}
              onClick={() => {
                void action("retry");
              }}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              重新分析
            </button>
          )}
        </div>
      </section>
      {(error || actionError) && (
        <ErrorBox
          requestId={actionError ? actionRequestId : undefined}
          retry={() => {
            if (actionError) void action(failedAction.current);
            else void refresh();
          }}
        >
          {actionError || error}
        </ErrorBox>
      )}
      {isActive(job) && (
        <div className="running-banner">
          <span className="running-icon">
            <LoaderCircle className="spin" size={22} />
          </span>
          <div>
            <strong>
              {job.status === "queued" ? "任务正在等待执行" : "分析正在进行"}
            </strong>
            <ProgressBar job={job} />
          </div>
          <span className="mono">{job.status.toUpperCase()}</span>
        </div>
      )}
      {job.error && (
        <ErrorBox>
          <strong>{job.error.code}</strong> / {job.error.message}
        </ErrorBox>
      )}
      <div className="detail-tabs" role="tablist" aria-label="任务详情">
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.id === "result" ? (
              <Activity size={14} />
            ) : item.id === "evidence" ? (
              <FileCode2 size={14} />
            ) : item.id === "events" ? (
              <BookOpen size={14} />
            ) : (
              <Boxes size={14} />
            )}
            {item.label}
            {item.count !== undefined && <span>{item.count}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="detail-body">
        {tab === "result" &&
          (result ? (
            <>
              <div className="result-target">
                <span className="eyebrow">TARGET / 分析对象</span>
                <code>{result.target}</code>
              </div>
              <ResultSummary result={result} />
              <ResultBrief
                job={job}
                result={result}
                onEvidence={showEvidence}
                onExecution={() => setTab("events")}
              />
              <Execution result={result} />
              {job.module === "android" ? (
                <AndroidResult
                  key={job.id}
                  job={job}
                  result={result}
                  onEvidence={showEvidence}
                />
              ) : job.module === "host" ? (
                <HostResult
                  key={job.id}
                  job={job}
                  result={result}
                  onEvidence={showEvidence}
                />
              ) : job.module === "cloud" ? (
                <CloudResult
                  key={job.id}
                  result={result}
                  onEvidence={showEvidence}
                />
              ) : (
                <WebResult
                  key={job.id}
                  job={job}
                  result={result}
                  onEvidence={showEvidence}
                />
              )}
              <Limitations limitations={result.limitations} />
            </>
          ) : (
            <Empty
              title={
                isActive(job)
                  ? "结果将在分析结束后显示"
                  : job.status === "cancelled"
                    ? "本次任务已取消"
                    : "没有可用的分析结果"
              }
              detail={
                isActive(job)
                  ? "可以切到“执行记录”查看已完成的步骤，离开此页不会中止任务。"
                  : "检查执行记录或输入配置后，可以重新创建一次分析。"
              }
            />
          ))}
        {tab === "evidence" &&
          (result ? (
            <EvidenceView
              result={result}
              selectedId={selectedEvidence}
              select={setSelectedEvidence}
            />
          ) : (
            <Empty
              title="暂时没有保存的证据"
              detail="任务结束后，原始响应或源码证据会显示在这里。"
            />
          ))}
        {tab === "events" && (
          <section className="event-section">
            <div className="result-section-heading">
              <div>
                <span className="eyebrow">EXECUTION JOURNAL</span>
                <h3>
                  执行记录 <span>{events.length}</span>
                </h3>
              </div>
              <button
                className="text-button"
                onClick={() => {
                  void refresh();
                }}
              >
                <RefreshCw size={13} />
                刷新
              </button>
            </div>
            {!events.length ? (
              <p className="inline-empty">尚无执行记录。</p>
            ) : (
              <ol className="event-list">
                {events.map((item) => (
                  <li key={item.id}>
                    <span className={`event-dot level-${item.level}`} />
                    <time className="mono">{dateLabel(item.created_at)}</time>
                    <span className="event-level mono">{item.level}</span>
                    <p>{item.message}</p>
                    <span className="event-progress mono">
                      {item.progress}%
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        )}
        {tab === "input" && (
          <section className="result-section">
            <div className="result-section-heading">
              <div>
                <span className="eyebrow">REPRODUCIBLE INPUT</span>
                <h3>输入与配置</h3>
              </div>
            </div>
            <KeyValues
              data={{
                module: job.module,
                asset:
                  job.asset_snapshot?.name ||
                  (job.asset_id ? job.asset_id : "历史记录未关联资产"),
                status: job.status,
                created_at: job.created_at,
                updated_at: job.updated_at,
              }}
            />
            <pre className="data-block">
              {JSON.stringify(job.config, null, 2)}
            </pre>
            <p className="scope-note">
              重试会使用相同输入创建新的任务，原始分析记录会保留。
            </p>
          </section>
        )}
      </div>
    </>
  );
}
