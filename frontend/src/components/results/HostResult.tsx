import { useState } from "react";
import { ArrowRight, ChevronDown, ShieldCheck } from "lucide-react";
import type { Data, Job, ModuleResult } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { SearchField } from "../Common";
import { JsonData } from "./JsonData";
import { HostCoverage } from "./HostCoverage";
import { HostCaseAction } from "./HostCaseAction";
import { HostCollection } from "./HostCollection";
import { externalReferenceUrl } from "../../lib/security";
import "./host-results.css";

const states: Record<string, string> = {
  pass: "满足本项条件",
  review: "待人工复核",
  unknown: "信息不足",
  info: "样本内未触发",
  not_applicable: "本项不适用",
};
const eventLabels: Record<string, string> = {
  http_access: "HTTP 访问",
  ssh_auth_failure: "SSH 认证失败",
  ssh_auth_success: "SSH 认证成功",
};

function stateOf(row: Data) {
  const value = textValue(row.status);
  return Object.hasOwn(states, value) ? value : "unknown";
}

function ManualGuide({ value }: { value: unknown }) {
  if (!isRecord(value))
    return (
      <p className="host-note">
        此记录未保存人工处理指引，请核对原始证据和适用范围。
      </p>
    );
  const sections = [
    ["prerequisites", "变更前确认"],
    ["red_review", "验证与调查方向"],
    ["blue_steps", "防御补强步骤"],
    ["verification", "复测与业务验收"],
    ["rollback", "回滚与恢复"],
  ] as const;
  return (
    <details className="host-manual-guide">
      <summary>
        查看复核、补强与验证指引 <ChevronDown size={14} />
      </summary>
      <p className="host-note">
        指引来自保存结果中的受控规则。先核对主机、采集时间与业务条件；工作台不会登录主机、执行命令、修改配置或自动关闭事项。
      </p>
      <div className="host-guide-grid">
        {sections.map(([key, label]) => (
          <section key={key}>
            <h5>{label}</h5>
            {strings(value[key]).length ? (
              <ol>
                {strings(value[key]).map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            ) : (
              <p>需补充人工处理计划。</p>
            )}
          </section>
        ))}
      </div>
      {strings(value.limitations).length > 0 && (
        <ul className="host-note">
          {strings(value.limitations).map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
      <div className="host-references">
        {records(value.references).map((ref, index) => {
          const href = externalReferenceUrl(ref.url);
          return href ? (
            <a
              key={index}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {textValue(ref.title) || "规则参考"} ↗
            </a>
          ) : null;
        })}
      </div>
    </details>
  );
}

export function HostResult({
  job,
  result,
  onEvidence,
}: {
  job: Job;
  result: ModuleResult;
  onEvidence: (id: string) => void;
}) {
  const checks = records(result.details.checks),
    events = records(result.details.log_events),
    execution = records(result.details.execution);
  const [status, setStatus] = useState("all"),
    [search, setSearch] = useState(""),
    [limit, setLimit] = useState(30),
    [tab, setTab] = useState("checks");
  const known = new Set(result.evidence.map((row) => row.id));
  const matches = checks.filter(
    (row) =>
      (status === "all" || stateOf(row) === status) &&
      `${textValue(row.title)} ${textValue(row.id)} ${textValue(row.resource_id)}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const origin = textValue(result.details.origin);
  return (
    <div className="host-results">
      <section className="host-brief" aria-label="主机防御检查摘要">
        <div className="result-section-heading">
          <div>
            <span className="eyebrow">HOST DEFENSE / SAVED INPUTS</span>
            <h3>从配置偏差到可核对的证据</h3>
          </div>
          <ShieldCheck size={26} />
        </div>
        <p>
          主机标识 <code>{readable(result.details.host_id)}</code> ·{" "}
          {origin === "synthetic_demo"
            ? "合成教学输入"
            : origin === "operator_supplied_log"
              ? "操作员提供的日志文件"
              : "操作员提供的配置资料"}
        </p>
        <p className="host-note">
          本次仅分析提供的资料，未连接主机或持续监控。配置通过限于本项声明；日志异常是调查线索，未触发也不表示没有攻击。
        </p>
        <div className="host-status-counts">
          {Object.entries(states).map(([key, label]) => (
            <button
              type="button"
              key={key}
              aria-pressed={status === key}
              onClick={() => {
                setTab("checks");
                setSearch("");
                setStatus(status === key ? "all" : key);
                setLimit(30);
              }}
            >
              <strong>
                {checks.filter((row) => stateOf(row) === key).length}
              </strong>
              <span>{label}</span>
            </button>
          ))}
        </div>
        <p className="host-note">
          本次完成：
          {execution
            .filter((row) => row.status === "completed")
            .map((row) => textValue(row.label) || textValue(row.id))
            .join("、") || "未记录"}
          。未执行：
          {execution
            .filter((row) => row.status !== "completed")
            .map((row) => textValue(row.label) || textValue(row.id))
            .join("、") || "无"}
          。
        </p>
      </section>
      <HostCaseAction job={job} />
      {(result.details.collection_metadata ||
        execution.some(
          (row) =>
            ["ssh", "nginx"].includes(textValue(row.id)) &&
            row.status === "completed",
        )) && <HostCollection value={result.details.collection_metadata} />}
      <div className="host-tabs" role="tablist" aria-label="主机防御结果">
        {[
          ["checks", "检查与处理"],
          ["coverage", "采集覆盖"],
          ["logs", "日志事件"],
        ].map(([key, label], index, array) => (
          <button
            type="button"
            id={`host-tab-${key}`}
            key={key}
            role="tab"
            aria-selected={tab === key}
            aria-controls="host-result-panel"
            tabIndex={tab === key ? 0 : -1}
            onClick={() => setTab(key!)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % array.length
                  : event.key === "ArrowLeft"
                    ? (index + array.length - 1) % array.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? array.length - 1
                        : null;
              if (next === null) return;
              event.preventDefault();
              const selected = array[next]![0]!;
              setTab(selected);
              document.getElementById(`host-tab-${selected}`)?.focus();
            }}
          >
            {label}
            {key === "logs" ? ` (${events.length})` : ""}
          </button>
        ))}
      </div>
      <section
        className="result-section"
        role="tabpanel"
        id="host-result-panel"
        aria-labelledby={`host-tab-${tab}`}
      >
        {tab === "checks" && (
          <>
            <div className="result-section-heading">
              <h3>
                实际执行的检查 <span>{checks.length}</span>
              </h3>
              <SearchField
                value={search}
                onChange={(value) => {
                  setSearch(value);
                  setLimit(30);
                }}
                label="搜索主机检查"
                placeholder="搜索检查项或规则编号"
              />
            </div>
            <div className="host-filter">
              <label>
                检查状态
                <select
                  aria-label="主机检查状态"
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value);
                    setLimit(30);
                  }}
                >
                  <option value="all">全部状态</option>
                  {Object.entries(states).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <span>
                显示 {Math.min(limit, matches.length)} / {matches.length} 项
              </span>
            </div>
            <div className="host-checks">
              {matches.slice(0, limit).map((row, index) => (
                <details
                  className="host-check"
                  key={`${textValue(row.id)}-${textValue(row.resource_id)}-${index}`}
                  data-rule-id={textValue(row.id)}
                >
                  <summary>
                    <span className={`check-state check-${stateOf(row)}`}>
                      {states[stateOf(row)]}
                    </span>
                    <span>
                      <strong>{readable(row.title)}</strong>
                      <code>{readable(row.id)}</code>
                    </span>
                    <ChevronDown size={15} />
                  </summary>
                  <p>{readable(row.description)}</p>
                  <p className="host-next-step">
                    {readable(row.recommendation)}
                  </p>
                  {row.complete === false && (
                    <p className="scope-note">
                      本项证据不完整，不能据此认定整体安全或整改完成。
                    </p>
                  )}
                  {stateOf(row) === "unknown" && (
                    <p className="host-note">
                      下一步：核对采集覆盖和此规则需要的字段，补充同一主机与上下文的新资料；信息不足不会作为通过或整改完成。
                    </p>
                  )}
                  {strings(row.evidence_ids)
                    .filter((id) => known.has(id))
                    .map((id) => (
                      <button
                        type="button"
                        key={id}
                        className="text-button"
                        onClick={() => onEvidence(id)}
                      >
                        查看保存证据 <ArrowRight size={12} />
                      </button>
                    ))}
                  <details className="host-facts">
                    <summary>查看配置依据与规则参数</summary>
                    <JsonData
                      data={isRecord(row.evidence) ? row.evidence : {}}
                    />
                  </details>
                  <ManualGuide value={row.guidance} />
                </details>
              ))}
            </div>
            {!matches.length && (
              <p className="host-note">
                当前筛选下没有检查项；请核对所选执行组与采集覆盖，空列表不代表安全。
              </p>
            )}
            {matches.length > limit && (
              <button
                className="text-button"
                onClick={() => setLimit((value) => value + 30)}
              >
                继续显示检查
              </button>
            )}
          </>
        )}
        {tab === "coverage" && (
          <>
            <h3>输入覆盖与分析边界</h3>
            <p className="host-note">
              这里记录本次实际解析范围。未知、未解析、未提供和截断信息保留为覆盖缺口。
            </p>
            <HostCoverage value={result.details.coverage} />
            {records(result.details.rule_parameters).length > 0 && (
              <>
                <h4>本次规则参数</h4>
                <p className="host-note">
                  日志规则使用固定 UTC
                  五分钟窗口。窗口边界、阈值与输入完整性都会影响结果，未触发不能证明无异常。
                </p>
                {records(result.details.rule_parameters).map((part, index) => (
                  <JsonData key={index} data={part} />
                ))}
              </>
            )}
          </>
        )}
        {tab === "logs" && (
          <>
            <h3>脱敏日志事件</h3>
            <p className="host-note">
              仅展示可解释的解析字段、来源行号和客户端代号；不显示原始请求、查询参数、用户名或日志正文。没有时区/年份的时间保留未知。
            </p>
            {events.length ? (
              <div className="table-scroll">
                <table className="host-events">
                  <thead>
                    <tr>
                      <th>来源行</th>
                      <th>UTC 时间</th>
                      <th>客户端代号</th>
                      <th>事件类型</th>
                      <th>状态</th>
                      <th>时间窗口规则可用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.slice(0, limit).map((event, index) => (
                      <tr key={textValue(event.id) || index}>
                        <td data-label="来源行">
                          {readable(event.line_number)}
                        </td>
                        <td data-label="UTC 时间">
                          {event.timestamp_status === "known"
                            ? readable(event.timestamp)
                            : "时间未知"}
                        </td>
                        <td data-label="客户端代号">
                          {readable(event.actor_alias)}
                        </td>
                        <td data-label="事件类型">
                          {eventLabels[textValue(event.event_class)] ||
                            "未支持事件"}
                        </td>
                        <td data-label="状态">{readable(event.status_code)}</td>
                        <td data-label="时间窗口规则可用">
                          {event.rule_eligible === true
                            ? "可用于窗口分析"
                            : "信息不足"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {events.length > limit && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setLimit((value) => value + 100)}
                  >
                    继续显示脱敏事件
                  </button>
                )}
              </div>
            ) : (
              <p className="host-note">
                本次没有保存日志事件，配置基线任务不会运行日志规则。
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
