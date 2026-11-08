import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  FileDown,
  Plus,
  RefreshCw,
  ShieldCheck,
  Target,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  Asset,
  Candidate,
  CaseStatus,
  Engagement,
  Job,
  ReviewCase,
} from "../lib/types";
import { assetKindLabel, dateLabel } from "../lib/types";
import { useDialog } from "../hooks/useDialog";
import { Empty, Loading, SearchField } from "./Common";
import { Failure, caseLabels } from "./CollaborationShared";
import { caseStatusLabel } from "./CollaborationShared";
import type { RoleView } from "./CollaborationShared";
import { CaseDetail } from "./CaseDetail";

type OpenWorkspace = (id: string | null, caseId?: string | null) => void;
function TeamSwitch({
  view,
  set,
}: {
  view: RoleView;
  set: (value: RoleView) => void;
}) {
  return (
    <div className="team-switch" role="tablist" aria-label="红蓝工作视角">
      {(
        [
          ["red", "红队 · 验证线索", Target],
          ["blue", "蓝队 · 整改复测", ShieldCheck],
        ] as const
      ).map(([value, label, Icon], index) => (
        <button
          key={value}
          role="tab"
          aria-selected={view === value}
          tabIndex={view === value ? 0 : -1}
          onClick={() => set(value)}
          onKeyDown={(event) => {
            if (
              ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
            ) {
              event.preventDefault();
              const next =
                event.key === "Home"
                  ? "red"
                  : event.key === "End"
                    ? "blue"
                    : index === 0
                      ? "blue"
                      : "red";
              set(next);
              const target =
                event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                  "button",
                )[next === "red" ? 0 : 1];
              target?.focus();
            }
          }}
        >
          <Icon size={16} />
          {label}
        </button>
      ))}
    </div>
  );
}
export function Collaboration({
  id,
  caseId,
  open,
}: {
  id: string | null;
  caseId: string | null;
  open: OpenWorkspace;
}) {
  const [view, setView] = useState<RoleView>("blue");
  if (id)
    return (
      <Workspace
        key={id}
        id={id}
        caseId={caseId}
        open={open}
        view={view}
        setView={setView}
      />
    );
  return <WorkspaceList open={open} view={view} setView={setView} />;
}
function WorkspaceList({
  open,
  view,
  setView,
}: {
  open: OpenWorkspace;
  view: RoleView;
  setView: (value: RoleView) => void;
}) {
  const [items, setItems] = useState<Engagement[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<unknown>(null),
    [search, setSearch] = useState(""),
    [creating, setCreating] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void api
      .engagements(offset, controller.signal)
      .then((page) => {
        if (active) {
          setItems((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((item) => [item.id, item]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, revision]);
  const matches = items.filter((item) =>
    `${item.name} ${item.objective}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <>
      <section className="overview-heading">
        <div>
          <div className="eyebrow">SHARED EVIDENCE / 验证与整改</div>
          <h1>
            从发现，到复核。<span>↗</span>
          </h1>
          <p>
            为同一批资产建立检查范围。红队整理线索和依据，蓝队跟踪整改、记录复测；结论始终回到保存的证据。
          </p>
        </div>
        <button
          className="button button-primary"
          onClick={() => setCreating(true)}
        >
          <Plus size={15} />
          新建工作区
        </button>
      </section>
      <TeamSwitch view={view} set={setView} />
      <div className={`team-intro team-${view}`}>
        <span className="eyebrow">
          {view === "red" ? "ASSESS / 验证视角" : "REVIEW / 防守视角"}
        </span>
        <p>
          {view === "red"
            ? "限定范围、选择已完成检查、保留待验证条件和证据缺口。静态线索不会被升级成已利用漏洞。"
            : "分配负责人和截止日期，记录整改说明，再选同一资产的检查结果进行复测。复测不会自动关闭条目。"}
        </p>
        <small>
          视角只改变工作方式；当前是本机单用户工具，不代表账号权限隔离。
        </small>
      </div>
      <div className="workspace-toolbar">
        <SearchField
          value={search}
          onChange={setSearch}
          label="搜索工作区"
          placeholder="搜索名称或目标"
        />
        <button
          className="text-button"
          onClick={() => {
            setOffset(0);
            setRevision((value) => value + 1);
          }}
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      <Failure value={error} retry={() => setRevision((value) => value + 1)} />
      {loading && !items.length ? (
        <Loading />
      ) : matches.length ? (
        <div className="workspace-grid">
          {matches.map((item) => (
            <button
              key={item.id}
              className="workspace-card"
              onClick={() => open(item.id)}
            >
              <span className="eyebrow">{item.asset_count} 项范围资产</span>
              <h2>
                {item.name}
                <ArrowRight size={19} />
              </h2>
              <p>{item.objective || "尚未填写评估目标"}</p>
              <div className="workspace-counts">
                <span>
                  <strong>{item.case_count}</strong>条记录
                </span>
                <span>
                  <strong>{item.case_counts?.ready_for_retest || 0}</strong>
                  待复测
                </span>
                <span>
                  <strong>{item.case_counts?.resolved || 0}</strong>已复核关闭
                </span>
              </div>
              <small>{dateLabel(item.created_at)}</small>
            </button>
          ))}
        </div>
      ) : (
        <Empty
          title={search ? "没有匹配的工作区" : "把检查变成持续的工作"}
          detail="先选择已有资产并写明目标与授权范围，再将检查中的线索加入工作区。"
          action={
            !search && (
              <button className="button" onClick={() => setCreating(true)}>
                新建工作区 <ArrowRight size={15} />
              </button>
            )
          }
        />
      )}
      <p className="load-scope">
        已载入 {items.length} / {total} 个工作区
      </p>
      {items.length < total && (
        <button
          className="text-button"
          disabled={loading}
          onClick={() => setOffset(items.length)}
        >
          载入更多 ↓
        </button>
      )}
      {creating && (
        <CreateWorkspace
          close={() => setCreating(false)}
          created={(item) => {
            setCreating(false);
            open(item.id);
          }}
        />
      )}
    </>
  );
}
export function CreateWorkspace({
  close,
  created,
  initialAssetId,
}: {
  close: () => void;
  created: (value: Engagement) => void;
  initialAssetId?: string;
}) {
  const [assets, setAssets] = useState<Asset[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState(""),
    [selected, setSelected] = useState<string[]>(
      initialAssetId ? [initialAssetId] : [],
    ),
    [name, setName] = useState(""),
    [objective, setObjective] = useState(""),
    [authorization, setAuthorization] = useState("");
  const missing: string[] = [];
  if (!name.trim()) missing.push("工作区名称");
  if (!authorization.trim()) missing.push("授权与范围说明");
  if (!selected.length) missing.push("至少一个资产");
  const busyRef = useRef(false),
    request = useRef<{ signature: string; key: string } | null>(null);
  const ref = useDialog(true, () => {
    if (!busyRef.current) close();
  });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    void api
      .assets(offset, controller.signal)
      .then((page) => {
        if (active) {
          setAssets((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((item) => [item.id, item]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    setError(null);
    if (!selected.length) {
      setError(new Error("请至少选择一个已有资产。"));
      return;
    }
    busyRef.current = true;
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        objective: objective.trim(),
        authorization_note: authorization.trim(),
        asset_ids: selected,
      };
      const signature = JSON.stringify(payload);
      if (request.current?.signature !== signature)
        request.current = { signature, key: crypto.randomUUID() };
      created(await api.createEngagement(payload, request.current.key));
    } catch (failure) {
      setError(failure);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="modal-backdrop">
      <div
        className="new-job-panel workspace-create"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-workspace-title"
      >
        <header className="panel-heading">
          <div>
            <span className="eyebrow">NEW WORKSPACE / 工作区</span>
            <h2 id="create-workspace-title">建立共同的工作区</h2>
          </div>
          <button
            className="icon-button"
            aria-label="关闭新建工作区"
            onClick={close}
            disabled={busy}
          >
            <X size={20} />
          </button>
        </header>
        <form
          onSubmit={(event) => {
            void save(event);
          }}
        >
          <div className="workspace-form-content">
            <label className="field">
              <span className="field-label">
                工作区名称 <small>必填</small>
              </span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={120}
                required
                disabled={busy}
                placeholder="例如：发布前安全复核"
              />
            </label>
            <label className="field">
              <span className="field-label">
                本次目标 <small>可选</small>
              </span>
              <textarea
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                maxLength={1000}
                rows={2}
                disabled={busy}
                placeholder="需要复核哪些配置或使用路径？"
              />
            </label>
            <label className="field">
              <span className="field-label">
                授权与范围说明 <small>必填</small>
              </span>
              <textarea
                value={authorization}
                onChange={(event) => setAuthorization(event.target.value)}
                maxLength={2000}
                rows={3}
                required
                disabled={busy}
                placeholder="例如：自有站点，内网授权，仅检查响应头"
              />
              <small className="field-hint">
                记录资产归属、授权依据与检查边界。此处是工作记录，不是外部授权证明。
              </small>
            </label>
            <div className="field">
              <span className="field-label">
                范围内资产 <small>必填 · 已选 {selected.length} / 100</small>
              </span>
              {initialAssetId && (
                <p className="scope-note">
                  此入口保留当前检查资产 <code>{initialAssetId}</code>
                  ，以便将保存证据接入明确范围。请核对授权说明和其他范围内资产；不会推断网站、云服务或主机之间的身份关系。
                </p>
              )}
              <SearchField
                value={search}
                onChange={setSearch}
                label="搜索范围资产"
                placeholder="搜索已有资产"
              />
              {loading && !assets.length ? (
                <Loading />
              ) : (
                <div className="scope-asset-options">
                  {assets
                    .filter((item) =>
                      item.name.toLowerCase().includes(search.toLowerCase()),
                    )
                    .map((item) => (
                      <label
                        className={`scope-asset-option ${selected.includes(item.id) ? "selected" : ""}`}
                        key={item.id}
                      >
                        <input
                          type="checkbox"
                          disabled={
                            busy ||
                            item.id === initialAssetId ||
                            (!selected.includes(item.id) &&
                              selected.length >= 100)
                          }
                          checked={selected.includes(item.id)}
                          onChange={(event) =>
                            setSelected((previous) =>
                              event.target.checked
                                ? [...previous, item.id]
                                : previous.filter((id) => id !== item.id),
                            )
                          }
                        />
                        <span>
                          <strong>{item.name}</strong>
                          <small>
                            {assetKindLabel[item.kind]} / {item.id.slice(0, 8)}
                          </small>
                        </span>
                      </label>
                    ))}
                  {!assets.length && (
                    <p className="inline-empty">
                      请先在“我的资产”中保存一个检查对象。
                    </p>
                  )}
                </div>
              )}
              <small className="load-scope">
                已载入 {assets.length}/{total} 个资产。范围在创建后固定。
              </small>
              {assets.length < total && (
                <button
                  type="button"
                  className="text-button"
                  disabled={loading || busy}
                  onClick={() => setOffset(assets.length)}
                >
                  载入更多资产 ↓
                </button>
              )}
            </div>
            <Failure value={error} />
          </div>
          <footer className="form-footer">
            <div className="form-footer-notes">
              <small>使用已保存的资产，不启动任何新探测。</small>
              {missing.length > 0 && (
                <small
                  className="field-hint"
                  role="status"
                  id="workspace-submit-missing"
                >
                  还需完成：{missing.join("、")}
                </small>
              )}
            </div>
            <button
              className="button button-primary"
              type="submit"
              aria-describedby={
                missing.length > 0 ? "workspace-submit-missing" : undefined
              }
              disabled={busy || missing.length > 0}
            >
              {busy ? "正在保存…" : "建立工作区"}
              <ArrowRight size={15} />
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}

function Workspace({
  id,
  caseId,
  open,
  view,
  setView,
}: {
  id: string;
  caseId: string | null;
  open: OpenWorkspace;
  view: RoleView;
  setView: (value: RoleView) => void;
}) {
  const [workspace, setWorkspace] = useState<Engagement | null>(null),
    [cases, setCases] = useState<ReviewCase[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<unknown>(null),
    [revision, setRevision] = useState(0),
    [adding, setAdding] = useState(false),
    [filter, setFilter] = useState("all"),
    [search, setSearch] = useState("");
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void Promise.all([
      api.engagement(id, controller.signal),
      api.cases(id, offset, controller.signal),
    ])
      .then(([detail, page]) => {
        if (active) {
          setWorkspace(detail);
          setCases((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((item) => [item.id, item]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [id, offset, revision]);
  const refresh = () => {
    setOffset(0);
    setRevision((value) => value + 1);
  };
  if (!workspace)
    return (
      <>
        <button className="text-button" onClick={() => open(null)}>
          <ArrowLeft size={14} />
          返回工作区
        </button>
        <Failure value={error} retry={refresh} />
        {loading && <Loading />}
      </>
    );
  const caseCounts: Partial<Record<CaseStatus, number>> =
    workspace.case_counts ?? {};
  const matches = cases.filter(
    (item) =>
      (filter === "all" || item.status === filter) &&
      `${item.title} ${item.owner} ${item.asset_name}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <button className="text-button back-link" onClick={() => open(null)}>
        <ArrowLeft size={14} />
        返回工作区列表
      </button>
      <section className="workspace-heading">
        <div>
          <span className="eyebrow">ASSESSMENT WORKSPACE / 验证与整改</span>
          <h1>{workspace.name}</h1>
          <p>{workspace.objective || "范围内的检查记录与人工复核。"}</p>
        </div>
        <div className="workspace-export">
          <a
            className="button"
            href={api.engagementExportUrl(id, "json")}
            download
          >
            <FileDown size={14} />
            JSON
          </a>
          <a
            className="button"
            href={api.engagementExportUrl(id, "html")}
            download
          >
            工作报告 ↗
          </a>
        </div>
      </section>
      <TeamSwitch view={view} set={setView} />
      <details className="engagement-scope" open={view === "red"}>
        <summary>
          <Target size={16} />
          资产与授权范围 <span>{workspace.asset_count} 项资产</span>
        </summary>
        <p className="scope-authorization">{workspace.authorization_note}</p>
        <div className="scope-chips">
          {workspace.assets?.map((item) => (
            <a key={item.id} href={`#/assets/${item.id}`}>
              {assetKindLabel[item.kind]} / {item.name}
              <ArrowRight size={12} />
            </a>
          ))}
        </div>
        <small>
          范围仅用于组织已保存资产的证据，不授予外部访问权限；红蓝视角不代表账号隔离。
        </small>
      </details>
      {caseId && <Failure value={error} retry={refresh} />}
      {caseId ? (
        <CaseDetail
          key={caseId}
          id={caseId}
          engagementId={id}
          view={view}
          back={() => open(id)}
          changed={refresh}
        />
      ) : (
        <>
          <div className="workspace-kpis">
            <div>
              <span>范围内记录</span>
              <strong>{workspace.case_count}</strong>
            </div>
            <div>
              <span>处理中</span>
              <strong>{caseCounts.in_progress || 0}</strong>
            </div>
            <div>
              <span>待复测</span>
              <strong>{caseCounts.ready_for_retest || 0}</strong>
            </div>
            <div>
              <span>已复核关闭</span>
              <strong>{caseCounts.resolved || 0}</strong>
            </div>
          </div>
          <div className="workspace-record-heading">
            <div>
              <span className="eyebrow">
                {view === "red" ? "EVIDENCE QUEUE" : "REMEDIATION REGISTER"}
              </span>
              <h2>{view === "red" ? "验证线索" : "整改记录"}</h2>
              <p>
                {view === "red"
                  ? "从范围内的已完成检查选择候选条目；原始置信程度和限制随证据保留。"
                  : "保存负责人、处理状态和复测依据；条目关闭需要明确的人工说明与可比结果。"}
              </p>
            </div>
            <button
              className="button button-primary"
              onClick={() => setAdding(true)}
            >
              <Plus size={15} />
              从检查添加线索
            </button>
          </div>
          <div className="workspace-toolbar">
            <SearchField
              value={search}
              onChange={setSearch}
              label="搜索协作记录"
              placeholder="搜索条目、资产或负责人"
            />
            <label className="workspace-status-filter">
              状态
              <select
                aria-label="筛选协作状态"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
              >
                <option value="all">全部状态</option>
                {Object.entries(caseLabels).map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <button className="text-button" onClick={refresh}>
              <RefreshCw size={14} />
              刷新
            </button>
          </div>
          <Failure value={error} retry={refresh} />
          {loading && !cases.length ? (
            <Loading />
          ) : matches.length ? (
            <div className={`case-register view-${view}`}>
              {matches.map((item) => (
                <button
                  className="case-row"
                  key={item.id}
                  onClick={() => open(id, item.id)}
                >
                  <span className={`case-state case-${item.status}`}>
                    {caseStatusLabel(item.status)}
                  </span>
                  <div className="case-row-main">
                    <h3>{item.title}</h3>
                    <small>
                      {item.asset_name} · {item.job_name}
                    </small>
                    <span className="case-confidence">
                      {item.severity} / {item.confidence}
                    </span>
                  </div>
                  {view === "blue" ? (
                    <div className="case-row-assignment">
                      <span>{item.owner || "尚未分配"}</span>
                      <small>
                        {item.due_date
                          ? `截止 ${item.due_date}`
                          : "未设截止日期"}
                      </small>
                    </div>
                  ) : (
                    <small className="case-row-source">
                      {item.source_kind === "check" ? "配置检查" : "观察记录"} ·
                      保留原始依据
                    </small>
                  )}
                  <ArrowRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="还没有匹配的记录"
              detail="选择已完成的检查，将候选线索加入当前工作区。"
              action={
                <button className="button" onClick={() => setAdding(true)}>
                  选择检查来源
                  <ArrowRight size={14} />
                </button>
              }
            />
          )}
          <p className="load-scope">
            已载入 {cases.length}/{total} 条记录；筛选作用于已载入记录。
          </p>
          {cases.length < total && (
            <button
              className="text-button"
              disabled={loading}
              onClick={() => setOffset(cases.length)}
            >
              载入更多记录 ↓
            </button>
          )}
        </>
      )}
      {adding && (
        <AddCandidate
          workspace={workspace}
          close={() => setAdding(false)}
          added={(item) => {
            setAdding(false);
            refresh();
            open(id, item.id);
          }}
        />
      )}
    </>
  );
}

function AddCandidate({
  workspace,
  close,
  added,
}: {
  workspace: Engagement;
  close: () => void;
  added: (item: ReviewCase) => void;
}) {
  const [assetId, setAssetId] = useState(workspace.assets?.[0]?.id || ""),
    [jobs, setJobs] = useState<Job[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [jobId, setJobId] = useState(""),
    [candidates, setCandidates] = useState<Candidate[]>([]),
    [limits, setLimits] = useState<string[]>([]),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(""),
    [error, setError] = useState<unknown>(null);
  const busyRef = useRef(false),
    requests = useRef(new Map<string, string>());
  busyRef.current = Boolean(busy);
  const ref = useDialog(true, () => {
    if (!busyRef.current) close();
  });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void api
      .assetJobs(assetId, offset, controller.signal)
      .then((page) => {
        if (active) {
          setJobs((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((item) => [item.id, item]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [assetId, offset]);
  useEffect(() => {
    setCandidates([]);
    setLimits([]);
    if (!jobId) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void api
      .candidates(workspace.id, jobId, controller.signal)
      .then((result) => {
        if (active) {
          setCandidates(result.items);
          setLimits(result.limitations);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [workspace.id, jobId]);
  async function select(candidate: Candidate) {
    if (busyRef.current) return;
    setBusy(candidate.source_ref);
    setError(null);
    const identity = `${candidate.job_id}/${candidate.source_kind}/${candidate.source_ref}`;
    if (!requests.current.has(identity))
      requests.current.set(identity, crypto.randomUUID());
    try {
      added(
        await api.createCase(
          workspace.id,
          {
            job_id: candidate.job_id,
            source_ref: candidate.source_ref,
            source_kind: candidate.source_kind,
          },
          requests.current.get(identity)!,
        ),
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="modal-backdrop">
      <div
        className="new-job-panel candidate-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-candidate-title"
        ref={ref}
      >
        <header className="panel-heading">
          <div>
            <span className="eyebrow">FROM SAVED CHECKS / 原始来源</span>
            <h2 id="add-candidate-title">选择一条验证线索</h2>
          </div>
          <button
            className="icon-button"
            aria-label="关闭线索选择"
            onClick={close}
            disabled={Boolean(busy)}
          >
            <X size={20} />
          </button>
        </header>
        <div className="workspace-form-content">
          <label className="field">
            <span className="field-label">范围内资产</span>
            <select
              aria-label="选择线索资产"
              value={assetId}
              disabled={Boolean(busy)}
              onChange={(event) => {
                setAssetId(event.target.value);
                setOffset(0);
                setJobs([]);
                setJobId("");
              }}
            >
              {workspace.assets?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">已完成的检查</span>
            <select
              aria-label="选择线索检查"
              value={jobId}
              onChange={(event) => setJobId(event.target.value)}
              disabled={Boolean(busy)}
            >
              <option value="">选择一个已完成检查</option>
              {jobs
                .filter((item) => item.status === "completed")
                .map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.name} · {dateLabel(item.created_at)}
                  </option>
                ))}
            </select>
          </label>
          <small className="load-scope">
            已载入 {jobs.length}/{total} 条历史，只能选已完成检查。
          </small>
          {jobs.length < total && (
            <button
              className="text-button"
              onClick={() => setOffset(jobs.length)}
              disabled={loading || Boolean(busy)}
            >
              载入更多检查 ↓
            </button>
          )}
          <Failure value={error} />
          {loading ? (
            <Loading />
          ) : (
            jobId &&
            (!candidates.length ? (
              <p className="inline-empty">
                这次检查没有可加入的候选条目；未选择的检查和普通技术指纹不会凭空生成发现。
              </p>
            ) : (
              <div className="candidate-source-list">
                {candidates.map((item) => (
                  <article key={`${item.source_kind}-${item.source_ref}`}>
                    <span className="eyebrow">
                      {item.severity} / {item.confidence}
                    </span>
                    <h3>{item.title}</h3>
                    <p>{item.description}</p>
                    <small>{item.evidence_ids.length} 条来源证据</small>
                    <button
                      className="button"
                      disabled={Boolean(busy)}
                      onClick={() => {
                        void select(item);
                      }}
                    >
                      {busy === item.source_ref ? "正在加入…" : "加入工作区"}
                      <ArrowRight size={14} />
                    </button>
                  </article>
                ))}
              </div>
            ))
          )}
          {limits.length > 0 && (
            <details className="workspace-limits">
              <summary>来源限制</summary>
              <ul>
                {limits.map((value, index) => (
                  <li key={index}>{value}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}
