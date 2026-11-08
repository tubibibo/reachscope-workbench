import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardList,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  CaseEvent,
  CaseStatus,
  Job,
  RetestResult,
  ReviewCase,
} from "../lib/types";
import { dateLabel, isRecord } from "../lib/types";
import {
  confidenceLabelText,
  evidenceKindText,
  severityLabelText,
} from "../lib/display-labels";
import { RawCode } from "./Common";
import { jobConfig } from "../lib/job-config";
import {
  canCloseCase,
  retestChecks,
  requiresCaseNote,
  requiresRetestForResolution,
} from "../lib/workflow-rules";
import { Loading } from "./Common";
import { JsonData } from "./results/JsonData";
import {
  Failure,
  caseLabels,
  caseStatusLabel,
  retestLabels,
} from "./CollaborationShared";
import type { RoleView } from "./CollaborationShared";
import { RevisionInput } from "./CaseRevision";
import { HostCaseJourney } from "./HostCaseJourney";

export function CaseDetail({
  id,
  engagementId,
  view,
  back,
  changed,
}: {
  id: string;
  engagementId: string;
  view: RoleView;
  back: () => void;
  changed: () => void;
}) {
  const [item, setItem] = useState<ReviewCase | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<unknown>(null),
    [revision, setRevision] = useState(0),
    [status, setStatus] = useState<CaseStatus>("open"),
    [owner, setOwner] = useState(""),
    [due, setDue] = useState(""),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false),
    [success, setSuccess] = useState(""),
    [jobs, setJobs] = useState<Job[]>([]),
    [jobOffset, setJobOffset] = useState(0),
    [jobTotal, setJobTotal] = useState(0),
    [jobsLoading, setJobsLoading] = useState(false),
    [jobsError, setJobsError] = useState<unknown>(null),
    [retestId, setRetestId] = useState(""),
    [retest, setRetest] = useState<RetestResult | null>(null),
    [retestLoading, setRetestLoading] = useState(false),
    [additionalEvents, setAdditionalEvents] = useState<CaseEvent[]>([]),
    [eventCursor, setEventCursor] = useState(0),
    [eventHasMore, setEventHasMore] = useState(false),
    [eventsLoading, setEventsLoading] = useState(false),
    [eventsError, setEventsError] = useState<unknown>(null);
  const busyRef = useRef(false),
    request = useRef<{ signature: string; key: string } | null>(null),
    eventRequest = useRef<AbortController | null>(null);
  const [revisionRequest, setRevisionRequest] = useState(0);
  useEffect(() => {
    eventRequest.current?.abort();
    setAdditionalEvents([]);
    setEventsError(null);
    setEventsLoading(false);
    const loaded = Array.isArray(item?.events)
      ? item.events
      : item?.events?.items || [];
    setEventCursor(
      item?.event_pagination?.next_cursor || loaded.at(-1)?.id || 0,
    );
    setEventHasMore(item?.event_pagination?.has_more ?? loaded.length >= 100);
    return () => eventRequest.current?.abort();
  }, [item?.id, item?.version]);
  async function loadEvents() {
    if (eventsLoading) return;
    const controller = new AbortController();
    eventRequest.current?.abort();
    eventRequest.current = controller;
    setEventsLoading(true);
    setEventsError(null);
    try {
      const page = await api.caseEvents(id, eventCursor, controller.signal);
      if (!controller.signal.aborted) {
        setAdditionalEvents((previous) => [
          ...new Map(
            [...previous, ...page.items].map((value) => [value.id, value]),
          ).values(),
        ]);
        setEventCursor(page.next_cursor);
        setEventHasMore(page.items.length >= 100);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setEventsError(failure);
    } finally {
      if (!controller.signal.aborted) setEventsLoading(false);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void api
      .reviewCase(id, controller.signal)
      .then((value) => {
        if (active) {
          if (value.engagement_id !== engagementId)
            throw new Error("记录不属于当前工作区。");
          setItem(value);
          setStatus(value.status);
          setOwner(value.owner);
          setDue(value.due_date);
          setNote("");
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
  }, [id, engagementId, revision]);
  useEffect(() => {
    if (!item) return;
    const controller = new AbortController();
    let active = true;
    setJobsLoading(true);
    setJobsError(null);
    void api
      .caseRetestJobs(id, jobOffset, controller.signal)
      .then((page) => {
        if (active) {
          setJobs((previous) =>
            jobOffset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((value) => [
                      value.id,
                      value,
                    ]),
                  ).values(),
                ]
              : page.items,
          );
          setJobTotal(page.total);
        }
      })
      .catch((failure) => {
        if (active) setJobsError(failure);
      })
      .finally(() => {
        if (active) setJobsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [item?.asset_id, jobOffset, revision]);
  useEffect(() => {
    setRetest(null);
    if (!retestId) return;
    const controller = new AbortController();
    let active = true;
    setRetestLoading(true);
    setError(null);
    void api
      .previewRetest(id, retestId, controller.signal)
      .then((value) => {
        if (active) setRetest(value);
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setRetestLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [id, retestId, revision]);
  const adopt = (value: ReviewCase, message: string) => {
    setItem(value);
    setStatus(value.status);
    setOwner(value.owner);
    setDue(value.due_date);
    setNote("");
    setSuccess(message);
    changed();
  };
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!item || busyRef.current) return;
    setError(null);
    setSuccess("");
    if (requiresCaseNote(status) && !note.trim()) {
      setError(new Error("关闭、接受风险或误报判定需要本次说明。"));
      return;
    }
    if (
      !canCloseCase({
        status,
        currentStatus: item.status,
        retestId,
        retestOutcome: retest?.outcome,
      })
    ) {
      setError(
        new Error(
          "关闭前请选择同一资产的可比复测，并确认本次未再观察到该条件。",
        ),
      );
      return;
    }
    busyRef.current = true;
    setBusy(true);
    try {
      adopt(
        await api.updateCase(id, {
          expected_version: item.version,
          status,
          owner: owner.trim(),
          due_date: due,
          note: note.trim(),
          ...(requiresRetestForResolution({
            status,
            currentStatus: item.status,
          })
            ? { retest_job_id: retestId }
            : {}),
        }),
        "记录已保存，变更已写入时间线。",
      );
    } catch (failure) {
      setError(failure);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function record() {
    if (!item || !retestId || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setSuccess("");
    try {
      adopt(
        await api.recordRetest(id, {
          expected_version: item.version,
          job_id: retestId,
          note: note.trim(),
        }),
        "复测依据已记录，条目状态没有自动关闭。",
      );
    } catch (failure) {
      setError(failure);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function startRetest() {
    if (!item || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setSuccess("");
    try {
      const source = await api.job(item.job_id);
      const selected = retestChecks(jobConfig(source));
      if (!selected.length)
        throw new Error("来源是旧版检查，请到资产页选择对应检查项目后复测。");
      const payload = {
        checks: selected,
        name: `复测 / ${item.title}`.slice(0, 120),
      };
      const signature = JSON.stringify({ case: id, ...payload });
      if (request.current?.signature !== signature)
        request.current = { signature, key: crypto.randomUUID() };
      const run = await api.inspectAsset(
        item.asset_id,
        payload,
        request.current.key,
      );
      request.current = null;
      setSuccess(
        `已创建复测任务 ${run.id.slice(0, 8)}。完成后刷新下方历史，选择该结果复核。`,
      );
      setJobs((previous) => [
        run,
        ...previous.filter((value) => value.id !== run.id),
      ]);
      setJobOffset(0);
      setRevision((value) => value + 1);
    } catch (failure) {
      setError(failure);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  if (!item)
    return (
      <>
        <Failure
          value={error}
          retry={() => setRevision((value) => value + 1)}
        />
        {loading && <Loading />}
      </>
    );
  const events = [
    ...new Map(
      [
        ...(Array.isArray(item.events)
          ? item.events
          : item.events?.items || []),
        ...additionalEvents,
      ].map((event) => [event.id, event]),
    ).values(),
  ];
  return (
    <section className={`case-detail view-${view}`}>
      <button className="text-button back-link" onClick={back}>
        <ArrowLeft size={14} />
        返回工作区记录
      </button>
      <div className="case-detail-heading">
        <div>
          <span className="eyebrow">
            {view === "red" ? "EVIDENCE REVIEW" : "整改与复测"} /{" "}
            {item.id.slice(0, 8)}
          </span>
          <h2>{item.title}</h2>
          <p>
            {item.asset_name} · {severityLabelText(item.severity)}
            <RawCode
              value={item.severity}
              text={severityLabelText(item.severity)}
            />{" "}
            / {confidenceLabelText(item.confidence)}
            <RawCode
              value={item.confidence}
              text={confidenceLabelText(item.confidence)}
            />
          </p>
        </div>
        <span className={`case-state case-${item.status}`}>
          {caseStatusLabel(item.status)}
        </span>
      </div>
      <Failure value={error} retry={() => setRevision((value) => value + 1)} />
      {success && (
        <p className="workspace-success" role="status">
          <Check size={15} />
          {success}
        </p>
      )}
      <HostCaseJourney
        item={item}
        retest={retest}
        openRevision={() => setRevisionRequest((value) => value + 1)}
      />
      <div className="case-detail-columns">
        <div className="case-evidence-column">
          <section className="case-section" id="host-case-source">
            <span className="eyebrow">SAVED SOURCE / 保存的来源</span>
            <h3>{view === "red" ? "线索与验证前提" : "原始配置与整改依据"}</h3>
            {item.source?.status === "unknown" && (
              <p className="inline-empty">
                来源信息不足：原始检查尚不能作出判断，后续缺失结果也不能作为修复证明。
              </p>
            )}
            <p>{item.source?.description || "查看来源检查中的原始记录。"}</p>
            {item.source?.recommendation && (
              <p className="case-recommendation">
                {item.source.recommendation}
              </p>
            )}
            <div className="case-source-links">
              <a href={`#/jobs/${item.job_id}`}>打开来源检查 ↗</a>
              <a href={`#/assets/${item.asset_id}`}>查看所属资产 ↗</a>
            </div>
            <small>
              原始置信程度不会因人工添加、流转或关闭而升级。人工说明与工具证据分别保留。
            </small>
          </section>
          <section className="case-section">
            <span className="eyebrow">SOURCE EVIDENCE</span>
            <h3>证据与覆盖范围</h3>
            {item.evidence?.length ? (
              item.evidence.map((evidence) => (
                <details className="case-evidence" key={evidence.id}>
                  <summary>
                    {evidence.title}
                    <span>
                      {evidenceKindText(evidence.kind)}
                      <RawCode
                        value={evidence.kind}
                        text={evidenceKindText(evidence.kind)}
                      />
                    </span>
                  </summary>
                  <small>{evidence.source}</small>
                  <code>{evidence.id}</code>
                  <JsonData data={evidence.data} />
                </details>
              ))
            ) : (
              <p className="inline-empty">
                没有可读取的原始证据；这属于证据缺口，不应当据此确认漏洞或关闭风险。
              </p>
            )}
          </section>
        </div>
        <div className="case-action-column">
          <form
            className="case-section case-edit"
            id="host-case-decision"
            onSubmit={(event) => {
              void save(event);
            }}
          >
            <span className="eyebrow">
              {view === "red"
                ? "MANUAL REVIEW / 人工研判"
                : "ASSIGN & FOLLOW UP / 整改跟踪"}
            </span>
            <h3>{view === "red" ? "记录下一步判断" : "更新整改记录"}</h3>
            <label className="field">
              <span className="field-label">处理状态</span>
              <select
                aria-label="记录处理状态"
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as CaseStatus)
                }
                disabled={busy}
              >
                {Object.entries(caseLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <div className="case-assignment">
              <label className="field">
                <span className="field-label">负责人</span>
                <input
                  aria-label="记录负责人"
                  value={owner}
                  onChange={(event) => setOwner(event.target.value)}
                  maxLength={80}
                  disabled={busy}
                  placeholder="本地工作标签"
                />
              </label>
              <label className="field">
                <span className="field-label">截止日期</span>
                <input
                  aria-label="记录截止日期"
                  type="date"
                  value={due}
                  onChange={(event) => setDue(event.target.value)}
                  disabled={busy}
                />
              </label>
            </div>
            <label className="field">
              <span className="field-label">本次说明</span>
              <textarea
                aria-label="记录本次说明"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={4000}
                rows={4}
                disabled={busy}
                placeholder={
                  view === "red"
                    ? "记录前提、人工观察、待确认内容或排除依据。"
                    : "记录配置改动、处理决定与复测说明。"
                }
              />
            </label>
            {item.note && (
              <details className="previous-note">
                <summary>上次说明</summary>
                <p>{item.note}</p>
              </details>
            )}
            <small>
              负责人是本地标签。关闭、接受风险和误报判定需要新说明；关闭还需要可比复测依据。
            </small>
            <button
              className="button button-primary"
              type="submit"
              disabled={busy}
            >
              {busy ? "正在处理…" : "保存记录"}
              <ArrowRight size={14} />
            </button>
          </form>
          <RevisionInput
            item={item}
            busy={busy}
            expandRequest={revisionRequest}
            linked={(value) => {
              adopt(value, "修订输入已关联；原始证据与工作区范围保持不变。");
              setJobOffset(0);
              setRevision((value) => value + 1);
            }}
          />
          <section
            className="case-section retest-section"
            id="host-case-retest"
          >
            <span className="eyebrow">RETEST / 可比复核</span>
            <h3>使用后续检查复测</h3>
            <p>
              先运行同一资产的检查，再选择完成结果。缺失规则、错误资产或失败采集都不能自动当成已修复。
            </p>
            <div className="retest-actions">
              <button
                className="button"
                disabled={busy}
                onClick={() => {
                  void startRetest();
                }}
              >
                按来源项目发起复测 <RefreshCw size={14} />
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setJobOffset(0);
                  setRevision((value) => value + 1);
                }}
              >
                刷新历史
              </button>
            </div>
            <Failure
              value={jobsError}
              retry={() => setRevision((value) => value + 1)}
            />
            <label className="field">
              <span className="field-label">复测检查</span>
              <select
                aria-label="选择复测检查"
                value={retestId}
                onChange={(event) => setRetestId(event.target.value)}
                disabled={busy}
              >
                <option value="">选择同一资产已完成的检查</option>
                {jobs
                  .filter(
                    (job) =>
                      job.status === "completed" && job.id !== item.job_id,
                  )
                  .map((job) => (
                    <option value={job.id} key={job.id}>
                      {job.name} · {dateLabel(job.created_at)}
                    </option>
                  ))}
              </select>
            </label>
            <small className="load-scope">
              已载入 {jobs.length}/{jobTotal} 条历史。
            </small>
            {jobs.length < jobTotal && (
              <button
                className="text-button"
                disabled={jobsLoading || busy}
                onClick={() => setJobOffset(jobs.length)}
              >
                载入更多检查 ↓
              </button>
            )}
            {retestLoading && <Loading label="正在对齐复测依据…" />}
            {retest && !retestLoading && (
              <div className={`retest-outcome outcome-${retest.outcome}`}>
                <strong>{retestLabels[retest.outcome]}</strong>
                <p>{retest.reason}</p>
                {retest.input_revision && (
                  <small>
                    本次使用显式关联的修订输入；资源身份由人工确认，原始来源保留。
                  </small>
                )}
                <details>
                  <summary>查看复测匹配依据</summary>
                  <JsonData data={{ matching: retest.matching }} />
                </details>
                <ul>
                  {retest.limitations.map((value, index) => (
                    <li key={index}>{value}</li>
                  ))}
                </ul>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => {
                    void record();
                  }}
                >
                  记录本次复测 <ClipboardList size={14} />
                </button>
              </div>
            )}
          </section>
        </div>
      </div>
      <section className="case-section case-timeline">
        <span className="eyebrow">AUDIT TRAIL / 变更时间线</span>
        <h3>每次判断都留下记录</h3>
        <small className="load-scope">
          已载入 {events.length} 条事件，按发生顺序展示。
        </small>
        {events.length ? (
          events.map((event) => (
            <details key={event.id}>
              <summary>
                <span>{dateLabel(event.created_at)}</span>
                <strong>{event.event_type}</strong>
                <small>#{event.id}</small>
              </summary>
              <JsonData
                data={isRecord(event.data) ? event.data : { value: event.data }}
              />
            </details>
          ))
        ) : (
          <p className="inline-empty">暂时没有变更事件。</p>
        )}
        <Failure value={eventsError} />
        {eventHasMore && (
          <button
            className="text-button"
            disabled={eventsLoading}
            onClick={() => {
              void loadEvents();
            }}
          >
            {eventsLoading ? "正在载入…" : "载入更多时间线 ↓"}
          </button>
        )}
      </section>
    </section>
  );
}
