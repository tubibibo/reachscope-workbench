import type { RetestResult, ReviewCase } from "../lib/types";

export function HostCaseJourney({
  item,
  retest,
  openRevision,
}: {
  item: ReviewCase;
  retest: RetestResult | null;
  openRevision: () => void;
}) {
  if (item.asset_kind !== "host") return null;
  const isLog = item.source?.category.startsWith("host.logs.") === true;
  function scroll(id: string) {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "auto", block: "start" });
  }
  return (
    <section className="host-case-journey" aria-label="主机加固处理步骤">
      <span className="eyebrow">HOST JOURNEY / SAVED CASE</span>
      <h3>{isLog ? "沿证据调查日志线索" : "按同一主机资料完成加固复核"}</h3>
      <ol>
        <li>
          <button type="button" onClick={() => scroll("host-case-source")}>
            <span>01</span>
            <strong>核对来源证据</strong>
            <small>检查主机、上下文、时间与未知项</small>
          </button>
        </li>
        <li>
          <button
            type="button"
            onClick={() => {
              if (isLog) scroll("host-case-decision");
              else {
                openRevision();
                requestAnimationFrame(() => scroll("host-case-revision"));
              }
            }}
          >
            <span>02</span>
            <strong>{isLog ? "记录调查补充" : "关联修订资料"}</strong>
            <small>
              {isLog
                ? "在处理说明中记录人工调查依据"
                : "先保存新文件，再显式关联"}
            </small>
          </button>
        </li>
        <li>
          <button type="button" onClick={() => scroll("host-case-retest")}>
            <span>03</span>
            <strong>核对可比复测</strong>
            <small>
              {retest?.outcome === "not_observed_in_scope"
                ? item.status === "resolved"
                  ? "当前范围已复核，人工结论已记录"
                  : "当前范围未再观察到，等待人工结论"
                : retest?.outcome === "still_observed"
                  ? "仍观察到原条件"
                  : retest?.outcome === "not_comparable"
                    ? "先处理不能比较的原因"
                    : "选择同规则、完整上下文的新检查"}
            </small>
          </button>
        </li>
        <li>
          <button type="button" onClick={() => scroll("host-case-decision")}>
            <span>04</span>
            <strong>
              {item.status === "resolved" ? "已记录人工关闭" : "记录处理决定"}
            </strong>
            <small>说明、风险接受或人工关闭继续使用现有审计流程</small>
          </button>
        </li>
      </ol>
      {isLog ? (
        <p className="scope-note">
          日志规则只提供调查线索。后续片段未命中、时间未知或资料减少，都不能据此自动认定安全或清除事项。
        </p>
      ) : (
        <p className="host-note">
          检查对应同一主机、规则及 SSH 连接上下文，采集时间不能倒退。从 v1 改用
          v2
          最小投影时请建立对应新基线；修订关联只记录关系，不替代身份或运行状态证明。
        </p>
      )}
      {retest?.outcome === "not_comparable" && (
        <div className="host-retest-help" role="status">
          <strong>下一步先补齐比较条件</strong>
          <p>{retest.reason}</p>
          <p>
            依次核对：新旧主机标识 → 检查规则和连接上下文 → 采集时间 →
            证据完整性与格式/投影版本。如果使用新文件，先完成显式关联；不应通过修改历史输入或填充安全值绕过缺口。
          </p>
        </div>
      )}
    </section>
  );
}
