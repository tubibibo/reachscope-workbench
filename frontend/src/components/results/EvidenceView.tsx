import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ModuleResult } from "../../lib/types";
import { Empty, KeyValues, SearchField } from "../Common";
import { JsonData } from "./JsonData";

export function EvidenceView({
  result,
  selectedId,
  select,
}: {
  result: ModuleResult;
  selectedId: string | null;
  select: (id: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = result.evidence.filter((item) =>
    `${item.title} ${item.kind} ${item.source}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const selected = result.evidence.find((item) => item.id === selectedId);
  return (
    <section className="result-section evidence-view">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">PERSISTED EVIDENCE</span>
          <h3>
            证据索引 <span>{result.evidence.length}</span>
          </h3>
        </div>
        <SearchField
          value={search}
          onChange={setSearch}
          label="搜索证据"
          placeholder="搜索标题、来源或类型"
        />
      </div>
      <div className="evidence-grid">
        <div className="evidence-list">
          {filtered.map((item, index) => (
            <button
              key={item.id}
              onClick={() => select(item.id)}
              className={selected?.id === item.id ? "selected" : ""}
            >
              <span className="mono">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{item.title}</strong>
                <small>
                  {item.kind} / {item.source}
                </small>
              </div>
              <ChevronRight size={14} />
            </button>
          ))}
          {!filtered.length && <p className="inline-empty">没有匹配的证据。</p>}
        </div>
        <div className="evidence-inspector">
          {selected ? (
            <>
              <span className="eyebrow">{selected.kind}</span>
              <h3>{selected.title}</h3>
              <div className="evidence-id mono">{selected.id}</div>
              <KeyValues
                data={{
                  source: selected.source,
                  ...(selected.sha256 ? { sha256: selected.sha256 } : {}),
                }}
              />
              <JsonData data={selected.data} />
            </>
          ) : (
            <Empty
              title="选择一条证据"
              detail="原始响应、代码位置与分析依据保存在这里。"
            />
          )}
        </div>
      </div>
    </section>
  );
}
