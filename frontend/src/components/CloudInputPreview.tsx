import { FileSearch } from "lucide-react";
import type { CloudInputPreview as Preview } from "../lib/types";
import "./results/cloud-review.css";

const kinds: Record<string, string> = {
  terraform_plan: "Terraform Plan JSON",
  iam_policy: "IAM 策略 JSON",
  security_groups_export: "安全组配置导出",
  s3_public_access_block_export: "S3 公开访问保护导出",
};
const gaps: Record<string, string> = {
  missing: "缺少字段",
  unknown: "计划未知值",
  redacted: "敏感值已脱敏",
  invalid: "字段结构不支持",
};

export function CloudInputPreview({ preview }: { preview: Preview }) {
  return (
    <section className="cloud-input-preview" aria-label="云配置输入预览">
      <header>
        <div>
          <span className="eyebrow">INPUT / BEFORE EXECUTION</span>
          <h4>配置已解析，先确认覆盖范围</h4>
        </div>
        <FileSearch size={20} />
      </header>
      <p>
        识别格式：
        <strong>{kinds[preview.input_kind] || preview.input_kind}</strong>
        。仅解析本地已保存文件，没有执行安全规则或发送网络请求；点击“开始检查”后才创建任务。
      </p>
      <dl className="cloud-preview-counts">
        <div>
          <dt>识别资源</dt>
          <dd>{preview.resources_total}</dd>
        </div>
        <div>
          <dt>有支持规则</dt>
          <dd>{preview.supported_resources}</dd>
        </div>
        <div>
          <dt>仅列入清单</dt>
          <dd>{preview.unsupported_resources}</dd>
        </div>
      </dl>
      {preview.resource_types.length > 0 && (
        <div className="cloud-resource-types">
          {preview.resource_types.map((type) => (
            <span key={type.type}>
              <code>{type.type}</code>
              <strong>× {type.count}</strong>
              <small>{type.supported ? "支持规则" : "未覆盖类型"}</small>
            </span>
          ))}
        </div>
      )}
      <div className="table-scroll">
        <table className="cloud-preview-table">
          <thead>
            <tr>
              <th>已选检查组</th>
              <th>适用资源</th>
              <th>已提供字段</th>
              <th>缺失</th>
              <th>未知</th>
              <th>脱敏</th>
              <th>结构异常</th>
            </tr>
          </thead>
          <tbody>
            {preview.group_coverage.map((group) => (
              <tr key={group.id}>
                <td>{group.label}</td>
                <td>{group.applicable_resources}</td>
                <td>{group.known_fields}</td>
                <td>{group.missing_fields}</td>
                <td>{group.unknown_fields}</td>
                <td>{group.redacted_fields}</td>
                <td>{group.invalid_fields}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="cloud-preview-scope">
        资源类型有支持规则不表示已检查或已经通过。实际执行仅包含已选组；字段数量描述输入覆盖，不代表风险或安全得分。
      </p>
      {preview.field_gaps_total > 0 && (
        <details className="cloud-preview-gaps">
          <summary>
            查看缺失、未知或不支持的字段（{preview.field_gaps_total} 项）
          </summary>
          <ul>
            {preview.field_gaps.map((gap, index) => (
              <li key={index}>
                <span>{gaps[gap.state] || "未解释字段"}</span>
                <code>
                  {gap.resource_id} / {gap.resource_type}
                </code>
                <code>
                  {gap.pointer} · {gap.field}
                </code>
              </li>
            ))}
          </ul>
        </details>
      )}
      {preview.truncated && (
        <p className="cloud-preview-warning">
          预览达到返回上限，未显示全部字段缺口；未显示的内容不能当作完整覆盖。
        </p>
      )}
      <details className="cloud-preview-limits">
        <summary>文件身份与预览边界</summary>
        <code className="cloud-preview-digest">SHA-256 / {preview.sha256}</code>
        <ul>
          {preview.limitations.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
