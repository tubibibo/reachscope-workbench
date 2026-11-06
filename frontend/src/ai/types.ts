import type { Data } from "../lib/types";
import type { components } from "../generated/api";

export type AIProviderId =
  | "openai_compatible"
  | "openai-compatible"
  | "deepseek"
  | "custom";
export function normalizeProviderId(value: AIProviderId): AIProviderId {
  return value === "openai-compatible" ? "openai_compatible" : value;
}
export type ReasoningEffort =
  | "default"
  | "none"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max";
export type TokenLimitField = "max_tokens" | "max_completion_tokens";
export interface AIProviderPreset {
  id: AIProviderId;
  label: string;
  base_url: string;
  models: string[];
  notes: string;
  reasoning_efforts: ReasoningEffort[];
  token_limit_field: TokenLimitField;
}

export interface AIConfig {
  configuration_sha256: string;
  enabled: boolean;
  provider_id: AIProviderId;
  provider_label: string;
  base_url: string;
  model: string;
  reasoning_effort: ReasoningEffort;
  token_limit_field: TokenLimitField;
  credential_source: "session" | "environment" | "missing";
  has_key: boolean;
  allow_local: boolean;
  timeout: number;
  capabilities: { web: boolean; android: boolean; cloud: boolean };
  limitations: string[];
}
type WireAIConfiguration = components["schemas"]["AIConfiguration"];
// Remaining properties have server defaults or are optional credentials.
export type AIConfigUpdate = Pick<WireAIConfiguration, "enabled" | "base_url"> &
  Partial<Omit<WireAIConfiguration, "enabled" | "base_url">>;
export interface AIDiagnosis {
  provider_id: AIProviderId;
  provider_label: string;
  base_url: string;
  status: string;
  message: string;
  network: string;
  protocol: string;
  authentication: string;
  model_call: false;
  business_data_sent: false;
  http_status?: number;
  limitations: string[];
}
export type AIDiagnosisRequest = components["schemas"]["AIDiagnostic"];
export interface ModelDiagnosis {
  kind: "saved_models";
  provider_id: AIProviderId;
  provider_label: string;
  base_url: string;
  model: string;
  status: string;
  message: string;
  authentication: "accepted" | "rejected" | "unknown";
  model_available: boolean | null;
  inference_verified: false;
  model_call: false;
  business_data_sent: false;
  http_status?: number;
  limitations: string[];
}
export interface ControlGuide {
  guide_version: string;
  report_id?: string;
  origin?: "probe" | "local_training";
  source_kind?: "deterministic_saved_evidence";
  job_id: string;
  control_id: string;
  title: string;
  applicability: string;
  environment: "generic" | "nginx";
  observed_stack: null;
  requires_environment_confirmation: boolean;
  evidence_ids: string[];
  signal_statuses: {
    check_id: string;
    status: string;
    evidence_ids: string[];
  }[];
  preconditions: string[];
  red_review: string[];
  blue_steps: string[];
  verification: string[];
  rollback: string[];
  acceptance: string[];
  templates: {
    title: string;
    content: string;
    language: "nginx";
    context: string;
    conditions: string[];
    limitations: string[];
    references: { title: string; url: string; kind: string }[];
  }[];
  references: { title: string; url: string; kind: string }[];
  limitations: string[];
}
export interface JobControls {
  job_id: string;
  origin: "probe" | "local_training" | "cloud_service_probe";
  source_kind: "deterministic_saved_evidence";
  ai_required: false;
  items: {
    control_id: string;
    title: string;
    category: string;
    states: string[];
    evidence_ids: string[];
    signal_statuses: ControlGuide["signal_statuses"];
  }[];
  limitations: string[];
}
export interface AdvisoryControl {
  id: string;
  title: string;
  category: string;
  applicability: string;
  red_review: string[];
  blue_actions: string[];
  verification: string[];
  limitations: string[];
  references: { title: string; url: string; kind: string }[];
  signals: string[];
}
export interface AdvisoryItem {
  control_id: string;
  priority: "high" | "medium" | "low";
  evidence_ids: string[];
  title: string;
  applicability: "web_config" | "manual_review" | "endpoint_hygiene";
  basis: "observed_configuration" | "manual_review";
  category: string;
  actions: string[];
  verification: string[];
  limitations: string[];
  references: { title: string; url: string; kind: string }[];
}
export interface AdvisoryMetadata {
  id: string;
  job_id: string;
  module: string;
  status: "running" | "completed" | "failed" | "interrupted";
  mode: "ai_api";
  provider: { base_url: string; model: string };
  context_sha256: string;
  created_at: string;
  error: { code: string; message: string } | null;
}
export interface AdvisoryReport extends AdvisoryMetadata {
  red: AdvisoryItem[];
  blue: AdvisoryItem[];
  limitations: string[];
  usage: Data;
  disclosure: { fields: string[]; excluded: string[]; bytes: number };
}
export interface AdvisoryPreview {
  job_id: string;
  module: string;
  eligible: boolean;
  reason: string;
  context: Data;
  context_sha256: string;
  provider: Pick<AIConfig, "base_url" | "model" | "has_key" | "enabled">;
  controls: AdvisoryControl[];
  disclosure: { fields: string[]; excluded: string[]; bytes: number };
  reports: AdvisoryMetadata[];
}
