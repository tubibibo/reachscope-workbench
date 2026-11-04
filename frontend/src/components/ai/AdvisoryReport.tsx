import { ArrowRight, FileDown } from "lucide-react";
import { aiApi } from "../../ai/api";
import type {
  AdvisoryItem,
  AdvisoryReport as SavedReport,
} from "../../ai/types";
import { dateLabel } from "../../lib/types";
import { externalReferenceUrl } from "../../lib/security";
import { ErrorBox } from "../Common";
import { ControlHandbook } from "./ControlHandbook";

const statusLabels = {
  running: "研判进行中",
  completed: "已生成 / 人工待复核",
  failed: "调用失败",
  interrupted: "会话中断",
};
const priorityLabels = {
  high: "优先核查",
  medium: "常规核查",
  low: "补充核查",
};
function AdviceColumn({
  title,
  subtitle,
  items,
  onEvidence,
  reportId,
}: {
  title: string;
  subtitle: string;
  items: AdvisoryItem[];
  onEvidence: (id: string) => void;
  reportId: string;
}) {
  return (
    <section className="ai-advice-column">
      <span className="eyebrow">{subtitle}</span>
      <h3>
        {title}
        <span>{items.length}</span>
      </h3>
      {items.length ? (
        items.map((item, index) => (
          <article
            className="ai-advice-card"
            key={`${item.control_id}-${index}`}
          >
            <div className="ai-control-meta">
              <code>{item.control_id}</code>
              <span>{priorityLabels[item.priority]}</span>
            </div>
            <h4>{item.title}</h4>
            <p className="ai-applicability">
              {item.applicability === "web_config"
                ? "站点配置 / 来自已执行检查"
                : item.applicability === "endpoint_hygiene"
                  ? "端点治理参考 / 未检测此电脑"
                  : "应用与运维 / 需要人工评审"}
              {item.basis === "manual_review" && " · 无自动检测结论"}
            </p>
            <ul>
              {item.actions.map((value, index) => (
                <li key={index}>{value}</li>
              ))}
            </ul>
            <div className="ai-evidence-links">
              {item.evidence_ids.map((id) => (
                <button
                  key={id}
                  className="text-button"
                  onClick={() => onEvidence(id)}
                >
                  来源证据 {id.slice(0, 15)} <ArrowRight size={11} />
                </button>
              ))}
              {!item.evidence_ids.length && (
                <small>没有对应的工具证据，需要人工建立依据。</small>
              )}
            </div>
            <details>
              <summary>复核方式、适用限制与公开来源</summary>
              <strong>复核方式</strong>
              <ul>
                {item.verification.map((value, index) => (
                  <li key={index}>{value}</li>
                ))}
              </ul>
              <strong>适用限制</strong>
              <ul>
                {item.limitations.map((value, index) => (
                  <li key={index}>{value}</li>
                ))}
              </ul>
              <div className="ai-references">
                {item.references.map((reference, index) => {
                  const href = externalReferenceUrl(reference.url);
                  return href ? (
                    <a
                      href={href}
                      key={index}
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
            </details>
            <ControlHandbook
              key={`${reportId}:${item.control_id}`}
              reportId={reportId}
              controlId={item.control_id}
              onEvidence={onEvidence}
            />
          </article>
        ))
      ) : (
        <p className="inline-empty">
          本次没有选择此类条目；这不代表对应风险不存在。
        </p>
      )}
    </section>
  );
}
export function AdvisoryReport({
  report,
  onEvidence,
  newRound,
}: {
  report: SavedReport;
  onEvidence: (id: string) => void;
  newRound: () => void;
}) {
  return (
    <section className="ai-saved-report" aria-label="AI 研判报告">
      <header className="ai-report-heading">
        <div>
          <span className="eyebrow">
            SAVED ADVISORY / {report.id.slice(0, 8)}
          </span>
          <h3>{statusLabels[report.status]}</h3>
          <p>
            {report.provider.model || "未指定模型"} · {report.provider.base_url}{" "}
            · {dateLabel(report.created_at)}
          </p>
        </div>
        {report.status !== "running" && (
          <button className="button" onClick={newRound}>
            新一轮研判 <ArrowRight size={13} />
          </button>
        )}
      </header>
      {report.provider.model.startsWith("protocol-fixture-") && (
        <p className="ai-ineligible">
          本机协议模拟：用于验证接口与状态流程，不代表真实模型质量或服务商验收。
        </p>
      )}
      {report.status === "running" && (
        <p className="ai-pending" role="status">
          正在等待兼容接口返回。报告标识已经保存；离开页面不会自动重发，稍后可从历史打开。
        </p>
      )}
      {report.error && (
        <ErrorBox>
          {report.error.message}{" "}
          <small>记录状态：{report.status}；没有自动重新调用。</small>
        </ErrorBox>
      )}
      {report.status === "completed" && (
        <>
          <p className="ai-report-boundary">
            AI
            根据发送的摘要选择受控目录条目与优先次序。建议文字与公开来源随条目保留，尚未经过人工验证；红队核查方向不等于已证实漏洞，蓝队清单不等于已完成修复。
          </p>
          <div className="ai-advice-columns">
            <AdviceColumn
              title="红队核查方向"
              subtitle="RED / HUMAN REVIEW"
              items={report.red}
              reportId={report.id}
              onEvidence={onEvidence}
            />
            <AdviceColumn
              title="蓝队配置补强"
              subtitle="BLUE / HARDENING"
              items={report.blue}
              reportId={report.id}
              onEvidence={onEvidence}
            />
          </div>
          <div className="ai-report-exports">
            <a
              className="button"
              href={aiApi.exportUrl(report.id, "html")}
              download
            >
              <FileDown size={13} />
              研判报告
            </a>
            <a
              className="text-button"
              href={aiApi.exportUrl(report.id, "json")}
              download
            >
              JSON ↗
            </a>
            <code>摘要 SHA-256 / {report.context_sha256}</code>
          </div>
        </>
      )}
      {report.limitations.length > 0 && (
        <details className="ai-disclosure">
          <summary>研判限制</summary>
          <ul>
            {report.limitations.map((value, index) => (
              <li key={index}>{value}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
