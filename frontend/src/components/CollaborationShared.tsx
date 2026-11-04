import { ApiError, errorRequestId, errorText } from "../lib/api";
import type { CaseStatus, RetestResult } from "../lib/types";
import { ErrorBox } from "./Common";

export const caseLabels: Record<CaseStatus, string> = {
  open: "待研判",
  in_progress: "处理中",
  ready_for_retest: "待复测",
  resolved: "已复核关闭",
  accepted_risk: "接受风险",
  false_positive: "不适用 / 误报",
};
export const retestLabels: Record<RetestResult["outcome"], string> = {
  still_observed: "仍观察到该条件",
  not_observed_in_scope: "本次范围内未再观察到",
  not_comparable: "不能作为可比复测",
};
export type RoleView = "red" | "blue";
export function Failure({
  value,
  retry,
}: {
  value: unknown;
  retry?: () => void;
}) {
  return value ? (
    <ErrorBox retry={retry} requestId={errorRequestId(value)}>
      {errorText(value)}
      {value instanceof ApiError && value.code === "CASE_CONFLICT"
        ? " 请刷新记录，核对最新版本后再保存。"
        : ""}
    </ErrorBox>
  ) : null;
}
