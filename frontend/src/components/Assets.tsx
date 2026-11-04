import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  BookOpen,
  Cloud,
  Globe2,
  Plus,
  RefreshCw,
  Smartphone,
  Server,
} from "lucide-react";
import { api, errorText } from "../lib/api";
import type { Asset, AssetKind, Job } from "../lib/types";
import { assetKindLabel, dateLabel, strings, textValue } from "../lib/types";
import { Empty, ErrorBox, Loading, SearchField, StatusTag } from "./Common";
import { matchesSource, sourceOfInput } from "../lib/inspection-source";
import { SourceBadge } from "./SourceBadge";

const icons = {
  android: Smartphone,
  website: Globe2,
  cloud: Cloud,
  host: Server,
};
export function Assets({
  id,
  refreshKey,
  open,
  openJob,
  create,
  guide,
}: {
  id: string | null;
  refreshKey: number;
  open: (id: string | null) => void;
  openJob: (job: Job) => void;
  create: (asset?: Asset) => void;
  guide: () => void;
}) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<AssetKind | "all">("all");
  const [sourceScope, setSourceScope] = useState("work");
  useEffect(() => {
    // A newly saved asset belongs to the first page. Refreshing only the last
    // appended page can leave that new asset invisible until a manual reset.
    setOffset(0);
  }, [refreshKey]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    void api
      .assets(offset, controller.signal)
      .then((page) => {
        if (active) {
          setAssets((previous) =>
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
      .catch((failure) => {
        if (active) setError(errorText(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, refresh, refreshKey]);
  const matches = assets.filter(
    (asset) =>
      (kind === "all" || kind === asset.kind) &&
      matchesSource(
        sourceOfInput(asset.source, asset.kind, asset.provenance),
        sourceScope,
      ) &&
      `${asset.name} ${asset.id} ${strings(asset.source.targets).join(" ")} ${textValue(asset.source.filename)}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  if (id)
    return (
      <AssetDetail
        key={id}
        id={id}
        back={() => open(null)}
        create={create}
        openJob={openJob}
      />
    );
  return (
    <>
      <section className="overview-heading">
        <div>
          <div className="eyebrow">ASSET LIBRARY / 我的资产</div>
          <h1>
            选好对象，再开始检查。<span>↗</span>
          </h1>
          <p>
            主机、应用、网站和云资产各有自己的输入与历史。同一个资产可以反复检查，逐项回查结果。
          </p>
        </div>
        <button className="button button-primary" onClick={() => create()}>
          <Plus size={15} />
          添加并检查
        </button>
      </section>
      <div className="asset-start-hint">
        <BookOpen size={17} aria-hidden="true" />
        <div>
          <strong>第一次使用？先走通一个资产。</strong>
          <p>
            选择对象 → 选定检查 → 核对证据 → 验证与整改。没有 API
            密钥也可以开始。
          </p>
        </div>
        <button className="text-button" onClick={guide}>
          查看上手指南
          <ArrowRight size={13} />
        </button>
      </div>
      <div className="asset-library-toolbar">
        <label className="source-scope-filter">
          记录来源
          <select
            aria-label="资产记录来源"
            value={sourceScope}
            onChange={(event) => setSourceScope(event.target.value)}
          >
            <option value="work">实际输入</option>
            <option value="demo">合成演示</option>
            <option value="training">本地教学 / 实际采集</option>
            <option value="all">全部来源</option>
          </select>
        </label>
        <div className="status-filters" role="group" aria-label="资产类型筛选">
          {(["all", "android", "website", "cloud", "host"] as const).map(
            (value) => (
              <button
                key={value}
                aria-pressed={kind === value}
                onClick={() => setKind(value)}
              >
                {value === "all" ? "全部资产" : assetKindLabel[value]}
              </button>
            ),
          )}
        </div>
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="搜索名称、地址或文件"
          label="搜索资产"
        />
        <button
          className="text-button"
          onClick={() => {
            setOffset(0);
            setRefresh((value) => value + 1);
          }}
        >
          <RefreshCw size={13} />
          刷新
        </button>
      </div>
      {error && (
        <ErrorBox retry={() => setRefresh((value) => value + 1)}>
          {error}
        </ErrorBox>
      )}
      {loading && !assets.length ? (
        <Loading label="正在读取资产…" />
      ) : !assets.length ? (
        <Empty
          title="从第一个资产开始"
          detail="选择应用、网站或云配置，输入一次，后续可直接复用。"
          action={
            <button className="button button-primary" onClick={() => create()}>
              添加资产
              <ArrowRight size={14} />
            </button>
          }
        />
      ) : !matches.length ? (
        <Empty title="没有匹配的资产" detail="换一个名称或资产类型。" />
      ) : (
        <div className="asset-library-grid">
          {matches.map((asset) => {
            const Icon = icons[asset.kind];
            return (
              <article key={asset.id} className="asset-library-card">
                <header>
                  <Icon size={21} />
                  <span>{assetKindLabel[asset.kind]}</span>
                  <SourceBadge
                    source={sourceOfInput(
                      asset.source,
                      asset.kind,
                      asset.provenance,
                    )}
                  />
                </header>
                <button
                  className="asset-card-title"
                  onClick={() => open(asset.id)}
                >
                  {asset.name}
                  <ArrowRight size={17} />
                </button>
                <code>
                  {strings(asset.source.targets).join("\n") ||
                    textValue(asset.source.filename) ||
                    "内置可复现样例"}
                </code>
                <footer>
                  <small>
                    {asset.job_count === undefined
                      ? dateLabel(asset.created_at)
                      : `${asset.job_count} 次检查 · ${dateLabel(asset.last_checked_at || asset.created_at)}`}
                  </small>
                  <button className="text-button" onClick={() => create(asset)}>
                    再次检查 <ArrowRight size={13} />
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}
      <div className="history-pagination">
        <span>
          已载入 {assets.length} / {total} 个资产 · 筛选与搜索覆盖已载入记录
        </span>
        {assets.length < total && (
          <button
            className="text-button"
            disabled={loading}
            onClick={() => setOffset(assets.length)}
          >
            <ArrowDown size={13} />
            {loading ? "正在读取…" : "加载更多资产"}
          </button>
        )}
      </div>
    </>
  );
}

function AssetDetail({
  id,
  back,
  create,
  openJob,
}: {
  id: string;
  back: () => void;
  create: (asset: Asset) => void;
  openJob: (job: Job) => void;
}) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    void Promise.all([
      api.asset(id, controller.signal),
      api.assetJobs(id, offset, controller.signal),
    ])
      .then(([record, page]) => {
        if (active) {
          setAsset(record);
          setJobs((previous) =>
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
      .catch((failure) => {
        if (active) setError(errorText(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [id, offset, attempt]);
  return (
    <>
      <button className="back-button" onClick={back}>
        ← 返回资产列表
      </button>
      {error && (
        <ErrorBox retry={() => setAttempt((value) => value + 1)}>
          {error}
        </ErrorBox>
      )}
      {!asset ? (
        loading ? (
          <Loading label="正在读取资产…" />
        ) : null
      ) : (
        <>
          <section className="detail-heading">
            <div>
              <span className="eyebrow">
                {assetKindLabel[asset.kind]} / SAVED ASSET
              </span>
              <h1>{asset.name}</h1>
              <SourceBadge
                source={sourceOfInput(
                  asset.source,
                  asset.kind,
                  asset.provenance,
                )}
              />
              <p className="asset-detail-source">
                {strings(asset.source.targets).join(" · ") ||
                  textValue(asset.source.filename) ||
                  "内置可复现样例"}
              </p>
            </div>
            <button
              className="button button-primary"
              onClick={() => create(asset)}
            >
              再次检查
              <ArrowRight size={15} />
            </button>
          </section>
          <section className="result-section">
            <div className="result-section-heading">
              <div>
                <span className="eyebrow">ASSET HISTORY</span>
                <h3>
                  检查记录 <span>{total}</span>
                </h3>
              </div>
              <small>输入保存在本机 · 每次检查独立保留</small>
            </div>
            {!jobs.length ? (
              <p className="inline-empty">
                尚无检查记录，可以选择检查项目后开始。
              </p>
            ) : (
              <div className="asset-history">
                {jobs.map((job) => (
                  <button key={job.id} onClick={() => openJob(job)}>
                    <div>
                      <strong>{job.name}</strong>
                      <small>{dateLabel(job.created_at)}</small>
                    </div>
                    <StatusTag status={job.status} />
                    <ArrowRight size={15} />
                  </button>
                ))}
              </div>
            )}
            {jobs.length < total && (
              <button
                className="text-button"
                disabled={loading}
                onClick={() => setOffset(jobs.length)}
              >
                {loading ? "读取中…" : "加载更多记录"}
                <ArrowDown size={13} />
              </button>
            )}
          </section>
        </>
      )}
    </>
  );
}
