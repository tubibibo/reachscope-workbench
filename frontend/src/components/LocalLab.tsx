import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleStop,
  FlaskConical,
  Play,
  RefreshCw,
} from "lucide-react";
import { api, errorRequestId, errorText } from "../lib/api";
import { labApi } from "../lib/local-lab";
import { jobConfig } from "../lib/job-config";
import type {
  LabState,
  ScenarioIssue,
  ScenarioSummary,
} from "../lib/local-lab";
import type {
  Asset,
  Candidate,
  Engagement,
  Job,
  RetestResult,
  ReviewCase,
  WebComparison,
} from "../lib/types";
import { isRecord, strings } from "../lib/types";
import { useJob } from "../hooks/useJobs";
import { ErrorBox, Loading, StatusTag } from "./Common";

interface Progress {
  session: string;
  asset?: string;
  baseline?: string;
  retest?: string;
  engagement?: string;
  case?: string;
}
const storageKey = "reachscope.lab.progress";
function storedProgress(): Progress | null {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(storageKey) || "null",
    );
    if (
      isRecord(value) &&
      typeof value.session === "string" &&
      /^[a-f0-9]{32}$/.test(value.session)
    ) {
      const progress: Progress = { session: value.session };
      for (const key of [
        "asset",
        "baseline",
        "retest",
        "engagement",
        "case",
      ] as const) {
        const id = value[key];
        if (
          id !== undefined &&
          (typeof id !== "string" || !/^[a-f0-9]{32}$/.test(id))
        )
          return null;
        if (typeof id === "string") progress[key] = id;
      }
      return progress;
    }
  } catch {
    /* Storage may be unavailable. All authoritative records remain in the API. */
  }
  return null;
}

export function LocalLab({
  openJob,
  openAsset,
  openCase,
  changed,
}: {
  openJob: (job: Job) => void;
  openAsset: (id: string) => void;
  openCase: (engagement: string, id: string) => void;
  changed: () => void;
}) {
  const [lab, setLab] = useState<LabState | null>(null),
    [progress, setProgress] = useState<Progress | null>(storedProgress),
    [asset, setAsset] = useState<Asset | null>(null),
    [engagement, setEngagement] = useState<Engagement | null>(null),
    [item, setItem] = useState<ReviewCase | null>(null),
    [candidates, setCandidates] = useState<Candidate[]>([]),
    [candidateId, setCandidateId] = useState(""),
    [note, setNote] = useState(""),
    [comparison, setComparison] = useState<WebComparison | null>(null),
    [retestResult, setRetestResult] = useState<RetestResult | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState<unknown>(null),
    [checks, setChecks] = useState(["http", "headers", "page"]),
    [ready, setReady] = useState(false),
    [packs, setPacks] = useState<ScenarioSummary[]>([]),
    [packIssues, setPackIssues] = useState<ScenarioIssue[]>([]),
    [selectedPack, setSelectedPack] = useState("");
  const busyRef = useRef(false),
    operations = useRef(new Map<string, string>());
  const baseline = useJob(progress?.baseline || null),
    retest = useJob(progress?.retest || null);
  const running = lab?.status === "running";
  const currentSession = running && progress?.session === lab?.session_id;
  const baselineComplete =
    currentSession && baseline.job?.status === "completed";
  const retestComplete = currentSession && retest.job?.status === "completed";
  function operation(name: string, signature: string) {
    const id = `${name}:${signature}`;
    let key = operations.current.get(id);
    if (!key) {
      key = crypto.randomUUID();
      operations.current.set(id, key);
    }
    return key;
  }
  function updateProgress(patch: Partial<Progress>) {
    setProgress((current) => ({
      session: lab?.session_id || current?.session || "",
      ...current,
      ...patch,
    }));
  }
  useEffect(() => {
    const controller = new AbortController();
    void labApi
      .state(controller.signal)
      .then(setLab)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      })
      .finally(() => {
        if (!controller.signal.aborted) setReady(true);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void labApi
      .scenarios(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setPacks(result.packs);
          setPackIssues(result.issues);
        }
      })
      .catch(() => {
        /* Scenario listing is auxiliary; the default teaching site stands alone. */
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    try {
      if (progress)
        sessionStorage.setItem(storageKey, JSON.stringify(progress));
    } catch {
      /* Session-only navigation convenience, never stores credentials. */
    }
  }, [progress]);
  useEffect(() => {
    if (lab?.session_id && progress?.session !== lab.session_id) {
      setProgress({ session: lab.session_id });
      setAsset(null);
      setEngagement(null);
      setItem(null);
      setCandidates([]);
      setComparison(null);
      setRetestResult(null);
    }
  }, [lab?.session_id, progress?.session]);
  useEffect(() => {
    let active = true;
    if (progress?.asset)
      void api
        .asset(progress.asset)
        .then((value) => {
          if (active) setAsset(value);
        })
        .catch((failure: unknown) => {
          if (active) setError(failure);
        });
    if (progress?.engagement)
      void api
        .engagement(progress.engagement)
        .then((value) => {
          if (active) setEngagement(value);
        })
        .catch((failure: unknown) => {
          if (active) setError(failure);
        });
    if (progress?.case)
      void api
        .reviewCase(progress.case)
        .then((value) => {
          if (active)
            setItem((current) =>
              current?.id === value.id && current.version > value.version
                ? current
                : value,
            );
        })
        .catch((failure: unknown) => {
          if (active) setError(failure);
        });
    return () => {
      active = false;
    };
  }, [progress?.asset, progress?.engagement, progress?.case]);
  async function run(label: string, action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(label);
    setError(null);
    try {
      await action();
      changed();
    } catch (failure) {
      setError(failure);
      try {
        setLab(await labApi.state());
        if (progress?.case) setItem(await api.reviewCase(progress.case));
      } catch {
        /* Keep the original operation error visible. */
      }
    } finally {
      busyRef.current = false;
      setBusy("");
    }
  }
  async function inspect(phase: "baseline" | "retest") {
    if (!asset || !lab) return;
    const selected =
      phase === "retest" && baseline.job
        ? strings(jobConfig(baseline.job).checks)
        : checks;
    const preflight = await api.preflight(asset.id, { checks: selected });
    if (!preflight.ready)
      throw new Error(
        preflight.items
          .filter((entry) => entry.status === "blocked")
          .map((entry) => entry.message)
          .join("；") || "运行条件尚未满足",
      );
    const job = await api.inspectAsset(
      asset.id,
      {
        checks: selected,
        name:
          phase === "baseline"
            ? "本地教学 / 基线检查"
            : "本地教学 / 补强后复测",
      },
      operation(phase, `${lab.session_id}:${asset.id}:${selected.join(",")}`),
    );
    updateProgress({ [phase]: job.id });
    setComparison(null);
    setRetestResult(null);
  }
  async function retryInspection(phase: "baseline" | "retest", job: Job) {
    const value = await api.retry(job.id, operation(`retry-${phase}`, job.id));
    updateProgress({ [phase]: value.id });
    setComparison(null);
    setRetestResult(null);
  }
  async function loadCandidates() {
    if (!asset || !baseline.job) return;
    let saved = engagement;
    if (!saved) {
      saved = await api.createEngagement(
        {
          name: "本地教学 / 配置整改",
          objective: "仅在本机教学站点验证配置观察与复测闭环",
          authorization_note:
            "本人启动的内置loopback教学站点，仅限此保存资产，不扩展目标。",
          asset_ids: [asset.id],
        },
        operation("engagement", asset.id),
      );
      setEngagement(saved);
      updateProgress({ engagement: saved.id });
    }
    const result = await api.candidates(saved.id, baseline.job.id);
    setCandidates(result.items);
    setCandidateId(result.items[0]?.source_ref || "");
  }
  const candidate = candidates.find(
    (entry) => entry.source_ref === candidateId,
  );
  const selectedPackData = packs.find((pack) => pack.id === selectedPack);
  return (
    <>
      <section className="overview-heading">
        <div>
          <span className="eyebrow">LOCAL TRAINING / 本地教学</span>
          <h1>
            亲手完成一次检查与修复。<span>↗</span>
          </h1>
          <p>
            真实请求本机教学站点，保存基线，补强配置，再复测并人工关闭事项。每个写入和检查都由你明确触发；不调用
            AI。
          </p>
        </div>
        <FlaskConical size={52} strokeWidth={1} aria-hidden="true" />
      </section>
      {!ready ? (
        <Loading label="正在读取教学环境…" />
      ) : (
        <>
          {error && (
            <ErrorBox requestId={errorRequestId(error)}>
              {errorText(error)}
            </ErrorBox>
          )}
          <section className="lab-environment">
            <div>
              <span className="eyebrow">01 / LOOPBACK ONLY</span>
              <h2>{running ? "教学站点已启动" : "启动专用教学站点"}</h2>
              <p>
                仅绑定 127.0.0.1
                的随机端口。这里的配置变化是教学示例，不能代表生产站点的安全状况。
              </p>
              {lab?.url && <code>{lab.url}</code>}
              <span className="lab-profile">
                {running
                  ? lab.profile === "baseline"
                    ? "当前响应：基线配置"
                    : "当前响应：补强配置"
                  : "当前未运行"}
              </span>
              {running && (
                <span className="lab-profile">
                  当前场景：
                  {lab.scenario
                    ? lab.scenario.title.zh || lab.scenario.title.en
                    : "内置响应头场景"}
                </span>
              )}
              {running && lab.scenario && lab.scenario.limits.length > 0 && (
                <p>{lab.scenario.limits.slice(0, 3).join("；")}</p>
              )}
              {packIssues.length > 0 && (
                <p>
                  {packIssues.length} 个场景包加载失败：
                  {packIssues
                    .slice(0, 3)
                    .map((issue) => issue.code)
                    .join("、")}
                </p>
              )}
            </div>
            <div className="lab-actions">
              {!running && packs.length > 0 && (
                <select
                  aria-label="选择教学场景"
                  value={selectedPack}
                  disabled={Boolean(busy)}
                  onChange={(event) => setSelectedPack(event.target.value)}
                >
                  <option value="">默认（响应头教学站）</option>
                  {packs.map((pack) => (
                    <option key={pack.id} value={pack.id}>
                      {pack.title.zh || pack.title.en}
                    </option>
                  ))}
                </select>
              )}
              {!running &&
                selectedPackData &&
                (selectedPackData.limits ?? []).length > 0 && (
                  <p>
                    {(selectedPackData.limits ?? []).slice(0, 3).join("；")}
                  </p>
                )}
              <button
                className="button button-primary"
                disabled={Boolean(busy) || running}
                onClick={() =>
                  void run("start", async () => {
                    setLab(await labApi.start(selectedPack || undefined));
                  })
                }
              >
                <Play size={14} />
                启动本地教学站点
              </button>
              <button
                className="button"
                disabled={Boolean(busy) || !running}
                onClick={() =>
                  void run("stop", async () => {
                    setLab(await labApi.stop());
                  })
                }
              >
                <CircleStop size={12} />
                停止教学站点
              </button>
            </div>
          </section>
          <div className="lab-flow">
            <section className="lab-step">
              <span className="eyebrow">02 / SAVE & INSPECT</span>
              <h2>保存资产并采集基线</h2>
              <p>
                先保存当前教学地址，再选择要执行的检查。保存资产不会发出探测请求。
              </p>
              <div
                className="lab-check-options"
                role="group"
                aria-label="教学检查项目"
              >
                {[
                  ["http", "HTTP 响应（必选）"],
                  ["headers", "响应头与 Cookie"],
                  ["page", "页面配置"],
                ].map(([id, label]) => (
                  <label key={id}>
                    <input
                      type="checkbox"
                      checked={checks.includes(id!)}
                      disabled={
                        id === "http" ||
                        Boolean(busy) ||
                        Boolean(progress?.baseline)
                      }
                      onChange={(event) =>
                        setChecks((current) =>
                          event.target.checked
                            ? [...current, id!]
                            : current.filter((entry) => entry !== id),
                        )
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
              <div className="lab-actions">
                <button
                  className="button"
                  disabled={
                    !currentSession ||
                    Boolean(asset) ||
                    Boolean(busy) ||
                    !lab?.asset_template
                  }
                  onClick={() =>
                    void run("asset", async () => {
                      if (!lab?.asset_template) return;
                      const template = lab.asset_template;
                      const value = await api.createAsset(
                        template.kind,
                        template.name,
                        template.source,
                        operation("asset", lab.session_id || ""),
                      );
                      setAsset(value);
                      updateProgress({ asset: value.id });
                    })
                  }
                >
                  保存教学资产
                  <ArrowRight size={13} />
                </button>
                <button
                  className="button button-primary"
                  disabled={
                    !currentSession ||
                    !asset ||
                    lab?.profile !== "baseline" ||
                    Boolean(busy) ||
                    Boolean(progress?.baseline)
                  }
                  onClick={() =>
                    void run("baseline", () => inspect("baseline"))
                  }
                >
                  执行基线检查
                  <ArrowRight size={13} />
                </button>
              </div>
              {asset && (
                <button
                  className="text-button"
                  onClick={() => openAsset(asset.id)}
                >
                  查看已保存的教学资产
                  <ArrowRight size={12} />
                </button>
              )}
              {baseline.job && (
                <div className="lab-job">
                  <StatusTag status={baseline.job.status} />
                  <span>{baseline.job.name}</span>
                  <button
                    className="text-button"
                    onClick={() => openJob(baseline.job!)}
                  >
                    打开基线证据
                    <ArrowRight size={12} />
                  </button>
                  {(baseline.job.status === "failed" ||
                    baseline.job.status === "cancelled") && (
                    <button
                      className="text-button"
                      disabled={
                        Boolean(busy) ||
                        !currentSession ||
                        lab?.profile !== "baseline"
                      }
                      onClick={() =>
                        void run("baseline-retry", () =>
                          retryInspection("baseline", baseline.job!),
                        )
                      }
                    >
                      重试失败的基线检查
                      <RefreshCw size={12} />
                    </button>
                  )}
                </div>
              )}
              {baseline.error && <ErrorBox>{baseline.error}</ErrorBox>}
            </section>
            <section className="lab-step">
              <span className="eyebrow">03 / REVIEW A SAVED OBSERVATION</span>
              <h2>选择一项真实观察</h2>
              <p>
                从已完成基线建立独立的教学工作组，再选择需要验证的观察项。没有结果时不会预填风险结论。
              </p>
              <button
                className="button"
                disabled={!baselineComplete || Boolean(busy) || Boolean(item)}
                onClick={() => void run("candidates", loadCandidates)}
              >
                读取基线整改候选
                <ArrowRight size={13} />
              </button>
              {candidates.length > 0 && !item && (
                <>
                  <label className="field">
                    <span className="field-label">本次跟进的观察项</span>
                    <select
                      aria-label="教学整改候选"
                      value={candidateId}
                      onChange={(event) => setCandidateId(event.target.value)}
                    >
                      {candidates.map((entry) => (
                        <option key={entry.source_ref} value={entry.source_ref}>
                          {entry.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  {candidate && (
                    <p className="lab-candidate">
                      {candidate.description}
                      <small>
                        {candidate.evidence_ids.length} 条来源证据 ·
                        需要人工复核
                      </small>
                    </p>
                  )}
                  <button
                    className="button"
                    disabled={!candidate || !engagement || Boolean(busy)}
                    onClick={() =>
                      void run("case", async () => {
                        if (!candidate || !engagement) return;
                        const value = await api.createCase(
                          engagement.id,
                          candidate,
                          operation(
                            "case",
                            `${engagement.id}:${candidate.source_ref}`,
                          ),
                        );
                        setItem(value);
                        updateProgress({ case: value.id });
                      })
                    }
                  >
                    建立教学整改事项
                    <ArrowRight size={13} />
                  </button>
                </>
              )}
              {item && (
                <div className="lab-case">
                  <CheckCircle2 size={16} />
                  <div>
                    <strong>{item.title}</strong>
                    <p>
                      事项状态：
                      {item.status === "resolved" ? "已人工确认关闭" : "待处理"}
                    </p>
                    <button
                      className="text-button"
                      onClick={() => openCase(item.engagement_id, item.id)}
                    >
                      打开事项与审计记录
                      <ArrowRight size={12} />
                    </button>
                  </div>
                </div>
              )}
            </section>
            <section className="lab-step">
              <span className="eyebrow">04 / HARDEN THE LOCAL FIXTURE</span>
              <h2>切换固定的补强配置</h2>
              <p>
                只改变内置教学站点的响应头和
                HTML，同一地址继续提供服务。不会配置
                Nginx，也不会修改你的其他网站。
              </p>
              <button
                className="button"
                disabled={
                  !baselineComplete ||
                  !item ||
                  Boolean(busy) ||
                  lab?.profile !== "baseline"
                }
                onClick={() =>
                  void run("harden", async () => {
                    if (lab)
                      setLab(
                        await labApi.configure(lab.generation, "hardened"),
                      );
                  })
                }
              >
                应用教学补强配置
                <CheckCircle2 size={14} />
              </button>
              <button
                className="button button-primary"
                disabled={
                  !currentSession ||
                  !item ||
                  lab?.profile !== "hardened" ||
                  Boolean(busy) ||
                  Boolean(progress?.retest)
                }
                onClick={() => void run("retest", () => inspect("retest"))}
              >
                <RefreshCw size={13} />
                执行补强后复测
              </button>
              {retest.job && (
                <div className="lab-job">
                  <StatusTag status={retest.job.status} />
                  <span>{retest.job.name}</span>
                  <button
                    className="text-button"
                    onClick={() => openJob(retest.job!)}
                  >
                    打开复测证据
                    <ArrowRight size={12} />
                  </button>
                  {(retest.job.status === "failed" ||
                    retest.job.status === "cancelled") && (
                    <button
                      className="text-button"
                      disabled={
                        Boolean(busy) ||
                        !currentSession ||
                        lab?.profile !== "hardened"
                      }
                      onClick={() =>
                        void run("retest-retry", () =>
                          retryInspection("retest", retest.job!),
                        )
                      }
                    >
                      重试失败的补强复测
                      <RefreshCw size={12} />
                    </button>
                  )}
                </div>
              )}
              {retest.error && <ErrorBox>{retest.error}</ErrorBox>}
            </section>
            <section className="lab-step">
              <span className="eyebrow">05 / COMPARE & DECIDE</span>
              <h2>比较证据，再人工关闭</h2>
              <p>
                先读取新旧结果和当前事项的复测判定。仅在范围内不再观察到同一条件时，才允许填写说明并关闭。
              </p>
              <button
                className="button"
                disabled={
                  !retestComplete || !item || !baseline.job || Boolean(busy)
                }
                onClick={() =>
                  void run("compare", async () => {
                    if (!item || !baseline.job || !retest.job) return;
                    const [change, result] = await Promise.all([
                      api.compare(retest.job.id, baseline.job.id),
                      api.previewRetest(item.id, retest.job.id),
                    ]);
                    setComparison(change);
                    setRetestResult(result);
                  })
                }
              >
                读取比较与复测判定
                <ArrowRight size={13} />
              </button>
              {comparison && (
                <div className="lab-comparison">
                  <strong>
                    本次比较：{comparison.summary.changed} 个目标有变化
                  </strong>
                  {comparison.assets
                    .flatMap((entry) =>
                      entry.changes
                        .filter(
                          (change) =>
                            change.field.startsWith("checks.") ||
                            change.field.startsWith("headers."),
                        )
                        .map((change) => (
                          <div key={`${entry.url}:${change.field}`}>
                            <code>{change.field}</code>
                            <span>
                              {change.before === null ||
                              change.before === undefined
                                ? "未观察到"
                                : typeof change.before === "object"
                                  ? JSON.stringify(change.before)
                                  : String(change.before ?? "—")}{" "}
                              →{" "}
                              {change.after === null ||
                              change.after === undefined
                                ? "未观察到"
                                : typeof change.after === "object"
                                  ? JSON.stringify(change.after)
                                  : String(change.after ?? "—")}
                            </span>
                          </div>
                        )),
                    )
                    .slice(0, 12)}
                </div>
              )}
              {retestResult && (
                <p className="lab-retest-outcome" role="status">
                  <strong>
                    {retestResult.outcome === "not_observed_in_scope"
                      ? "同一条件在本轮范围内未再观察到"
                      : retestResult.outcome === "still_observed"
                        ? "原条件仍可观察"
                        : "两次结果不可比较"}
                  </strong>
                  <span>{retestResult.reason}</span>
                </p>
              )}
              {item?.status === "resolved" ? (
                <p className="workspace-success" role="status">
                  <CheckCircle2 size={15} />
                  教学事项已人工关闭，基线、复测和决策历史均保留。
                </p>
              ) : (
                <>
                  <label className="field">
                    <span className="field-label">人工复核与关闭说明</span>
                    <textarea
                      aria-label="教学人工关闭说明"
                      value={note}
                      maxLength={4000}
                      disabled={Boolean(busy)}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="说明核对了哪些前后证据、这次结论的适用范围…"
                    />
                  </label>
                  <button
                    className="button button-primary"
                    disabled={
                      Boolean(busy) ||
                      !item ||
                      retestResult?.outcome !== "not_observed_in_scope" ||
                      !note.trim() ||
                      !retest.job
                    }
                    onClick={() =>
                      void run("close", async () => {
                        if (!item || !retest.job) return;
                        const value = await api.updateCase(item.id, {
                          expected_version: item.version,
                          status: "resolved",
                          retest_job_id: retest.job.id,
                          note: note.trim(),
                        });
                        setItem(value);
                      })
                    }
                  >
                    确认依据并关闭教学事项
                    <CheckCircle2 size={14} />
                  </button>
                </>
              )}
            </section>
          </div>
          {Boolean(busy) && (
            <p className="lab-pending" role="status">
              正在处理当前操作；不会自动进入下一步。
            </p>
          )}
          {lab?.limitations.length ? (
            <details className="limitations">
              <summary>教学范围与限制</summary>
              <ul>
                {lab.limitations.map((value) => (
                  <li key={value}>{value}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </>
  );
}
