import { useEffect, useRef, useState } from "react";
import { ArrowRight, Plus } from "lucide-react";
import { api } from "../lib/api";
import type { Asset, ReviewCase } from "../lib/types";
import { Loading } from "./Common";
import { Failure } from "./CollaborationShared";
import { supportsRevisionLink } from "../lib/workflow-rules";

export function RevisionInput({
  item,
  busy,
  linked,
  expandRequest = 0,
}: {
  item: ReviewCase;
  busy: boolean;
  linked: (value: ReviewCase) => void;
  expandRequest?: number;
}) {
  const [expanded, setExpanded] = useState(false),
    [original, setOriginal] = useState<Asset | null>(null),
    [assets, setAssets] = useState<Asset[]>([]),
    [known, setKnown] = useState<Asset[]>([]),
    [offset, setOffset] = useState(0),
    [total, setTotal] = useState(0),
    [selected, setSelected] = useState(""),
    [note, setNote] = useState(""),
    [loading, setLoading] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<unknown>(null);
  const savingRef = useRef(false);
  useEffect(() => {
    if (expandRequest > 0) setExpanded(true);
  }, [expandRequest]);
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    void Promise.all([
      api.asset(item.asset_id, controller.signal),
      api.assets(offset, controller.signal),
      api.caseRetestInputs(item.id, controller.signal),
    ])
      .then(([source, page, inputs]) => {
        if (active) {
          setOriginal(source);
          setAssets((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((value) => [
                      value.id,
                      value,
                    ]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
          setKnown(inputs.items);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [expanded, item.id, item.asset_id, item.version, offset]);
  const candidates = assets.filter(
    (asset) =>
      asset.id !== item.asset_id &&
      !known.some((value) => value.id === asset.id) &&
      asset.kind === original?.kind &&
      asset.source.profile_id === original?.source.profile_id &&
      (original?.kind !== "host" ||
        asset.source.host_id === original.source.host_id),
  );
  const supported = supportsRevisionLink(original);
  async function attach() {
    if (!selected || !note.trim() || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      linked(
        await api.linkRetestInput(item.id, {
          expected_version: item.version,
          asset_id: selected,
          note: note.trim(),
        }),
      );
      setSelected("");
      setNote("");
    } catch (failure) {
      setError(failure);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }
  return (
    <section className="case-section revision-input" id="host-case-revision">
      <button
        className="text-button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        如何关联修订文件？（说明） <Plus size={13} />
      </button>
      {expanded && (
        <>
          <p>
            保存的资产输入不可覆盖。先用原四步流程新增修订文件并完成检查，再明确关联到这条记录；关联不会扩大工作区范围。
          </p>
          <Failure value={error} />
          {loading ? (
            <Loading label="正在读取可关联的修订输入…" />
          ) : supported ? (
            <>
              <label className="field">
                <span className="field-label">已保存的修订文件资产</span>
                <select
                  aria-label="选择修订输入"
                  disabled={busy || saving}
                  value={selected}
                  onChange={(event) => setSelected(event.target.value)}
                >
                  <option value="">选择同类别、同输入方式的修订文件</option>
                  {candidates.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.name}
                    </option>
                  ))}
                </select>
              </label>
              <small>
                已载入 {assets.length}/{total}{" "}
                个资产。这里只提供同一输入方式的文件；资源身份与修改说明仍需人工核对。
              </small>
              {assets.length < total && (
                <button
                  className="text-button"
                  disabled={loading || saving}
                  onClick={() => setOffset(assets.length)}
                >
                  载入更多资产 ↓
                </button>
              )}
              <label className="field">
                <span className="field-label">修订关联说明</span>
                <textarea
                  aria-label="修订关联说明"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={3}
                  maxLength={4000}
                  disabled={busy || saving}
                  placeholder="说明文件属于同一应用或配置，以及修改内容。"
                />
              </label>
              <button
                className="button"
                disabled={busy || saving || !selected || !note.trim()}
                onClick={() => {
                  void attach();
                }}
              >
                {saving ? "正在关联…" : "关联修订文件"}
                <ArrowRight size={14} />
              </button>
            </>
          ) : (
            <p className="inline-empty">
              网站使用同一地址的后续检查复测；内置样例没有可关联的修订文件。文件关联仅用于相同
              APK 或配置输入方式。
            </p>
          )}
          {known.length > 0 && (
            <div className="linked-revisions">
              <strong>已关联输入</strong>
              {known.map((asset) => (
                <a key={asset.id} href={`#/assets/${asset.id}`}>
                  {asset.name} ↗
                </a>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
