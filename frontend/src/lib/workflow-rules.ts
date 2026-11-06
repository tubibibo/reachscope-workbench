import type { Asset, CaseStatus, Data, RetestResult } from "./types";
import { strings } from "./types";

// Mirrors authoritative validation in core/collaboration.py, core/inspections.py,
// modules/android/module.py, modules/cloud/module.py, and modules/host/input.py.
export const STATUSES_REQUIRING_NOTE = [
  "resolved",
  "accepted_risk",
  "false_positive",
] as const satisfies readonly CaseStatus[];

export function requiresCaseNote(status: CaseStatus): boolean {
  return STATUSES_REQUIRING_NOTE.some((required) => required === status);
}

export function requiresRetestForResolution(input: {
  status: CaseStatus;
  currentStatus: CaseStatus;
}): boolean {
  return input.status === "resolved" && input.currentStatus !== "resolved";
}

export function canCloseCase(input: {
  status: CaseStatus;
  currentStatus: CaseStatus;
  retestId: string;
  retestOutcome: RetestResult["outcome"] | undefined;
}): boolean {
  return (
    !requiresRetestForResolution(input) ||
    Boolean(input.retestId && input.retestOutcome === "not_observed_in_scope")
  );
}

export function retestChecks(source: Data): string[] {
  return strings(source.checks);
}

export function supportsRevisionLink(original: Asset | null): boolean {
  return Boolean(
    original &&
      (["apk", "import"].includes(String(original.source.mode)) ||
        (original.kind === "host" &&
          original.source.profile_id === "host-baseline" &&
          original.source.mode === "baseline")),
  );
}

export const INPUT_LIMITS = {
  apkBytes: 256 * 1024 * 1024,
  jsonBytes: 2 * 1024 * 1024,
  urls: 20,
  hostId: 128,
} as const;
