import { useEffect, useState } from "react";
import { ArrowRight, BookOpen } from "lucide-react";
import { aiApi } from "../../ai/api";
import type { JobControls } from "../../ai/types";
import { errorRequestId, errorText } from "../../lib/api";
import { ErrorBox, Loading } from "../Common";
import { ControlHandbook } from "../ai/ControlHandbook";

const states: Record<string, string> = {
  pass: "本项满足检查条件",
  review: "本项待人工复核",
  unknown: "本项信息不足",
  info: "记录信息",
  not_applicable: "本项不适用",
};
export function JobControlGuides({
  jobId,
  onEvidence,
}: {
  jobId: string;
  onEvidence: (id: string) => void;
}) {
  const [data, setData] = useState<JobControls | null>(null),
    [error, setError] = useState<unknown>(null),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    void aiApi
      .jobControls(jobId, controller.signal)
      .then(setData)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      });
    return () => controller.abort();
  }, [jobId, revision]);
  return (
    <section className="result-section job-control-guides">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">DETERMINISTIC / SAVED EVIDENCE</span>
          <h3>配置实施指南</h3>
        </div>
        <BookOpen size={22} />
      </div>
      <p className="section-description">
        按本次实际执行的检查和保存证据匹配受控指南，不需要 AI 或 API
        密钥。待复核项先确认适用性，满足项保持验证，未知项先补齐证据；打开指南不会制造新发现或执行修复。
      </p>
      {Boolean(error) && (
        <ErrorBox
          requestId={errorRequestId(error)}
          retry={() => setRevision((value) => value + 1)}
        >
          {errorText(error)}
        </ErrorBox>
      )}
      {!data && !error && <Loading label="正在读取证据对应的指南…" />}
      {data && (
        <>
          {data.origin === "local_training" && (
            <p className="scope-note">
              本地教学资产：以下是内置站点的真实loopback采集，不是生产站点检测结论。
            </p>
          )}
          {data.origin === "cloud_service_probe" && (
            <p className="scope-note">
              云服务 HTTP(S)
              观察：指南只对应保存的响应证据，不代表已读取云账号配置、验证安全组生效或计算
              IAM 权限。
            </p>
          )}
          {data.items.length ? (
            <div className="job-guide-grid">
              {data.items.map((item) => (
                <article
                  className="ai-advice-card"
                  data-control-id={item.control_id}
                  key={item.control_id}
                >
                  <code>{item.control_id}</code>
                  <h4>{item.title}</h4>
                  <div className="guide-check-states">
                    {item.states.map((state) => (
                      <span key={state}>{states[state] || state}</span>
                    ))}
                  </div>
                  <div className="ai-evidence-links">
                    {item.evidence_ids.map((id) => (
                      <button
                        className="text-button"
                        key={id}
                        onClick={() => onEvidence(id)}
                      >
                        来源证据 {id.slice(0, 14)}
                        <ArrowRight size={11} />
                      </button>
                    ))}
                  </div>
                  <ControlHandbook
                    jobId={jobId}
                    controlId={item.control_id}
                    onEvidence={onEvidence}
                  />
                </article>
              ))}
            </div>
          ) : (
            <p className="inline-empty">
              本次没有匹配到已执行且有证据的配置检查。未选择、未采集或不受支持的内容不会补记为已检查。
            </p>
          )}
          <details className="limitations">
            <summary>指南适用范围</summary>
            <ul>
              {data.limitations.map((value) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}
