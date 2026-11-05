import { request } from "./api";
import type { Data } from "./types";
import type { components } from "../generated/api";

export interface LabState {
  status: "running" | "stopped";
  generation: string;
  session_id: string | null;
  profile: "baseline" | "hardened";
  scenario?: {
    id: string;
    title: Record<string, string>;
    difficulty: string;
  } | null;
  url: string | null;
  source: { kind: "local_training"; label: string; production: false };
  asset_template: { kind: "website"; name: string; source: Data } | null;
  limitations: string[];
}
export interface ScenarioSummary {
  id: string;
  title: Record<string, string>;
  summary: Record<string, string>;
  difficulty: string;
}
export interface ScenarioIssue {
  source: string;
  code: string;
  message: string;
}
export const labApi = {
  state: (signal?: AbortSignal) => request<LabState>("/lab", { signal }),
  scenarios: (signal?: AbortSignal) =>
    request<{ packs: ScenarioSummary[]; issues: ScenarioIssue[] }>(
      "/lab/scenarios",
      { signal },
    ),
  start: (scenarioId?: string) =>
    request<LabState>("/lab/start", {
      method: "POST",
      ...(scenarioId
        ? {
            body: JSON.stringify({
              scenario_id: scenarioId,
            } satisfies components["schemas"]["LabStart"]),
          }
        : {}),
    }),
  configure: (generation: string, profile: LabState["profile"]) =>
    request<LabState>("/lab/configure", {
      method: "POST",
      body: JSON.stringify({
        generation,
        profile,
      } satisfies components["schemas"]["LabConfigure"]),
    }),
  stop: () => request<LabState>("/lab/stop", { method: "POST" }),
};
