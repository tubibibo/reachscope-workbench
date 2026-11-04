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
import { externalReferenceUrl } from "../../lib/security";

const reviewStates: Record<string, string> = {
  pass: "满足本项条件",
  review: "待人工复核",
  unknown: "信息不足",
  not_applicable: "本项不适用",
};

export function androidReview(result: ModuleResult): Data | null {
  return isRecord(result.details.security_review)
    ? result.details.security_review
    : null;
}

function stateOf(check: Data): string {
  const state = textValue(check.status);
  return Object.hasOwn(reviewStates, state) ? state : "unknown";
}

export function AndroidBrief({
  job,
  result,
}: {
  job: Job;
  result: ModuleResult;
}) {
  const review = androidReview(result);
  const checks = records(review?.checks);
  const execution = records(result.details.execution);
  const completed = execution.filter((item) => item.status === "completed");
  const skipped = execution.filter((item) => item.status === "skipped");
  const mode = textValue(job.asset_snapshot?.source.mode || job.config.mode);
  const counts = Object.keys(reviewStates).map((state) => ({
    state,
    count: checks.filter((check) => stateOf(check) === state).length,
  }));
  return (
    <section className="android-brief" aria-label="安卓检查摘要">
      <div className="android-brief-title">
        <div>
          <span className="eyebrow">ANDROID / STATIC EVIDENCE</span>
          <h3>先看配置，再看路径</h3>
        </div>
        <span className="subtle-tag">
          {mode === "demo"
            ? "合成教学样例"
            : mode === "apk"
              ? "上传 APK 静态分析"
              : "历史静态结果"}
        </span>
      </div>
      <dl className="android-package-facts">
        <div>
          <dt>应用包名</dt>
          <dd className="mono">
            {readable(result.details.package || result.summary.package)}
          </dd>
        </div>
        <div>
          <dt>targetSdk</dt>
          <dd>{readable(result.details.target_sdk)}</dd>
        </div>
        <div>
          <dt>minSdk</dt>
          <dd>{readable(result.details.min_sdk)}</dd>
        </div>
      </dl>
      {checks.length > 0 ? (
        <div className="android-review-counts">
          {counts.map(({ state, count }) => (
            <div key={state} data-state={state}>
              <strong>{count}</strong>
              <span>{reviewStates[state]}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="android-note">
          此历史记录没有保存新版配置复核结果。再次检查同一资产可以生成新证据，历史记录不会被回填。
        </p>
      )}
      <div className="android-execution-brief">
        {execution.length ? (
          <>
            <span>
              本次完成：
              {completed
                .map((item) => textValue(item.label) || textValue(item.id))
                .join("、") || "未记录"}
            </span>
            {skipped.length > 0 && (
              <span>
                未执行：
                {skipped
                  .map((item) => textValue(item.label) || textValue(item.id))
                  .join("、")}
              </span>
            )}
          </>
        ) : (
          <span>历史结果未保存逐项执行状态，请结合输入与执行记录复核。</span>
        )}
      </div>
      <p className="android-note">
        配置条件满足、未发现路径和未知状态各自独立；这些结果不证明应用安全或漏洞可利用。应用未被安装或执行。
      </p>
    </section>
  );
}

function Guidance({ value }: { value: unknown }) {
  if (!isRecord(value))
    return <p className="android-note">此条记录没有保存实施指引。</p>;
  const groups = [
    ["red_review", "红队：人工复核"],
    ["blue_steps", "蓝队：配置补强"],
    ["verification", "修改后如何验证"],
    ["rollback", "变更与回滚检查"],
  ] as const;
  return (
    <details className="android-guidance">
      <summary>
        查看复核、补强与复测指引 <ChevronDown size={14} />
      </summary>
      <p className="android-note">
        以下为保存结果中的规则指引，不需要
        AI；修改前核对业务条件，修改后重新构建、上传并复测。指引不会执行修改或自动关闭问题。
      </p>
      <div className="android-guidance-grid">
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
              <p className="android-note">未记录，需补充人工验证方案。</p>
            )}
          </div>
        ))}
      </div>
      {strings(value.limitations).length > 0 && (
        <ul className="android-guide-limits">
          {strings(value.limitations).map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
    </details>
  );
}

export function AndroidReview({
  result,
  onEvidence,
}: {
  result: ModuleResult;
  onEvidence: (id: string) => void;
}) {
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const review = androidReview(result);
  const checks = records(review?.checks);
  const matches = checks.filter(
    (item) =>
      (status === "all" || stateOf(item) === status) &&
      [item.id, item.title, item.description].some((value) =>
        textValue(value).toLowerCase().includes(query.toLowerCase()),
      ),
  );
  const coverage = isRecord(review?.coverage) ? review.coverage : null;
  const knownEvidence = new Set(result.evidence.map((item) => item.id));
  return (
    <section
      className="result-section android-security-review"
      id="android-configuration"
      tabIndex={-1}
      aria-label="安卓配置复核"
    >
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">CONFIGURATION / REVIEW</span>
          <h3>
            配置复核 <span>{checks.length}</span>
          </h3>
        </div>
        <ShieldCheck size={22} />
      </div>
      <p className="android-note">
        围绕发布配置、备份、网络信任、组件入口和深链，逐项保留判断条件与原始依据。先处理待复核项，再补足未知项。
      </p>
      {!checks.length ? (
        <p className="inline-empty">
          此记录没有新版配置复核数据。可继续查看已有组件、路径及证据；运行一次新检查后再使用本区域。
        </p>
      ) : (
        <>
          <div className="android-toolbar">
            <SearchField
              value={query}
              onChange={setQuery}
              label="搜索安卓配置检查"
              placeholder="检查名称或规则编号"
            />
            <label className="android-select-label">
              状态
              <select
                aria-label="筛选安卓配置状态"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="all">全部状态</option>
                {Object.entries(reviewStates).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <span className="android-result-count" role="status">
              显示 {matches.length} / {checks.length} 项
            </span>
          </div>
          {!matches.length && (
            <p className="inline-empty">没有符合搜索和状态条件的配置项。</p>
          )}
          <div className="android-check-list">
            {matches.map((item, index) => {
              const state = stateOf(item);
              const evidenceIds = strings(item.evidence_ids).filter((id) =>
                knownEvidence.has(id),
              );
              return (
                <details
                  className="android-check"
                  key={textValue(item.id) || index}
                  data-control-id={textValue(item.id)}
                  data-state={state}
                >
                  <summary>
                    <span className={`android-state android-state-${state}`}>
                      {reviewStates[state]}
                    </span>
                    <strong>{readable(item.title)}</strong>
                    <code>{readable(item.id)}</code>
                    <ChevronDown size={15} />
                  </summary>
                  <div className="android-check-body">
                    <p>{readable(item.description)}</p>
                    {textValue(item.recommendation) && (
                      <p className="android-next-action">
                        <strong>下一步</strong>
                        {textValue(item.recommendation)}
                      </p>
                    )}
                    <div className="android-facts">
                      <span>配置位置</span>
                      <code>
                        {textValue(item.source) || "AndroidManifest.xml"}
                        {textValue(item.pointer)}
                      </code>
                      {records(item.facts).map((fact, factIndex) => (
                        <div key={factIndex}>
                          <code>
                            {readable(fact.source)}
                            {textValue(fact.pointer)}
                          </code>
                          <pre>{readable(fact.value)}</pre>
                        </div>
                      ))}
                    </div>
                    <div className="android-evidence-links">
                      {evidenceIds.map((id) => (
                        <button
                          className="text-button"
                          type="button"
                          key={id}
                          onClick={() => onEvidence(id)}
                        >
                          查看保存证据 <ArrowRight size={12} />
                        </button>
                      ))}
                      {!evidenceIds.length && (
                        <span className="android-note">
                          此记录缺少可跳转证据，需检查证据索引。
                        </span>
                      )}
                    </div>
                    <Guidance value={item.guidance} />
                    {records(item.references).length > 0 && (
                      <div className="android-references">
                        {records(item.references).map(
                          (reference, referenceIndex) => {
                            const url = externalReferenceUrl(reference.url);
                            return url ? (
                              <a
                                href={url}
                                key={referenceIndex}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {textValue(reference.title) || "规则参考"} ↗
                              </a>
                            ) : null;
                          },
                        )}
                      </div>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        </>
      )}
      {coverage?.truncated === true && (
        <p className="android-coverage-warning">
          达到静态解析返回上限，部分组件、深链或资源未包含在本结果内；未返回的内容不能算作通过。
        </p>
      )}
      {strings(review?.limitations).length > 0 && (
        <details className="android-limitations">
          <summary>配置复核边界与未覆盖项</summary>
          <ul>
            {strings(review?.limitations).map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
