import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, RefreshCw } from "lucide-react";
import { ApiError, errorRequestId, errorText } from "../../lib/api";
import { aiApi } from "../../ai/api";
import type {
  AdvisoryMetadata,
  AdvisoryPreview,
  AdvisoryReport as SavedReport,
} from "../../ai/types";
import { dateLabel } from "../../lib/types";
import { ErrorBox, Loading } from "../Common";
import { JsonData } from "../results/JsonData";
import { AdvisoryReport } from "./AdvisoryReport";

interface Submission {
  key: string;
  payload: {
    context_sha256: string;
    consent: true;
    authorization_note: string;
  };
}
export function WebAdvisory({
  jobId,
  onEvidence,
}: {
  jobId: string;
  onEvidence: (id: string) => void;
}) {
  const [preview, setPreview] = useState<AdvisoryPreview | null>(null),
    [history, setHistory] = useState<AdvisoryMetadata[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<unknown>(null),
    [report, setReport] = useState<SavedReport | null>(null),
    [reportError, setReportError] = useState<unknown>(null),
    [authorization, setAuthorization] = useState(""),
    [consent, setConsent] = useState(false),
    [consentContext, setConsentContext] = useState(""),
    [busy, setBusy] = useState(false),
    [attempted, setAttempted] = useState(false),
    [pollRevision, setPollRevision] = useState(0);
  const operation = useRef<Submission | null>(null),
    busyRef = useRef(false),
    reportRequest = useRef<AbortController | null>(null),
    initialRead = useRef(true);
  const currentConsent = Boolean(
    consent && preview && consentContext === preview.context_sha256,
  );
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void Promise.all([
      aiApi.preview(jobId, controller.signal),
      aiApi.reports(jobId, offset, controller.signal),
    ])
      .then(([value, page]) => {
        if (active) {
          // An ambiguous submission is confirmed with its original operation
          // and preview, never silently rebound to a refreshed provider.
          setPreview((previous) =>
            operation.current ? (previous ?? value) : value,
          );
          setHistory((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((entry) => [
                      entry.id,
                      entry,
                    ]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
          if (initialRead.current) {
            initialRead.current = false;
            if (page.items[0]) void openReport(page.items[0].id);
          }
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
  }, [jobId, revision, offset]);
  useEffect(() => () => reportRequest.current?.abort(), [jobId]);
  useEffect(() => {
    if (!report || report.status !== "running") return;
    const controller = new AbortController();
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const value = await aiApi.report(report.id, controller.signal);
        if (active) {
          setReport(value);
          if (value.status === "running")
            timer = window.setTimeout(() => {
              void poll();
            }, 1000);
          else {
            setOffset(0);
            setRevision((value) => value + 1);
          }
        }
      } catch (failure) {
        if (active) setReportError(failure);
      }
    };
    timer = window.setTimeout(() => {
      void poll();
    }, 1000);
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
      controller.abort();
    };
  }, [report?.id, report?.status, pollRevision]);
  async function openReport(id: string) {
    reportRequest.current?.abort();
    const controller = new AbortController();
    reportRequest.current = controller;
    setReportError(null);
    try {
      const value = await aiApi.report(id, controller.signal);
      if (!controller.signal.aborted) {
        setReport(value);
        setPollRevision((value) => value + 1);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setReportError(failure);
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!preview || !currentConsent || !authorization.trim() || busyRef.current)
      return;
    busyRef.current = true;
    setBusy(true);
    setAttempted(true);
    setError(null);
    operation.current ??= {
      key: crypto.randomUUID(),
      payload: {
        context_sha256: preview.context_sha256,
        consent: true,
        authorization_note: authorization.trim(),
      },
    };
    try {
      setReport(
        await aiApi.submit(
          jobId,
          operation.current.payload,
          operation.current.key,
        ),
      );
      setReportError(null);
      setOffset(0);
      setRevision((value) => value + 1);
    } catch (failure) {
      setError(failure);
      if (
        failure instanceof ApiError &&
        [400, 403, 422].includes(failure.status)
      ) {
        operation.current = null;
        setAttempted(false);
      }
      if (failure instanceof ApiError && failure.code === "AI_PREVIEW_STALE") {
        operation.current = null;
        setAttempted(false);
        setConsent(false);
        setConsentContext("");
        setRevision((value) => value + 1);
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  function newRound() {
    operation.current = null;
    setAttempted(false);
    setReport(null);
    setConsent(false);
    setConsentContext("");
    setAuthorization("");
    setError(null);
    setOffset(0);
    setRevision((value) => value + 1);
  }
  const canSend = Boolean(
    preview?.eligible &&
      preview.provider.enabled &&
      preview.provider.has_key &&
      preview.provider.model,
  );
  return (
    <section className="web-ai-advisory">
      <div className="ai-section-heading">
        <div>
          <span className="eyebrow">EVIDENCE TO REVIEW / 按需 AI 研判</span>
          <h3>同一份证据，两种下一步。</h3>
          <p>
            把已保存的检查摘要交给你选择的接口，整理红队人工核查方向与蓝队补强清单。
          </p>
        </div>
        <a className="button" href="#/settings/ai">
          AI 接口设置 <ArrowRight size={13} />
        </a>
      </div>
      {Boolean(error) && (
        <ErrorBox requestId={errorRequestId(error)}>
          {errorText(error)}
        </ErrorBox>
      )}
      {loading && !preview ? (
        <Loading label="正在准备本地发送预览…" />
      ) : (
        preview && (
          <>
            {!preview.eligible ? (
              <p className="ai-ineligible">
                {preview.reason || "这条记录尚不满足真实网站 AI 研判条件。"}{" "}
                当前结果仍可独立查看。
              </p>
            ) : (
              <>
                <div className="ai-provider-state">
                  <span>
                    {canSend ? (
                      <>
                        <Check size={13} />
                        接口已配置
                      </>
                    ) : (
                      "接口尚未准备好"
                    )}
                  </span>
                  <code>
                    {preview.provider.model || "未填写模型"} /{" "}
                    {preview.provider.base_url}
                  </code>
                  <small>预览只在本机生成；尚未发送给模型接口。</small>
                </div>
                {!report && (
                  <form
                    className="ai-consent-form"
                    onSubmit={(event) => {
                      void submit(event);
                    }}
                  >
                    <details className="ai-disclosure">
                      <summary>
                        审阅即将发送的脱敏摘要 · {preview.disclosure.bytes} 字节
                      </summary>
                      <JsonData data={preview.context} />
                      <code>SHA-256 / {preview.context_sha256}</code>
                    </details>
                    <details className="ai-disclosure ai-control-catalog">
                      <summary>
                        本次可用的受控目录 · {preview.controls.length} 项
                      </summary>
                      <div className="ai-control-grid">
                        {preview.controls.map((control) => (
                          <article key={control.id}>
                            <code>{control.id}</code>
                            <strong>{control.title}</strong>
                            <small>
                              {control.applicability === "web_config"
                                ? "站点配置"
                                : control.applicability === "endpoint_hygiene"
                                  ? "端点防护参考"
                                  : "需人工评审"}
                            </small>
                          </article>
                        ))}
                      </div>
                      <p className="field-hint">
                        模型只能从这些稳定 ID 中选择，并只能引用预览中已有的证据
                        ID；目录本身不会宣称已发现问题。
                      </p>
                    </details>
                    <div className="ai-disclosure-columns">
                      <div>
                        <strong>发送的字段</strong>
                        <ul>
                          {preview.disclosure.fields.map((value, index) => (
                            <li key={index}>{value}</li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <strong>排除的内容</strong>
                        <ul>
                          {preview.disclosure.excluded.map((value, index) => (
                            <li key={index}>{value}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <label className="field">
                      <span className="field-label">本次授权与用途说明</span>
                      <textarea
                        aria-label="AI 研判授权说明"
                        rows={3}
                        maxLength={1000}
                        value={authorization}
                        disabled={busy || attempted}
                        onChange={(event) =>
                          setAuthorization(event.target.value)
                        }
                        placeholder="说明该资产的授权范围，以及本次摘要发送的用途。"
                        required
                      />
                    </label>
                    <label className="checkbox-field">
                      <input
                        type="checkbox"
                        aria-label="确认发送 AI 摘要"
                        checked={currentConsent}
                        disabled={busy || attempted}
                        onChange={(event) => {
                          setConsent(event.target.checked);
                          setConsentContext(
                            event.target.checked ? preview.context_sha256 : "",
                          );
                        }}
                      />
                      <span>
                        我已审阅摘要，确认向当前接口发送
                        <small>
                          调用可能产生服务商费用；结果需要人工复核，不执行攻击或配置修改。
                        </small>
                      </span>
                    </label>
                    {attempted && !busy && (
                      <p className="field-hint">
                        上次提交结果尚未确认。再次确认使用原说明与同一操作标识，不会自动发起新调用；也可从历史打开已保存的报告。
                      </p>
                    )}
                    <button
                      type="submit"
                      className="button button-primary"
                      disabled={
                        busy ||
                        !canSend ||
                        !currentConsent ||
                        !authorization.trim()
                      }
                    >
                      {busy
                        ? "正在确认提交…"
                        : attempted
                          ? "确认原研判请求"
                          : "发送摘要并生成研判"}
                      <ArrowRight size={14} />
                    </button>
                  </form>
                )}
              </>
            )}
            {Boolean(reportError) && (
              <ErrorBox
                retry={() => {
                  if (report) void openReport(report.id);
                }}
                requestId={errorRequestId(reportError)}
              >
                {errorText(reportError)}
              </ErrorBox>
            )}
            {report && (
              <AdvisoryReport
                report={report}
                onEvidence={onEvidence}
                newRound={newRound}
              />
            )}
            <section className="ai-history">
              <div>
                <span className="eyebrow">SAVED REPORTS / 调用历史</span>
                <h4>
                  研判记录{" "}
                  <span>
                    {history.length}/{total}
                  </span>
                </h4>
                <button
                  className="text-button"
                  disabled={loading || busy}
                  onClick={() => {
                    setOffset(0);
                    setRevision((value) => value + 1);
                  }}
                >
                  <RefreshCw size={12} />
                  刷新记录
                </button>
              </div>
              {history.length ? (
                history.map((item) => (
                  <button
                    className={`ai-history-row ${report?.id === item.id ? "selected" : ""}`}
                    key={item.id}
                    onClick={() => {
                      void openReport(item.id);
                    }}
                  >
                    <span>
                      {item.provider.model || "兼容接口"}
                      <small>{item.provider.base_url}</small>
                    </span>
                    <span>
                      {item.status}
                      <small>{dateLabel(item.created_at)}</small>
                    </span>
                    <ArrowRight size={13} />
                  </button>
                ))
              ) : (
                <p className="inline-empty">
                  尚未保存研判记录。普通检查不会自动调用 AI。
                </p>
              )}
              {history.length < total && (
                <button
                  className="text-button"
                  disabled={loading}
                  onClick={() => setOffset(history.length)}
                >
                  载入更多研判 ↓
                </button>
              )}
            </section>
          </>
        )
      )}
    </section>
  );
}
