import { Assets } from "./components/Assets";
import { Collaboration } from "./components/Collaboration";
import { GettingStarted } from "./components/GettingStarted";
import { LocalLab } from "./components/LocalLab";
import { NewJob } from "./components/NewJob";
import { SourceBadge } from "./components/SourceBadge";
import { AIPreferences } from "./components/ai/AIPreferences";
import { useJobs } from "./hooks/useJobs";
import { api } from "./lib/api";
import {
  initialAssetId,
  initialCaseId,
  initialEngagementId,
  initialId,
  jobAssetKind,
  routeView,
} from "./lib/hash-route";
import type { View } from "./lib/hash-route";
import { matchesSource, sourceOfJob } from "./lib/inspection-source";
import { moduleLabel } from "./lib/types";
import type { Asset, Job, ModuleId, ModuleSpec } from "./lib/types";
import { useCallback, useEffect, useState } from "react";
import { Overview } from "./components/Overview";
import { JobDetail } from "./components/JobDetail";
import {
  BookOpen,
  Cloud,
  FlaskConical,
  FolderOpen,
  GitCompareArrows,
  Globe2,
  LayoutDashboard,
  Menu,
  Plug2,
  Plus,
  Server,
  Smartphone,
} from "lucide-react";

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
  const [announcement, setAnnouncement] = useState("");
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
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
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
            {jobs.length > 0 && (
              <span className="nav-count">{jobs.length}</span>
            )}
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
            {jobs.some((job) => jobAssetKind(job) === "android") && (
              <span className="nav-count">
                {jobs.filter((job) => jobAssetKind(job) === "android").length}
              </span>
            )}
          </button>
          <button
            className={view === "web" && !selectedId ? "active" : ""}
            onClick={() => navigate("web")}
          >
            <Globe2 size={17} />
            <span>Web</span>
            {jobs.some((job) => jobAssetKind(job) === "website") && (
              <span className="nav-count">
                {jobs.filter((job) => jobAssetKind(job) === "website").length}
              </span>
            )}
          </button>
          <button
            className={view === "cloud" && !selectedId ? "active" : ""}
            onClick={() => navigate("cloud")}
          >
            <Cloud size={17} />
            <span>云资产</span>
            {jobs.some((job) => jobAssetKind(job) === "cloud") && (
              <span className="nav-count">
                {jobs.filter((job) => jobAssetKind(job) === "cloud").length}
              </span>
            )}
          </button>
          <button
            className={view === "host" && !selectedId ? "active" : ""}
            onClick={() => navigate("host")}
          >
            <Server size={17} />
            <span>主机防御</span>
            {jobs.some((job) => jobAssetKind(job) === "host") && (
              <span className="nav-count">
                {jobs.filter((job) => jobAssetKind(job) === "host").length}
              </span>
            )}
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
              announce={setAnnouncement}
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
