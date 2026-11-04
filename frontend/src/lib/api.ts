import type {
  Asset,
  AssetKind,
  Catalog,
  Data,
  Evidence,
  Job,
  JobEvent,
  InspectionRequest,
  MethodCode,
  MethodPage,
  ModuleId,
  ModuleSpec,
  Page,
  Preflight,
  Upload,
  WebComparison,
  Engagement,
  Candidate,
  ReviewCase,
  CasePatch,
  CaseEvent,
  RetestResult,
} from "./types";
import { isRecord } from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  requestId?: string;
  constructor(
    message: string,
    code = "REQUEST_FAILED",
    status = 0,
    requestId?: string,
  ) {
    super(message);
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

export async function request<T>(
  url: string,
  init: RequestInit = {},
  timeoutMs?: number,
): Promise<T> {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const abort = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abort();
  else callerSignal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(
    () => {
      timedOut = true;
      controller.abort();
    },
    timeoutMs ?? (init.body instanceof FormData ? 120_000 : 30_000),
  );
  try {
    return await readResponse<T>(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut && !callerSignal?.aborted)
      throw new ApiError(
        "等待服务响应超时。可以重试当前操作，已提交的任务会使用同一操作标识确认。",
        "REQUEST_TIMEOUT",
      );
    throw error;
  } finally {
    window.clearTimeout(timer);
    callerSignal?.removeEventListener("abort", abort);
  }
}

async function readResponse<T>(url: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET")
    headers.set("X-ReachScope-Client", "workbench");
  let response: Response;
  try {
    response = await fetch(`/api${url}`, {
      ...init,
      headers,
      credentials: "same-origin",
    });
  } catch (error) {
    if (
      init.signal?.aborted ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw error;
    throw new ApiError(
      "无法确认服务响应，请检查本地服务后重试。",
      "NETWORK_ERROR",
    );
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (
      init.signal?.aborted ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw error;
    throw new ApiError(
      "服务返回了无法读取的响应，请重试。",
      "INVALID_RESPONSE",
      response.status,
      response.headers.get("X-Request-ID") || undefined,
    );
  }
  if (!response.ok) {
    const failure =
      isRecord(body) && isRecord(body.error)
        ? body.error
        : isRecord(body) && isRecord(body.detail)
          ? body.detail
          : null;
    const message =
      failure && typeof failure.message === "string"
        ? failure.message
        : isRecord(body) && typeof body.detail === "string"
          ? body.detail
          : `请求失败（${response.status}）`;
    throw new ApiError(
      message,
      failure && typeof failure.code === "string"
        ? failure.code
        : "REQUEST_FAILED",
      response.status,
      failure && typeof failure.request_id === "string"
        ? failure.request_id
        : response.headers.get("X-Request-ID") || undefined,
    );
  }
  if (!isRecord(body))
    throw new ApiError(
      "服务返回了不符合接口约定的响应，请重试。",
      "INVALID_RESPONSE",
      response.status,
      response.headers.get("X-Request-ID") || undefined,
    );
  return body as T;
}

export const api = {
  engagements: (offset = 0, signal?: AbortSignal) =>
    request<Page<Engagement>>(`/engagements?limit=50&offset=${offset}`, {
      signal,
    }),
  engagement: (id: string, signal?: AbortSignal) =>
    request<Engagement>(`/engagements/${encodeURIComponent(id)}`, { signal }),
  createEngagement: (
    payload: {
      name: string;
      objective: string;
      authorization_note: string;
      asset_ids: string[];
    },
    requestKey: string,
  ) =>
    request<Engagement>("/engagements", {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify(payload),
    }),
  candidates: (id: string, jobId: string, signal?: AbortSignal) =>
    request<{
      items: Candidate[];
      job: Pick<Job, "id" | "name" | "module" | "asset_id">;
      limitations: string[];
    }>(
      `/engagements/${encodeURIComponent(id)}/candidates?job_id=${encodeURIComponent(jobId)}`,
      { signal },
    ),
  cases: (id: string, offset = 0, signal?: AbortSignal) =>
    request<Page<ReviewCase>>(
      `/engagements/${encodeURIComponent(id)}/cases?limit=100&offset=${offset}`,
      { signal },
    ),
  createCase: (
    id: string,
    candidate: Pick<Candidate, "job_id" | "source_ref" | "source_kind">,
    requestKey: string,
    signal?: AbortSignal,
  ) =>
    request<ReviewCase>(`/engagements/${encodeURIComponent(id)}/cases`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify({
        job_id: candidate.job_id,
        source_ref: candidate.source_ref,
        source_kind: candidate.source_kind,
      }),
      signal,
    }),
  reviewCase: (id: string, signal?: AbortSignal) =>
    request<ReviewCase>(`/cases/${encodeURIComponent(id)}`, { signal }),
  caseEvents: (id: string, after = 0, signal?: AbortSignal) =>
    request<{ items: CaseEvent[]; next_cursor: number }>(
      `/cases/${encodeURIComponent(id)}/events?after=${after}&limit=100`,
      { signal },
    ),
  updateCase: (id: string, payload: CasePatch) =>
    request<ReviewCase>(`/cases/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  previewRetest: (id: string, jobId: string, signal?: AbortSignal) =>
    request<RetestResult>(
      `/cases/${encodeURIComponent(id)}/retest?job_id=${encodeURIComponent(jobId)}`,
      { signal },
    ),
  recordRetest: (
    id: string,
    payload: { expected_version: number; job_id: string; note?: string },
  ) =>
    request<ReviewCase>(`/cases/${encodeURIComponent(id)}/retests`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  caseRetestJobs: (id: string, offset = 0, signal?: AbortSignal) =>
    request<Page<Job>>(
      `/cases/${encodeURIComponent(id)}/retest-jobs?limit=100&offset=${offset}`,
      { signal },
    ),
  caseRetestInputs: (id: string, signal?: AbortSignal) =>
    request<{ items: Asset[] }>(
      `/cases/${encodeURIComponent(id)}/retest-inputs`,
      { signal },
    ),
  linkRetestInput: (
    id: string,
    payload: { expected_version: number; asset_id: string; note: string },
  ) =>
    request<ReviewCase>(`/cases/${encodeURIComponent(id)}/retest-inputs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  engagementExportUrl: (id: string, format: "json" | "html") =>
    `/api/engagements/${encodeURIComponent(id)}/export?format=${format}`,
  catalog: (signal?: AbortSignal) => request<Catalog>("/catalog", { signal }),
  assets: (offset = 0, signal?: AbortSignal) =>
    request<Page<Asset>>(`/assets?limit=100&offset=${offset}`, { signal }),
  asset: (id: string, signal?: AbortSignal) =>
    request<Asset>(`/assets/${encodeURIComponent(id)}`, { signal }),
  assetJobs: (id: string, offset = 0, signal?: AbortSignal) =>
    request<Page<Job>>(
      `/assets/${encodeURIComponent(id)}/jobs?limit=100&offset=${offset}`,
      { signal },
    ),
  createAsset: (
    kind: AssetKind,
    name: string,
    source: Data,
    requestKey?: string,
  ) =>
    request<Asset>("/assets", {
      method: "POST",
      body: JSON.stringify({ kind, name, source }),
      headers: requestKey ? { "Idempotency-Key": requestKey } : undefined,
    }),
  preflight: (id: string, payload: InspectionRequest, signal?: AbortSignal) =>
    request<Preflight>(`/assets/${encodeURIComponent(id)}/preflight`, {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    }),
  inspectAsset: (id: string, payload: InspectionRequest, requestKey: string) =>
    request<Job>(`/assets/${encodeURIComponent(id)}/inspections`, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Idempotency-Key": requestKey },
    }),
  health: () => request<{ status: string; version: string }>("/health"),
  modules: () => request<{ items: ModuleSpec[] }>("/modules"),
  jobs: (module?: ModuleId, offset = 0, signal?: AbortSignal) =>
    request<Page<Job>>(
      `/jobs?limit=100&offset=${offset}${module ? `&module=${module}` : ""}`,
      { signal },
    ),
  job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  events: (id: string) =>
    request<{ items: JobEvent[] }>(`/jobs/${encodeURIComponent(id)}/events`),
  create: (module: ModuleId, name: string, config: Data, assetId?: string) =>
    request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({
        module,
        name,
        config,
        ...(assetId ? { asset_id: assetId } : {}),
      }),
    }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Upload>("/uploads", { method: "POST", body: form });
  },
  cancel: (id: string) =>
    request<Job>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  retry: (id: string, requestKey: string) =>
    request<Job>(`/jobs/${encodeURIComponent(id)}/retry`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
    }),
  methods: (id: string, search = "", offset = 0) =>
    request<MethodPage>(
      `/jobs/${encodeURIComponent(id)}/methods?search=${encodeURIComponent(search)}&offset=${offset}&limit=50`,
    ),
  method: (id: string, ref: string, offset = 0) =>
    request<MethodCode>(
      `/jobs/${encodeURIComponent(id)}/method?ref=${encodeURIComponent(ref)}&offset=${offset}&limit=80`,
    ),
  evidence: (id: string, evidence: string) =>
    request<Evidence>(
      `/jobs/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidence)}`,
    ),
  compare: (id: string, baseline: string, signal?: AbortSignal) =>
    request<WebComparison>(
      `/jobs/${encodeURIComponent(id)}/compare?baseline=${encodeURIComponent(baseline)}`,
      { signal },
    ),
  exportUrl: (id: string, format: "json" | "html" | "csv") =>
    `/api/jobs/${encodeURIComponent(id)}/export?format=${format}`,
};

export const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : "操作失败，请重试。";
export const errorRequestId = (error: unknown): string | undefined =>
  error instanceof ApiError ? error.requestId : undefined;
