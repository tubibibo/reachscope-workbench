import type { Asset, Data, Job } from "./types";
import { textValue } from "./types";
import { jobConfig } from "./job-config";

export type SourceKind = "probe" | "file" | "demo" | "legacy" | "training";
export interface InspectionSource {
  kind: SourceKind;
  label: string;
  detail: string;
}
export function sourceOfInput(
  source: Data,
  assetKind?: Asset["kind"],
  provenance?: Asset["provenance"],
): InspectionSource {
  if (provenance?.kind === "local_training")
    return {
      kind: "training",
      label: "本地教学 / 实际采集",
      detail:
        "由服务端登记的内置loopback教学资产，保留实际响应证据；不属于生产站点检测。",
    };
  const mode = textValue(source.mode);
  if (mode === "demo")
    return {
      kind: "demo",
      label: "合成演示",
      detail: "内置样例，仅用于体验流程，不代表实际资产。",
    };
  if (mode === "probe")
    return {
      kind: "probe",
      label: assetKind === "cloud" ? "云服务 HTTP 观察" : "网站 HTTP 观察",
      detail: "只检查已提供的 HTTP(S) 地址，保留本次响应证据。",
    };
  if (mode === "apk")
    return {
      kind: "file",
      label: "APK 文件分析",
      detail: "读取保存的 APK 输入，应用不会被安装或执行。",
    };
  if (["baseline", "access_log", "auth_log"].includes(mode))
    return {
      kind: "file",
      label: mode === "baseline" ? "主机配置导出" : "脱敏日志分析",
      detail:
        "分析操作员提供的本地文件；未连接主机、持续监控或确认入侵。原始上传仍保存在本机。",
    };
  if (mode === "import")
    return {
      kind: "file",
      label: assetKind === "cloud" ? "云配置文件审查" : "文件导入 / 未复测",
      detail:
        assetKind === "cloud"
          ? "离线审查配置文件，不代表已部署资源的有效权限。"
          : "来自保存的文件记录，不等于本次完成网络验证。",
    };
  return {
    kind: "legacy",
    label: "历史输入",
    detail: "旧记录缺少完整的来源绑定，请结合原输入和证据核对。",
  };
}
export function sourceOfJob(job: Job): InspectionSource {
  return sourceOfInput(
    job.asset_snapshot?.source || jobConfig(job),
    job.asset_snapshot?.kind || (job.module === "web" ? "website" : job.module),
    job.asset_snapshot?.provenance,
  );
}
export function matchesSource(
  source: InspectionSource,
  scope: string,
): boolean {
  return (
    scope === "all" ||
    (scope === "demo"
      ? source.kind === "demo"
      : scope === "training"
        ? source.kind === "training"
        : source.kind !== "demo" && source.kind !== "training")
  );
}
