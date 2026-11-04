import type { HostInputPreview as Preview } from "../lib/types";
import { readable } from "../lib/types";
import { HostCoverage } from "./results/HostCoverage";
import { HostCollection } from "./results/HostCollection";
import "./results/host-results.css";

export function HostInputPreview({ preview }: { preview: Preview }) {
  const label =
    preview.input_kind === "baseline"
      ? "主机配置资料"
      : preview.input_kind === "demo"
        ? "合成教学资料"
        : "日志文件";
  return (
    <section className="host-input-preview" aria-label="主机输入预览">
      <span className="eyebrow">LOCAL INPUT / BEFORE EXECUTION</span>
      <h4>先确认资料，再创建检查</h4>
      <p>
        {label} · 主机标识 <code>{readable(preview.host_id)}</code>
      </p>
      <p>
        仅在本地解析已保存资料，没有运行安全规则、建立任务证据或联系主机。字段存在不代表配置安全；无法确定的时间、缺失字段和未解析记录都保留为覆盖缺口。
      </p>
      <HostCoverage value={preview.coverage} />
      {(preview.input_kind === "baseline" ||
        Boolean(preview.collection_metadata)) && (
        <HostCollection value={preview.collection_metadata} />
      )}
      {preview.limitations?.length > 0 && (
        <ul className="host-note">
          {preview.limitations.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
