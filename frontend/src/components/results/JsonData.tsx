import type { Data } from "../../lib/types";

export function JsonData({ data }: { data: Data }) {
  return <pre className="data-block">{JSON.stringify(data, null, 2)}</pre>;
}
