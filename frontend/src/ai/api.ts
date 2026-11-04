import { request } from "../lib/api";
import type { Page } from "../lib/types";
import type { components } from "../generated/api";
import type {
  AIConfig,
  AIConfigUpdate,
  AdvisoryMetadata,
  AdvisoryPreview,
  AdvisoryReport,
  AIDiagnosis,
  AIDiagnosisRequest,
  AIProviderPreset,
  ModelDiagnosis,
  ControlGuide,
  JobControls,
} from "./types";

export const aiApi = {
  config: (signal?: AbortSignal) => request<AIConfig>("/ai/config", { signal }),
  providers: (signal?: AbortSignal) =>
    request<{ items: AIProviderPreset[] }>("/ai/providers", { signal }),
  configure: (payload: AIConfigUpdate) =>
    request<AIConfig>("/ai/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  diagnose: (payload: AIDiagnosisRequest) =>
    request<AIDiagnosis>("/ai/diagnose", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  diagnoseModels: (configuration_sha256: string) =>
    request<ModelDiagnosis>("/ai/diagnose/models", {
      method: "POST",
      body: JSON.stringify({
        configuration_sha256,
        consent: true,
      } satisfies components["schemas"]["AIModelDiagnostic"]),
    }),
  guide: (
    reportId: string,
    controlId: string,
    environment: "generic" | "nginx",
    signal?: AbortSignal,
  ) =>
    request<ControlGuide>(
      `/advisories/${encodeURIComponent(reportId)}/controls/${encodeURIComponent(controlId)}/guide?environment=${environment}`,
      { signal },
    ),
  jobControls: (jobId: string, signal?: AbortSignal) =>
    request<JobControls>(`/jobs/${encodeURIComponent(jobId)}/controls`, {
      signal,
    }),
  jobGuide: (
    jobId: string,
    controlId: string,
    environment: "generic" | "nginx",
    signal?: AbortSignal,
  ) =>
    request<ControlGuide>(
      `/jobs/${encodeURIComponent(jobId)}/controls/${encodeURIComponent(controlId)}/guide?environment=${environment}`,
      { signal },
    ),
  preview: (jobId: string, signal?: AbortSignal) =>
    request<AdvisoryPreview>(
      `/jobs/${encodeURIComponent(jobId)}/advisory/preview`,
      { signal },
    ),
  submit: (
    jobId: string,
    payload: {
      context_sha256: string;
      consent: true;
      authorization_note: string;
    },
    key: string,
  ) =>
    request<AdvisoryReport>(
      `/jobs/${encodeURIComponent(jobId)}/advisory`,
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(payload),
      },
      90_000,
    ),
  report: (id: string, signal?: AbortSignal) =>
    request<AdvisoryReport>(`/advisories/${encodeURIComponent(id)}`, {
      signal,
    }),
  reports: (jobId: string, offset = 0, signal?: AbortSignal) =>
    request<Page<AdvisoryMetadata>>(
      `/jobs/${encodeURIComponent(jobId)}/advisories?limit=25&offset=${offset}`,
      { signal },
    ),
  exportUrl: (id: string, format: "json" | "html") =>
    `/api/advisories/${encodeURIComponent(id)}/export?format=${format}`,
};
