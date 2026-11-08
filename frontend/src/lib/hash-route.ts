// Pure hash-route helpers and the view taxonomy. The location hash IS
// the router (App parses it on every hashchange); never write to it from
// anchor clicks.
import type { Job, ModuleId } from "./types";

export type View =
  | "all"
  | "assets"
  | "collaboration"
  | "ai"
  | "guide"
  | "lab"
  | ModuleId;
export const routeView = (): View => {
  const hash = window.location.hash;
  if (hash.startsWith("#/settings/ai")) return "ai";
  if (hash.startsWith("#/engagements")) return "collaboration";
  if (hash.startsWith("#/guide")) return "guide";
  if (hash.startsWith("#/lab")) return "lab";
  const module = hash.match(/^#\/modules\/(android|web|cloud|host)$/)?.[1];
  if (module) return module as ModuleId;
  if (hash.startsWith("#/jobs/") || hash === "#/") return "all";
  return "assets";
};
export type DetailTab = "result" | "evidence" | "events" | "input";
export const decodedId = (value: string): string | null => {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
};
export const initialId = () =>
  window.location.hash.startsWith("#/jobs/")
    ? decodedId(window.location.hash.slice(7))
    : null;
export const initialAssetId = () =>
  window.location.hash.startsWith("#/assets/")
    ? decodedId(window.location.hash.slice(9))
    : null;
export const initialEngagementId = () =>
  window.location.hash.match(/^#\/engagements\/([^/]+)/)?.[1] || null;
export const initialCaseId = () =>
  window.location.hash.match(/^#\/engagements\/[^/]+\/cases\/([^/]+)/)?.[1] ||
  null;
export const jobAssetKind = (job: Job) =>
  job.asset_snapshot?.kind || (job.module === "web" ? "website" : job.module);
