import { request } from "./api";
import type { Data } from "./types";
import type { components } from "../generated/api";

export interface LabState {
  status: "running" | "stopped";
  generation: string;
  session_id: string | null;
  profile: "baseline" | "hardened";
  url: string | null;
  source: { kind: "local_training"; label: string; production: false };
  asset_template: { kind: "website"; name: string; source: Data } | null;
  limitations: string[];
}
export const labApi = {
  state: (signal?: AbortSignal) => request<LabState>("/lab", { signal }),
  start: () => request<LabState>("/lab/start", { method: "POST" }),
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
