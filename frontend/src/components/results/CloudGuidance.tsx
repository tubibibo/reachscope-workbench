import { ChevronDown } from "lucide-react";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { externalReferenceUrl } from "../../lib/security";

export function CloudGuidance({ value }: { value: unknown }) {
  if (!isRecord(value))
    return (
      <p className="cloud-guide-note">
        此历史检查未保存实施指引，可基于同一资产创建新任务后复核。
      </p>
    );
  const groups = [
    ["prerequisites", "变更前确认"],
    ["red_review", "红队：复核配置条件"],
    ["blue_steps", "蓝队：最小化配置范围"],
    ["verification", "复测与实际环境验收"],
    ["rollback", "回滚与业务回归"],
  ] as const;
  return (
    <details className="cloud-manual-guidance">
      <summary>
        查看云配置复核与补强指引 <ChevronDown size={14} />
      </summary>
      <p className="cloud-guide-note">
        依据本项保存的配置事实提供规则指引，不需要
        AI。执行任何变更前先核对账户、环境和业务范围，工作台不会修改云资源或自动关闭事项。
      </p>
      <div className="cloud-guide-location">
        <code>{readable(value.rule_id)}</code>
        <code>{readable(value.resource_id)}</code>
        <code>{readable(value.source_pointer)}</code>
      </div>
      <div className="cloud-manual-grid">
        {groups.map(([key, label]) => (
          <div key={key}>
            <h5>{label}</h5>
            {strings(value[key]).length ? (
              <ol>
                {strings(value[key]).map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            ) : (
              <p className="cloud-guide-note">未记录，需要补充人工验证计划。</p>
            )}
          </div>
        ))}
      </div>
      {strings(value.limitations).length > 0 && (
        <ul className="cloud-guidance-limits">
          {strings(value.limitations).map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
      <div className="cloud-guide-references">
        {records(value.references).map((reference, index) => {
          const url = externalReferenceUrl(reference.url);
          return url ? (
            <a href={url} key={index} target="_blank" rel="noopener noreferrer">
              {textValue(reference.title) || "规则参考"} ↗
            </a>
          ) : null;
        })}
      </div>
    </details>
  );
}
