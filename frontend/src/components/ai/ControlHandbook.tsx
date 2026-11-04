import { useEffect, useState } from "react";
import { BookOpen, ArrowRight } from "lucide-react";
import { aiApi } from "../../ai/api";
import type { ControlGuide } from "../../ai/types";
import { errorRequestId, errorText } from "../../lib/api";
import { ErrorBox, Loading } from "../Common";
import { externalReferenceUrl } from "../../lib/security";

export function ControlHandbook({
  reportId,
  jobId,
  controlId,
  onEvidence,
}: {
  reportId?: string;
  jobId?: string;
  controlId: string;
  onEvidence: (id: string) => void;
}) {
  const [open, setOpen] = useState(false),
    [environment, setEnvironment] = useState<"generic" | "nginx">("generic"),
    [guide, setGuide] = useState<ControlGuide | null>(null),
    [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setGuide(null);
    setError(null);
    const response = reportId
      ? aiApi.guide(reportId, controlId, environment, controller.signal)
      : aiApi.jobGuide(jobId!, controlId, environment, controller.signal);
    void response
      .then((value) => {
        if (!controller.signal.aborted) setGuide(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      });
    return () => controller.abort();
  }, [open, environment, reportId, jobId, controlId]);
  return (
    <div className="control-handbook">
      <button
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <BookOpen size={13} />
        {open ? "收起操作手册" : "打开证据与人工操作手册"}
      </button>
      {open && (
        <div className="control-handbook-body">
          <p>
            以下内容来自服务端维护的受控指南，关联本次保存的检查证据。不会运行命令或修改站点；技术环境需要由你确认。
          </p>
          <label className="checkbox-field">
            <input
              type="checkbox"
              aria-label={`确认 ${controlId} 使用 Nginx 查看人工模板`}
              checked={environment === "nginx"}
              onChange={(event) =>
                setEnvironment(event.target.checked ? "nginx" : "generic")
              }
            />
            <span>
              我确认使用 Nginx，查看人工模板
              <small>
                没有从服务指纹推断部署环境；片段需要人工审阅与适配。
              </small>
            </span>
          </label>
          {Boolean(error) && (
            <ErrorBox requestId={errorRequestId(error)}>
              {errorText(error)}
            </ErrorBox>
          )}
          {!guide && !error && <Loading label="正在读取受控操作指南…" />}
          {guide && (
            <>
              <div className="handbook-signals">
                <strong>原检查与来源证据</strong>
                {guide.signal_statuses.length ? (
                  guide.signal_statuses.map((signal, index) => (
                    <div key={`${signal.check_id}-${index}`}>
                      <code>{signal.check_id}</code>
                      <span>{signal.status}</span>
                      {signal.evidence_ids.map((id) => (
                        <button
                          className="text-button"
                          key={id}
                          onClick={() => onEvidence(id)}
                        >
                          定位 {id.slice(0, 14)}
                          <ArrowRight size={11} />
                        </button>
                      ))}
                    </div>
                  ))
                ) : (
                  <p>没有可关联的自动检查状态；仅作人工核查方向。</p>
                )}
              </div>
              {(
                [
                  ["适用前提", guide.preconditions],
                  ["红队人工核查", guide.red_review],
                  ["蓝队处理步骤", guide.blue_steps],
                  ["复核方法", guide.verification],
                  ["验收标准", guide.acceptance],
                  ["回滚计划", guide.rollback],
                ] as const
              ).map(([title, values]) => (
                <div className="handbook-group" key={title}>
                  <strong>{title}</strong>
                  <ol>
                    {values.map((value, index) => (
                      <li key={index}>{value}</li>
                    ))}
                  </ol>
                </div>
              ))}
              {environment === "nginx" &&
                (guide.templates.length ? (
                  guide.templates.map((template, index) => (
                    <section className="handbook-template" key={index}>
                      <h5>{template.title}</h5>
                      <p>{template.context}</p>
                      <strong>适配条件</strong>
                      <ul>
                        {template.conditions.map((value) => (
                          <li key={value}>{value}</li>
                        ))}
                      </ul>
                      <pre
                        tabIndex={0}
                        aria-label={`${template.title} 人工审阅模板`}
                      >
                        <code>{template.content}</code>
                      </pre>
                      <ul>
                        {template.limitations.map((value) => (
                          <li key={value}>{value}</li>
                        ))}
                      </ul>
                    </section>
                  ))
                ) : (
                  <p>此条目没有受审核的 Nginx 片段，请按通用人工流程处理。</p>
                ))}
              <ul>
                {guide.limitations.map((value) => (
                  <li key={value}>{value}</li>
                ))}
              </ul>
              <div className="ai-references">
                {guide.references.map((reference, index) => {
                  const href = externalReferenceUrl(reference.url);
                  return href ? (
                    <a
                      key={index}
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      referrerPolicy="no-referrer"
                    >
                      {reference.title} ↗<small>{reference.kind}</small>
                    </a>
                  ) : (
                    <span key={index}>{reference.title}</span>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
