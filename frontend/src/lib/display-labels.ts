// Display-only label maps for internal enum codes surfaced in the UI.
// Mirrors the authoritative value sets in the backend:
//   severity / confidence / category / kind — src/reachscope_workbench/core/case_sources.py
//   web categories & kinds — src/reachscope_workbench/modules/web/{module,importer}.py
//   android categories & kinds — src/reachscope_workbench/modules/android/module.py
//   host kinds — src/reachscope_workbench/modules/host/{baseline,logs,module}.py
// Unknown codes fall back to the raw value so evidence stays searchable.
// Host/cloud observation categories are dynamic rule/check identifiers by
// design; the fallback path is expected for them, not an error.

export const severityLabel: Record<string, string> = {
  info: "信息",
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export const confidenceLabel: Record<string, string> = {
  observed: "直接观察",
  observed_config: "配置观察",
  imported_unverified: "导入未复核",
  heuristic: "启发式",
  static_candidate: "静态候选",
  static_inference: "静态推断",
  static_config: "静态配置",
  log_indicator: "日志指标",
  unknown: "未知",
};

export const observationCategoryLabel: Record<string, string> = {
  cleartext_http: "明文 HTTP",
  security_headers: "安全响应头",
  fingerprint: "技术指纹",
  body_limit: "正文上限",
  redirect_scope: "重定向范围",
  cookie_capture: "Cookie 采集",
  header_capture: "响应头上限",
  probe_error: "探测失败",
  imported_finding: "导入发现",
  android_attack_surface: "Android 攻击面",
  android_static_risk: "Android 静态风险",
  android_configuration: "Android 配置",
  analysis_gap: "分析盲区",
  unknown: "未知",
};

export const evidenceKindLabel: Record<string, string> = {
  http_observation: "HTTP 观察",
  synthetic_asset: "合成资产",
  synthetic_demo: "教学合成",
  imported_asset: "导入资产",
  manifest_configuration: "Android 清单",
  android_configuration_review: "Android 配置复核",
  static_candidate_path: "静态候选路径",
  cloud_static_configuration: "云静态配置",
  host_static_configuration: "主机静态配置",
  host_log_summary: "主机日志摘要",
  host_log_indicator: "主机日志指标",
};

export const severityLabelText = (value: string): string =>
  severityLabel[value] ?? value;

export const confidenceLabelText = (value: string): string =>
  confidenceLabel[value] ?? value;

export const observationCategoryText = (value: string): string =>
  observationCategoryLabel[value] ?? value;

export const evidenceKindText = (value: string): string =>
  evidenceKindLabel[value] ?? value;

// AI advisory run statuses — core/advisory_service.py records.finish()
export const advisoryStatusLabel: Record<string, string> = {
  ok: "成功",
  failed: "失败",
  running: "进行中",
  cancelled: "已取消",
  unknown: "未知",
};

export const advisoryStatusText = (value: string): string =>
  advisoryStatusLabel[value] ?? value;
