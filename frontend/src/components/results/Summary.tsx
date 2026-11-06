import { ArrowRight, ChevronDown, Layers3 } from "lucide-react";
import type { Job, ModuleResult } from "../../lib/types";
import { readable, records, strings } from "../../lib/types";
import { sourceOfJob } from "../../lib/inspection-source";
import { jobConfig } from "../../lib/job-config";

const checkLabels: Record<string, string> = {
  http: "HTTP 响应",
  headers: "响应头与 Cookie",
  page: "页面配置",
  fingerprints: "技术线索",
  manifest: "应用清单",
  code_paths: "候选代码路径",
  network: "云网络规则",
  iam: "IAM 策略",
  storage: "存储配置",
  ssh: "SSH 配置基线",
  nginx: "Nginx 配置基线",
  web_logs: "Web 访问日志",
  auth_logs: "认证日志",
};
export function ResultBrief({
  job,
  result,
  onEvidence,
  onExecution,
}: {
  job: Job;
  result: ModuleResult;
  onEvidence: (id: string) => void;
  onExecution: () => void;
}) {
  const execution = records(result.details.execution);
  const failed = execution.filter((entry) => entry.status === "failed");
  const skipped = execution.filter((entry) => entry.status === "skipped");
  const first = result.observations.find((entry) => entry.evidence_ids.length);
  const checkCount =
    typeof result.summary.review_checks === "number"
      ? result.summary.review_checks
      : null;
  const errors =
    typeof result.summary.errors === "number" ? result.summary.errors : null;
  return (
    <section className="result-brief" aria-label="检查摘要与下一步">
      <div>
        <span className="eyebrow">01 / SCOPE</span>
        <h3>本次覆盖</h3>
        <p>
          {strings(jobConfig(job).checks)
            .map((id) => checkLabels[id] || id)
            .join(" / ") || "按保存的输入配置执行"}
        </p>
        <small>
          {sourceOfJob(job).label} · {result.evidence.length} 条保存证据
        </small>
      </div>
      <div>
        <span className="eyebrow">02 / REVIEW</span>
        <h3>优先关注</h3>
        <p>
          {checkCount === null
            ? `${result.observations.length} 条观察项`
            : `${checkCount} 项配置待复核 · ${result.observations.length} 条观察项`}
        </p>
        <small>待复核与候选方向需要人工确认，不代表已证实漏洞。</small>
        {first && (
          <button
            className="text-button"
            onClick={() => onEvidence(first.evidence_ids[0]!)}
          >
            查看首项来源证据
            <ArrowRight size={12} />
          </button>
        )}
      </div>
      <div>
        <span className="eyebrow">03 / COLLECTION</span>
        <h3>失败与未覆盖</h3>
        <p>
          {errors === null
            ? `${failed.length} 个执行步骤失败`
            : `${errors} 个请求失败 · ${failed.length} 个执行步骤失败`}
        </p>
        <small>
          {skipped.length} 个步骤未执行
          {typeof result.summary.unknown_checks === "number"
            ? ` · ${result.summary.unknown_checks} 项信息不足`
            : ""}
          。缺少证据不能视为安全。
        </small>
        <button className="text-button" onClick={onExecution}>
          查看执行记录
          <ArrowRight size={12} />
        </button>
      </div>
      <div>
        <span className="eyebrow">04 / NEXT ACTION</span>
        <h3>接下来做什么</h3>
        <p>
          {failed.length || (errors !== null && errors > 0)
            ? "先核对采集失败及输入范围，再补齐可比较的检查。"
            : "复核保存的证据，将需要跟进的条目建立为整改事项。"}
        </p>
        <small>
          修复后用同一资产复测，并补充人工结论；AI建议不自动关闭事项。
        </small>
        <a className="text-button" href="#/engagements">
          进入验证与整改
          <ArrowRight size={12} />
        </a>
      </div>
    </section>
  );
}

const summaryLabels: Record<string, string> = {
  assets: "资产",
  online: "本次响应",
  observations: "观察项",
  paths: "候选路径",
  components: "组件",
  exported: "导出组件",
  deeplinks: "深链",
  chains: "候选链",
  findings: "风险提示",
  warnings: "分析警告",
  methods: "方法",
  evidence: "证据",
  files: "文件",
  targets: "目标",
  errors: "请求失败",
  imported: "导入资产",
  imported_responses: "历史响应",
  import_warnings: "导入提示",
  checks: "配置检查",
  review_checks: "待复核",
  resources: "配置资源",
  unknown_checks: "信息不足",
  unsupported_resources: "未覆盖资源",
};
export function ResultSummary({ result }: { result: ModuleResult }) {
  return (
    <div className="result-stats">
      {Object.entries(result.summary)
        .filter(([, value]) => typeof value === "number")
        .sort(([a], [b]) => {
          if (result.module !== "web") return 0;
          const order = [
            "assets",
            "online",
            "imported_responses",
            "checks",
            "review_checks",
            "paths",
            "observations",
            "errors",
          ];
          return (
            (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) -
            (order.indexOf(b) < 0 ? 99 : order.indexOf(b))
          );
        })
        .slice(0, 8)
        .map(([key, value]) => (
          <div key={key}>
            <span>{summaryLabels[key] || key}</span>
            <strong>{readable(value)}</strong>
          </div>
        ))}
    </div>
  );
}

export function Limitations({ limitations }: { limitations: string[] }) {
  return (
    <details className="limitations">
      <summary>
        <Layers3 size={15} />
        <span>分析范围与限制</span>
        <span className="mono">{limitations.length}</span>
        <ChevronDown size={14} />
      </summary>
      <ul>
        {limitations.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </details>
  );
}
