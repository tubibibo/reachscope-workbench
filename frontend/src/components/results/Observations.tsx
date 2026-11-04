import { useState } from "react";
import { ArrowRight, ChevronDown, ShieldAlert } from "lucide-react";
import type { Observation } from "../../lib/types";

export function Observations({
  observations,
  onEvidence,
}: {
  observations: Observation[];
  onEvidence: (id: string) => void;
}) {
  const [severity, setSeverity] = useState("all");
  const selected = observations.filter(
    (item) => severity === "all" || item.severity === severity,
  );
  return (
    <section className="result-section">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">OBSERVATIONS</span>
          <h3>
            观察与检查建议 <span>{observations.length}</span>
          </h3>
        </div>
        <select
          aria-label="按观察等级筛选"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
        >
          <option value="all">全部等级</option>
          {Array.from(new Set(observations.map((item) => item.severity))).map(
            (item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ),
          )}
        </select>
      </div>
      {!observations.length ? (
        <p className="inline-empty">
          本次分析没有生成观察项。缺少提示不等于目标安全。
        </p>
      ) : !selected.length ? (
        <p className="inline-empty">没有这一等级的观察项。</p>
      ) : (
        <div className="observations">
          {selected.map((item) => (
            <details className="observation" key={item.id}>
              <summary>
                <span className={`severity-dot severity-${item.severity}`} />
                <strong>{item.title}</strong>
                <span className="observation-category">{item.category}</span>
                <span className={`severity-label severity-${item.severity}`}>
                  {item.severity}
                </span>
                <ChevronDown size={14} />
              </summary>
              <div className="observation-body">
                <p>{item.description}</p>
                {item.recommendation && (
                  <div className="recommendation">
                    <ShieldAlert size={15} />
                    <span>{item.recommendation}</span>
                  </div>
                )}
                <div className="observation-meta">
                  <span>依据：{item.confidence}</span>
                  {item.evidence_ids.map((id) => (
                    <button
                      type="button"
                      key={id}
                      onClick={() => onEvidence(id)}
                    >
                      查看证据 <ArrowRight size={12} />
                    </button>
                  ))}
                </div>
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
