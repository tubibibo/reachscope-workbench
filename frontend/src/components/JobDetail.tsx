import { SourceBadge } from "../components/SourceBadge";
import { useJob } from "../hooks/useJobs";
import { api, errorRequestId, errorText } from "../lib/api";
import { jobAssetKind } from "../lib/hash-route";
import type { DetailTab } from "../lib/hash-route";
import { sourceOfJob } from "../lib/inspection-source";
import {
  dateLabel,
  isActive,
  moduleLabel,
  statusLabelText,
} from "../lib/types";
import { useEffect, useRef, useState } from "react";
import { isRecord } from "../lib/types";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Boxes,
  FileCode2,
  LoaderCircle,
  RefreshCw,
  Square,
} from "lucide-react";
import {
  Empty,
  ErrorBox,
  KeyValues,
  LinkButton,
  Loading,
  ProgressBar,
  StatusTag,
} from "../components/Common";
import {
  AndroidResult,
  CloudResult,
  EvidenceView,
  Execution,
  HostResult,
  Limitations,
  ResultBrief,
  ResultSummary,
  WebResult,
} from "./ResultViews";

export function JobDetail({
  id,
  back,
  changed,
  announce,
}: {
  id: string;
  back: () => void;
  changed: () => void;
  announce: (message: string) => void;
}) {
  const { job, events, error, loading, refresh } = useJob(id);
  const previousStatus = useRef<string | null>(null);
  useEffect(() => {
    if (!job) return;
    if (previousStatus.current && previousStatus.current !== job.status) {
      announce(
        isActive(job)
          ? `任务 ${job.name} 开始执行`
          : `任务 ${job.name} ${statusLabelText(job.status)}`,
      );
    }
    previousStatus.current = job.status;
  }, [job, announce]);
  const [tab, setTab] = useState<DetailTab>("result");
  const [confirmRetry, setConfirmRetry] = useState(false);
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
  // A completed run that produced zero responses while recording request
  // failures did not "succeed" in any user-facing sense — label it as such.
  const summary = result && isRecord(result.summary) ? result.summary : null;
  const zeroData =
    job.status === "completed" &&
    summary !== null &&
    Number(summary.online ?? 0) === 0 &&
    Number(summary.errors ?? 0) > 0;
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
            {zeroData ? (
              <span className="status-tag status-failed">
                采集失败 · 未取得数据
              </span>
            ) : (
              <StatusTag status={job.status} />
            )}
            <span className="mono">{job.id}</span>
            <span>{dateLabel(job.created_at)}</span>
            <button
              type="button"
              className="icon-button"
              aria-label="刷新任务详情"
              onClick={() => {
                refresh();
                announce("任务详情已刷新");
              }}
            >
              <RefreshCw size={13} />
            </button>
            <span className="mono">最后更新 {dateLabel(job.updated_at)}</span>
            {job.asset_id && (
              <a className="text-button" href={`#/assets/${job.asset_id}`}>
                查看所属资产 <ArrowUpRight size={12} />
              </a>
            )}
            {sourceOfJob(job).kind === "training" && (
              <a className="text-button" href="#/lab">
                返回本地教学
              </a>
            )}
          </div>
        </div>
        <div className="detail-actions">
          {result && job.status === "completed" && (
            <>
              <LinkButton href={api.exportUrl(id, "json")}>
                导出 JSON
              </LinkButton>
              <LinkButton href={api.exportUrl(id, "html")}>
                导出报告（HTML）
              </LinkButton>
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
                if (!confirmRetry) {
                  setConfirmRetry(true);
                  announce("再次点击确认重新分析");
                  window.setTimeout(() => setConfirmRetry(false), 3000);
                  return;
                }
                setConfirmRetry(false);
                void action("retry");
              }}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              {confirmRetry ? "确认重新分析" : "重新分析"}
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
            aria-controls="detail-panel"
            onClick={() => {
              setTab(item.id);
              requestAnimationFrame(() => {
                document
                  .getElementById("detail-panel")
                  ?.focus({ preventScroll: true });
              });
            }}
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
      <div
        role="tabpanel"
        id="detail-panel"
        className="detail-body"
        tabIndex={-1}
      >
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
                模块: moduleLabel[job.module],
                资产:
                  job.asset_snapshot?.name ||
                  (job.asset_id ? job.asset_id : "历史记录未关联资产"),
                状态: statusLabelText(job.status),
                创建时间: dateLabel(job.created_at),
                更新时间: dateLabel(job.updated_at),
              }}
            />
            {job.module === "web" &&
              isRecord(job.config) &&
              job.config.allow_private === false && (
                <p className="field-hint">
                  是否允许本机/内网地址：否。如果目标就在本机或内网，请在“新建检查”第
                  2 步勾选「包含我的本机或内网地址」后重新分析。
                </p>
              )}
            <details className="input-raw">
              <summary>原始输入（调试用）</summary>
              <pre className="data-block">
                {JSON.stringify(job.config, null, 2)}
              </pre>
            </details>
            <p className="scope-note">
              重试会使用相同输入创建新的任务，原始分析记录会保留。
            </p>
          </section>
        )}
      </div>
    </>
  );
}
