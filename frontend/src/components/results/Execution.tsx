import type { ModuleResult } from "../../lib/types";
import { readable, records, textValue } from "../../lib/types";
const labels: Record<string, string> = {
  completed: "已执行",
  skipped: "未选择",
  failed: "执行失败",
  unknown: "信息不足",
};
export function Execution({ result }: { result: ModuleResult }) {
  const rows = records(result.details.execution);
  if (!rows.length) return null;
  return (
    <section className="execution-scope" aria-label="本次执行范围">
      <span className="eyebrow">THIS RUN / 本次执行</span>
      <div>
        {rows.map((item, index) => (
          <details key={textValue(item.id) || index}>
            <summary>
              <i
                className={`execution-dot execution-${textValue(item.status)}`}
              />
              <strong>{readable(item.label || item.id)}</strong>
              <span>
                {labels[textValue(item.status)] || readable(item.status)}
              </span>
            </summary>
            <p>{readable(item.reason)}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
