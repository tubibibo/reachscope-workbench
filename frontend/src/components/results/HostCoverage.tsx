import { isRecord, readable, records, textValue } from "../../lib/types";
import { JsonData } from "./JsonData";

const labels: Record<string, string> = {
  total_lines: "文件行数",
  examined_lines: "已检查行数",
  parsed_events: "解析事件",
  returned_events: "已保存事件",
  unparsed_lines: "未解析行",
  unsupported_lines: "不支持记录",
  timestamp_unknown_events: "时间未知事件",
  invalid_ip_lines: "无效客户端地址",
  overlong_lines: "超长行",
  duplicate_events: "重复记录",
};

export function HostCoverage({ value }: { value: unknown }) {
  const parts = Array.isArray(value)
    ? records(value)
    : isRecord(value)
      ? [value]
      : [];
  return (
    <div className="host-coverage">
      {parts.map((part, index) => {
        const rows = records(part.components);
        const metrics = Object.entries(labels).filter(
          ([key]) => typeof part[key] === "number",
        );
        return (
          <section key={index} className="host-coverage-part">
            {parts.length > 1 && <h4>资料片段 {index + 1}</h4>}
            {typeof part.collected_at === "string" && (
              <p className="host-note">
                资料声明采集时间：<code>{part.collected_at}</code>
                。该时间由输入提供，未独立验证。
              </p>
            )}
            {Boolean(part.collection_state) && (
              <p className="host-note">
                {part.collection_state === "known" ||
                part.collection_state === "provided"
                  ? "输入包含可解析的采集时间，仍需人工核对来源。"
                  : "配置来源与采集上下文需结合导出过程核对。"}
              </p>
            )}
            {rows.length > 0 && (
              <div className="table-scroll">
                <table className="host-coverage-table">
                  <thead>
                    <tr>
                      <th>资料组件</th>
                      <th>本次选择</th>
                      <th>已提供资料</th>
                      <th>输入字节</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i}>
                        <td>
                          {textValue(row.id) === "ssh"
                            ? "SSH 有效配置"
                            : "Nginx 配置导出"}
                        </td>
                        <td>{row.selected === true ? "已选择" : "未选择"}</td>
                        <td>{row.provided === true ? "已提供" : "缺少资料"}</td>
                        <td>{readable(row.bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {metrics.length > 0 && (
              <dl className="host-coverage-counts">
                {metrics.map(([key, label]) => (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{readable(part[key])}</dd>
                  </div>
                ))}
              </dl>
            )}
            {part.truncated === true && (
              <p className="scope-note">
                本片段触及分析或展示预算，覆盖不完整。截断资料不能用于证明安全或整改成功。
              </p>
            )}
            {part.complete === false && (
              <p className="scope-note">
                解析存在覆盖缺口，请补齐可解释的记录与时间信息后再复核。
              </p>
            )}
            <details className="host-facts">
              <summary>查看完整覆盖元数据</summary>
              <JsonData data={part} />
            </details>
          </section>
        );
      })}
      {!parts.length && (
        <p className="host-note">此记录未保存覆盖元数据，不能推断检查完整。</p>
      )}
    </div>
  );
}
