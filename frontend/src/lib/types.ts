export type ModuleId = "android" | "web" | "cloud" | "host";
export type AssetKind = "android" | "website" | "cloud" | "host";
export interface Asset {
  id: string;
  kind: AssetKind;
  name: string;
  source: Data;
  provenance?: {
    kind: "local_training";
    label: string;
    session_id: string;
  } | null;
  created_at: string;
  updated_at: string;
  job_count?: number;
  last_checked_at?: string | null;
}
export interface CheckOption {
  id: string;
  label: string;
  description: string;
  required: boolean;
  depends_on: string[];
  recommended?: boolean;
}
export interface AnalysisProfile {
  id: string;
  module: ModuleId;
  asset_kind: AssetKind;
  mode: string;
  label: string;
  description: string;
  network: boolean;
  input: "apk" | "urls" | "json" | "demo";
  checks: CheckOption[];
}
export interface Catalog {
  asset_kinds: { id: AssetKind; label: string; description: string }[];
  profiles: AnalysisProfile[];
}
type WireInspection = components["schemas"]["InspectionCreate"];
// name has a server default; the generator marks defaulted fields as required.
export type InspectionRequest = Omit<WireInspection, "name"> &
  Partial<Pick<WireInspection, "name">>;
export interface Preflight {
  ready: boolean;
  asset_id: string;
  module: ModuleId;
  checks: string[];
  network: boolean;
  items: {
    id: string;
    label: string;
    status: "ready" | "blocked" | "warning";
    message: string;
  }[];
  scope: {
    profile_id: string;
    label: string;
    selected_checks: { id: string; label: string }[];
    limits: Data;
  };
  limitations: string[];
  input_preview?: CloudInputPreview | HostInputPreview;
}
export interface HostInputPreview {
  version: number;
  module: "host";
  input_kind: string;
  host_id: string;
  sha256: string;
  coverage: Data;
  analysis_executed: false;
  network_requests: false;
  limitations: string[];
  collection_metadata?: Data;
}
export interface CloudInputPreview {
  version: number;
  input_kind: string;
  sha256: string;
  resources_total: number;
  supported_resources: number;
  unsupported_resources: number;
  resource_types: { type: string; count: number; supported: boolean }[];
  selected_groups: string[];
  group_coverage: {
    id: string;
    label: string;
    applicable_resources: number;
    known_fields: number;
    missing_fields: number;
    unknown_fields: number;
    redacted_fields: number;
    invalid_fields: number;
  }[];
  field_gaps: {
    resource_id: string;
    resource_type: string;
    group: string;
    field: string;
    pointer: string;
    state: "missing" | "unknown" | "redacted" | "invalid";
  }[];
  field_gaps_total: number;
  truncated: boolean;
  limitations: string[];
  analysis_executed: false;
  network_requests: false;
}
export type Status =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type Data = Record<string, unknown>;
export interface ModuleSpec {
  id: ModuleId;
  name: string;
  description: string;
  capabilities: string[];
  input_modes: string[];
  version: string;
}
export interface Evidence {
  id: string;
  kind: string;
  title: string;
  source: string;
  data: Data;
  sha256: string;
}
export interface Observation {
  id: string;
  title: string;
  severity: string;
  category: string;
  description: string;
  evidence_ids: string[];
  confidence: string;
  recommendation: string;
}
export interface ModuleResult {
  module: string;
  target: string;
  summary: Data;
  evidence: Evidence[];
  observations: Observation[];
  details: Data;
  limitations: string[];
  schema_version: string;
}
export interface Job {
  id: string;
  module: ModuleId;
  name: string;
  status: Status;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  config?: Data | null;
  error: { code: string; message: string } | null;
  result?: ModuleResult | null;
  asset_id?: string | null;
  asset_snapshot?: Pick<
    Asset,
    "id" | "kind" | "name" | "source" | "provenance"
  > | null;
}
export interface JobEvent {
  id: number;
  created_at: string;
  level: string;
  message: string;
  progress: number;
}
export interface Page<T> {
  items: T[];
  total: number;
}
export type CaseStatus =
  | "open"
  | "in_progress"
  | "ready_for_retest"
  | "resolved"
  | "accepted_risk"
  | "false_positive";
export interface Engagement {
  id: string;
  name: string;
  objective: string;
  authorization_note: string;
  created_at: string;
  updated_at: string;
  assets?: Pick<Asset, "id" | "name" | "kind">[];
  asset_ids: string[];
  asset_count: number;
  case_count: number;
  case_counts?: Record<CaseStatus, number>;
}
export interface Candidate {
  source_ref: string;
  source_kind: "observation" | "check";
  title: string;
  severity: string;
  confidence: string;
  asset_id: string;
  job_id: string;
  evidence_ids: string[];
  description: string;
  recommendation: string;
  category: string;
  status?: string;
  locator?: Data;
}
export interface CaseEvent {
  id: number;
  created_at: string;
  event_type: string;
  data: Data;
}
export interface ReviewCase {
  id: string;
  engagement_id: string;
  asset_id: string;
  job_id: string;
  source_ref: string;
  source_kind: "observation" | "check";
  title: string;
  severity: string;
  confidence: string;
  status: CaseStatus;
  owner: string;
  due_date: string;
  note: string;
  version: number;
  created_at: string;
  updated_at: string;
  asset_name: string;
  asset_kind: AssetKind;
  job_name: string;
  source?: Omit<Candidate, "asset_id" | "job_id">;
  evidence?: Evidence[];
  events?: CaseEvent[] | { items: CaseEvent[] };
  event_pagination?: {
    next_cursor: number;
    limit?: number;
    has_more?: boolean;
  };
}
export interface RetestResult {
  outcome: "still_observed" | "not_observed_in_scope" | "not_comparable";
  reason: string;
  source_job_id: string;
  retest_job_id: string;
  matching: Data[];
  evidence: Evidence[];
  limitations: string[];
  input_revision?: boolean;
}
export type CasePatch = components["schemas"]["CasePatch"];
export interface Upload {
  id: string;
  filename: string;
  size: number;
  sha256: string;
}
export interface WebComparison {
  baseline_job_id: string;
  current_job_id: string;
  summary: {
    added: number;
    removed: number;
    changed: number;
    unchanged: number;
    not_comparable: number;
  };
  assets: {
    url: string;
    status: "added" | "removed" | "changed" | "unchanged" | "not_comparable";
    changes: { field: string; before: unknown; after: unknown }[];
    before_evidence_ids: string[];
    after_evidence_ids: string[];
    notes?: string[];
  }[];
  limitations: string[];
}
export interface MethodPage {
  data: Data[];
  pagination: {
    offset: number;
    limit: number;
    total: number;
    truncated: boolean;
    next_offset: number | null;
  };
}
export interface MethodCode {
  data: {
    code: string;
    file: string;
    start_line: number;
    end_line?: number;
    sha256?: string;
    truncated?: boolean;
    total_lines?: number;
    next_offset?: number | null;
  };
  pagination?: MethodPage["pagination"];
}
export const isRecord = (value: unknown): value is Data =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export const records = (value: unknown): Data[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
export const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
export const readable = (value: unknown): string =>
  value === undefined || value === null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : String(value);
export const textValue = (value: unknown): string =>
  typeof value === "string" ? value : "";
export const statusLabel: Record<Status, string> = {
  queued: "等待执行",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};
export const statusLabelText = (value: string): string =>
  statusLabel[value as Status] || value;
export const moduleLabel: Record<ModuleId, string> = {
  android: "Android",
  web: "Web",
  cloud: "云配置",
  host: "主机防御",
};
export const assetKindLabel: Record<AssetKind, string> = {
  android: "安卓应用",
  website: "网站",
  cloud: "云资产",
  host: "主机与日志",
};
export const isActive = (job: Job): boolean =>
  job.status === "queued" || job.status === "running";
export const dateLabel = (date: string): string => {
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime())
    ? date
    : parsed.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
};
import type { components } from "../generated/api";
