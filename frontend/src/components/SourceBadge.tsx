import type { InspectionSource } from "../lib/inspection-source";
export function SourceBadge({ source }: { source: InspectionSource }) {
  return (
    <span
      className={`inspection-source source-${source.kind}`}
      title={source.detail}
    >
      {source.label}
    </span>
  );
}
