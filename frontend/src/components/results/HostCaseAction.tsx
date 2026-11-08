import { useEffect, useRef, useState } from "react";
import { ArrowRight, Plus } from "lucide-react";
import { api } from "../../lib/api";
import type { Candidate, Engagement, Job } from "../../lib/types";
import { ErrorBox, Loading } from "../Common";
import { errorRequestId, errorText } from "../../lib/api";
import { CreateWorkspace } from "../Collaboration";

export function HostCaseAction({ job }: { job: Job }) {
  const [expanded, setExpanded] = useState(false),
    [creatingScope, setCreatingScope] = useState(false);
  const [workspaces, setWorkspaces] = useState<Engagement[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0);
  const [workspace, setWorkspace] = useState(""),
    [rows, setRows] = useState<Candidate[]>([]),
    [selected, setSelected] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false),
    [loadingSources, setLoadingSources] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const request = useRef<{ signature: string; key: string } | null>(null),
    saving = useRef(false),
    creating = useRef<AbortController | null>(null);
  useEffect(() => () => creating.current?.abort(), []);
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void api
      .engagements(offset, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) {
          setWorkspaces((previous) =>
            offset
              ? [
                  ...new Map(
                    [...previous, ...page.items].map((item) => [item.id, item]),
                  ).values(),
                ]
              : page.items,
          );
          setTotal(page.total);
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [expanded, offset]);
  useEffect(() => {
    setRows([]);
    setSelected("");
    setError(null);
    setConfirmed(false);
    setLoadingSources(false);
    if (!expanded || !workspace) return;
    const controller = new AbortController();
    setLoadingSources(true);
    void api
      .candidates(workspace, job.id, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) setRows(page.items);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingSources(false);
      });
    return () => controller.abort();
  }, [workspace, job.id, expanded]);
  const scopes = workspaces.filter(
    (scope) =>
      Array.isArray(scope.asset_ids) &&
      scope.asset_ids.includes(job.asset_id || ""),
  );
  async function create() {
    const candidate = rows.find((row) => row.source_ref === selected);
    if (!candidate || !workspace || !confirmed || saving.current) return;
    const controller = new AbortController();
    creating.current = controller;
    saving.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const signature = JSON.stringify({
        workspace,
        job: job.id,
        source: candidate.source_ref,
        kind: candidate.source_kind,
      });
      if (request.current?.signature !== signature)
        request.current = { signature, key: crypto.randomUUID() };
      const item = await api.createCase(
        workspace,
        candidate,
        request.current.key,
        controller.signal,
      );
      if (!controller.signal.aborted)
        window.location.hash = `/engagements/${encodeURIComponent(workspace)}/cases/${encodeURIComponent(item.id)}`;
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure);
    } finally {
      if (creating.current === controller && !controller.signal.aborted) {
        creating.current = null;
        saving.current = false;
        setBusy(false);
      }
    }
  }
  function cancelWaiting() {
    creating.current?.abort();
    creating.current = null;
    saving.current = false;
    setBusy(false);
    setNotice(
      "已停止等待。服务端可能已建立事项，请先到所选工作区核对；再次确认同一来源将沿用原请求标识，不会自动重试。",
    );
  }
  if (!job.asset_id)
    return (
      <p className="host-note">
        此历史检查未绑定保存资产；先从资产重新检查，再建立有范围的整改事项。
      </p>
    );
  return (
    <section className="host-case-action" aria-label="从主机证据进入整改">
      <div className="host-action-heading">
        <div>
          <span className="eyebrow">NEXT / EVIDENCE TO REVIEW</span>
          <h4>把本次证据接入整改</h4>
        </div>
        <button
          type="button"
          className="button button-outline"
          aria-expanded={expanded}
          disabled={busy}
          onClick={() => setExpanded(!expanded)}
        >
          选择证据建立事项 <ArrowRight size={13} />
        </button>
      </div>
      <p className="host-note">
        使用已有验证与整改流程。先明确包含此资产的工作范围，再主动选择保存的证据；未知项可记录待补资料，日志线索不会变成已确认入侵。
      </p>
      {expanded && (
        <>
          {Boolean(error) && (
            <ErrorBox requestId={errorRequestId(error)}>
              {errorText(error)}
            </ErrorBox>
          )}
          {notice && (
            <p className="scope-note" role="status">
              {notice}
            </p>
          )}
          {loading && <Loading label="读取可用工作范围…" />}
          <label className="field">
            <span className="field-label">包含本资产的工作区</span>
            <select
              aria-label="选择主机整改工作区"
              value={workspace}
              disabled={busy}
              onChange={(event) => setWorkspace(event.target.value)}
            >
              <option value="">请选择已有范围</option>
              {scopes.map((scope) => (
                <option key={scope.id} value={scope.id}>
                  {scope.name}
                </option>
              ))}
            </select>
          </label>
          <div className="host-action-links">
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={() => setCreatingScope(true)}
            >
              建立包含此资产的工作区 <Plus size={12} />
            </button>
            {workspaces.length < total && (
              <button
                type="button"
                className="text-button"
                disabled={loading || busy}
                onClick={() => setOffset(workspaces.length)}
              >
                载入更多工作区
              </button>
            )}
          </div>
          {!loading && scopes.length === 0 && (
            <p className="host-note">
              当前载入范围尚未包含这个资产。可先建立明确范围，或继续载入已有工作区；不会自动猜测服务器与网站/云资产之间的身份关系。
            </p>
          )}
          {workspace && (
            <>
              <label className="host-scope-confirm">
                <input
                  type="checkbox"
                  aria-label="确认主机整改工作区"
                  checked={confirmed}
                  disabled={busy}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>
                  我已核对所选工作区包含本资产，并确认此条保存证据在已记录的授权范围内；这只是人工范围确认，不是外部授权证明。
                </span>
              </label>
              {loadingSources ? (
                <Loading label="读取可建立事项的真实来源…" />
              ) : (
                <>
                  <label className="field">
                    <span className="field-label">
                      本次检查中有保存依据的条目
                    </span>
                    <select
                      aria-label="选择主机整改证据"
                      value={selected}
                      disabled={busy}
                      onChange={(event) => setSelected(event.target.value)}
                    >
                      <option value="">请选择证据来源</option>
                      {rows.map((row) => (
                        <option key={row.source_ref} value={row.source_ref}>
                          {row.title}
                          {row.status === "unknown" ? " · 信息不足" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!rows.length && (
                    <p className="host-note">
                      本次没有可建立整改事项的来源；满足项和无命中日志不需要制造新问题。
                    </p>
                  )}
                </>
              )}
              <button
                type="button"
                className="button button-primary"
                disabled={busy || !selected || !confirmed || loadingSources}
                onClick={() => {
                  void create();
                }}
              >
                {busy ? "正在建立…" : "确认建立整改事项"}
                <ArrowRight size={13} />
              </button>
              {busy && (
                <button
                  type="button"
                  className="text-button"
                  onClick={cancelWaiting}
                >
                  停止等待建立结果
                </button>
              )}
            </>
          )}
        </>
      )}
      {creatingScope && (
        <CreateWorkspace
          initialAssetId={job.asset_id}
          close={() => setCreatingScope(false)}
          created={(scope) => {
            setWorkspaces((previous) => [
              scope,
              ...previous.filter((item) => item.id !== scope.id),
            ]);
            setWorkspace(scope.id);
            setCreatingScope(false);
          }}
        />
      )}
    </section>
  );
}
