import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Cloud,
  FileUp,
  Globe2,
  LoaderCircle,
  Smartphone,
  Server,
  X,
} from "lucide-react";
import { api, errorRequestId, errorText } from "../lib/api";
import type {
  AnalysisProfile,
  Asset,
  AssetKind,
  Catalog,
  Data,
  Job,
  InspectionRequest,
  ModuleId,
  Preflight,
  Upload,
} from "../lib/types";
import { assetKindLabel, strings, textValue } from "../lib/types";
import { ErrorBox, Loading } from "./Common";
import { sourceOfInput } from "../lib/inspection-source";
import { SourceBadge } from "./SourceBadge";
import { CloudInputPreview } from "./CloudInputPreview";
import { HostInputPreview } from "./HostInputPreview";
import { HostPreparation } from "./HostPreparation";
import { INPUT_LIMITS } from "../lib/workflow-rules";
import { zeroOr } from "../lib/display-labels";

const samples = [
  ["cross_component", "跨组件传参"],
  ["bridge", "JS 桥与文件"],
  ["wrong_key", "参数不匹配"],
  ["permission", "签名权限"],
  ["missing", "缺少实现"],
];
const steps = ["选择资产", "提供输入", "选择检查", "确认执行"];
const icons = {
  android: Smartphone,
  website: Globe2,
  cloud: Cloud,
  host: Server,
};
// Mirrors the private-address rules enforced by modules/web/scope.py; the
// backend stays authoritative — this is a discoverability hint only. IPv6
// beyond the ::1 literal and non-global special ranges are intentionally not
// enumerated here; the backend rejects them with an explicit message.
function privateTargets(urls: string[]): string[] {
  return urls.filter((url) => {
    try {
      const host = new URL(url).hostname.toLowerCase().replace(/\.$/, "");
      if (host === "localhost" || host.endsWith(".localhost")) return true;
      if (host === "::1" || host === "[::1]") return true;
      const match = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
      if (!match) return false;
      const first = Number(match[1]);
      const second = Number(match[2]);
      return (
        first === 127 ||
        first === 10 ||
        first === 0 ||
        (first === 100 && second >= 64 && second <= 127) ||
        (first === 192 && second === 168) ||
        (first === 172 && second >= 16 && second <= 31) ||
        (first === 169 && second === 254)
      );
    } catch {
      return false;
    }
  });
}
function dependencies(profile: AnalysisProfile, selected: string[]): string[] {
  const values = new Set([
    ...selected,
    ...profile.checks.filter((item) => item.required).map((item) => item.id),
  ]);
  let changed = true;
  while (changed) {
    changed = false;
    profile.checks.forEach((item) => {
      if (values.has(item.id))
        item.depends_on.forEach((id) => {
          if (!values.has(id)) {
            values.add(id);
            changed = true;
          }
        });
    });
  }
  return profile.checks
    .filter((item) => values.has(item.id))
    .map((item) => item.id);
}
export function NewJob({
  initialModule,
  initialAsset,
  close,
  created,
}: {
  initialModule: ModuleId;
  initialAsset?: Asset | null;
  close: () => void;
  created: (job: Job) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [step, setStep] = useState(initialAsset ? 1 : 0);
  const [kind, setKind] = useState<AssetKind>(
    initialAsset?.kind || (initialModule === "web" ? "website" : initialModule),
  );
  const [existing, setExisting] = useState<Asset | null>(initialAsset || null);
  const [profileId, setProfileId] = useState(
    textValue(initialAsset?.source.profile_id),
  );
  const [assetName, setAssetName] = useState(initialAsset?.name || "");
  const [name, setName] = useState("");
  const [sample, setSample] = useState("cross_component");
  const [hostId, setHostId] = useState(textValue(initialAsset?.source.host_id));
  const [targets, setTargets] = useState("");
  const [allowPrivate, setAllowPrivate] = useState(false);
  const [apktool, setApktool] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const savedDuringSubmit = useRef(false);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState<string>();
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [checking, setChecking] = useState(false);
  const uploadedFile = useRef<{ file: File; upload: Upload } | null>(null);
  const assetRequest = useRef<{ signature: string; key: string } | null>(null);
  const inspectionRequest = useRef<{ signature: string; key: string } | null>(
    null,
  );
  const dialog = useRef<HTMLDivElement>(null);
  const initialFocus = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const profiles =
    catalog?.profiles.filter((item) => item.asset_kind === kind) || [];
  const profile = catalog?.profiles.find((item) => item.id === profileId);
  const websiteTargets =
    profile?.input === "urls"
      ? targets
          .split(/\r?\n/)
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  const blockedTargets = allowPrivate ? [] : privateTargets(websiteTargets);
  const chosen = profile ? dependencies(profile, selected) : [];
  const chosenSignature = JSON.stringify(chosen);
  useEffect(() => {
    setPreflight(null);
    setRequestId(undefined);
    if (step !== 3 || !existing || !profile || busyRef.current) return;
    let active = true;
    const controller = new AbortController();
    setChecking(true);
    void api
      .preflight(
        existing.id,
        { checks: JSON.parse(chosenSignature) as string[] },
        controller.signal,
      )
      .then((value) => {
        if (active) setPreflight(value);
      })
      .catch((failure: unknown) => {
        if (active) {
          setError(errorText(failure));
          setRequestId(errorRequestId(failure));
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
      controller.abort();
      setChecking(false);
    };
  }, [step, existing, profile, chosenSignature]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    void Promise.all([
      api.catalog(controller.signal),
      api.assets(0, controller.signal),
    ])
      .then(([definitions, page]) => {
        if (!active) return;
        setCatalog(definitions);
        setAssets(page.items);
        setTotal(page.total);
      })
      .catch((failure) => {
        if (active) {
          setError(errorText(failure));
          setRequestId(errorRequestId(failure));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [loadAttempt]);
  useEffect(() => {
    if (!catalog) return;
    if (savedDuringSubmit.current) {
      savedDuringSubmit.current = false;
      return;
    }
    const candidate =
      catalog.profiles.find(
        (item) =>
          item.id === textValue(existing?.source.profile_id) &&
          item.asset_kind === kind,
      ) || catalog.profiles.find((item) => item.asset_kind === kind);
    if (candidate) {
      setProfileId(candidate.id);
      setSelected(
        candidate.checks
          .filter((item) => item.recommended !== false)
          .map((item) => item.id),
      );
    }
  }, [catalog, kind, existing]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    initialFocus.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) close();
      if (event.key === "Tab") {
        const elements = Array.from(
          dialog.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
          ) || [],
        ).filter((element) => element.getClientRects().length);
        const first = elements[0],
          last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [close]);
  useEffect(() => {
    content.current?.scrollTo({ top: 0 });
  }, [step]);
  function switchKind(value: AssetKind) {
    setKind(value);
    setExisting(null);
    setAssetName("");
    setTargets("");
    setHostId("");
    setFile(null);
    setAllowPrivate(false);
    setApktool("");
    setError("");
    setProfileId("");
  }
  function switchProfile(value: string) {
    const next = catalog?.profiles.find((item) => item.id === value);
    setProfileId(value);
    setFile(null);
    setError("");
    setSelected(
      next?.checks
        .filter((item) => item.recommended !== false)
        .map((item) => item.id) || [],
    );
  }
  function sourceConfig(): Data {
    if (existing) return { ...existing.source };
    if (!profile) throw new Error("请选择检查方式。");
    const source: Data = { profile_id: profile.id, mode: profile.mode };
    if (profile.input === "urls") {
      const urls = targets
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
      if (!urls.length || urls.length > INPUT_LIMITS.urls)
        throw new Error("请输入 1–20 个完整的 HTTP(S) 地址，每行一个。");
      if (
        urls.some((url) => {
          try {
            const value = new URL(url);
            return (
              !["http:", "https:"].includes(value.protocol) ||
              !!value.username ||
              !!value.password
            );
          } catch {
            return true;
          }
        })
      )
        throw new Error(
          "请填写完整的 http:// 或 https:// 地址，不包含账号密码。",
        );
      source.targets = urls;
      source.allow_private = allowPrivate;
    }
    if (profile.input === "apk" || profile.input === "json") {
      if (!file)
        throw new Error(
          profile.input === "apk"
            ? "请选择 APK 文件。"
            : "请选择配置或资产文件。",
        );
      const limit =
        profile.input === "apk"
          ? INPUT_LIMITS.apkBytes
          : INPUT_LIMITS.jsonBytes;
      if (!file.size || file.size > limit)
        throw new Error(
          profile.input === "apk"
            ? "请选择非空且不超过 256 MiB 的 APK。"
            : "请选择非空且不超过 2 MiB 的文件。",
        );
      if (
        profile.module === "cloud" &&
        !file.name.toLowerCase().endsWith(".json")
      )
        throw new Error("云配置目前支持 JSON 文件。");
      if (profile.input === "apk" && !file.name.toLowerCase().endsWith(".apk"))
        throw new Error("请选择 .apk 文件。");
      source.filename = file.name;
      if (profile.input === "apk" && apktool.trim())
        source.apktool = apktool.trim();
    }
    if (profile.id === "android-demo") source.sample = sample;
    if (profile.module === "host") {
      source.host_id = profile.mode === "demo" ? "demo-host-01" : hostId.trim();
      if (
        !source.host_id ||
        String(source.host_id).length > INPUT_LIMITS.hostId
      )
        throw new Error(
          "请填写 1–128 个字符的主机标识，并与配置文件中的 host_id 保持一致。",
        );
      if (
        profile.mode === "baseline" &&
        file &&
        !file.name.toLowerCase().endsWith(".json")
      )
        throw new Error(
          "主机配置资料需要 .json 文件；格式模板可在输入步骤下载。",
        );
    }
    return source;
  }
  async function saveCurrentAsset(): Promise<Asset> {
    if (existing) return existing;
    if (!profile) throw new Error("请选择检查方式。");
    const source = sourceConfig();
    if (file && (profile.input === "apk" || profile.input === "json")) {
      setStage("正在保存输入文件…");
      const upload =
        uploadedFile.current?.file === file
          ? uploadedFile.current.upload
          : await api.upload(file);
      uploadedFile.current = { file, upload };
      source.upload_id = upload.id;
      source.filename = upload.filename;
    }
    setStage("正在保存资产…");
    const savedName = (
      assetName.trim() ||
      file?.name ||
      (strings(source.targets)[0] ?? `${assetKindLabel[kind]} · 样例`)
    ).slice(0, 120);
    const signature = JSON.stringify({ kind, name: savedName, source });
    if (assetRequest.current?.signature !== signature)
      assetRequest.current = { signature, key: crypto.randomUUID() };
    const asset = await api.createAsset(
      kind,
      savedName,
      source,
      assetRequest.current.key,
    );
    savedDuringSubmit.current = true;
    setExisting(asset);
    return asset;
  }
  async function next() {
    if (busyRef.current) return;
    let preparing = false;
    try {
      if (!profile && step > 0) throw new Error("请选择检查方式。");
      if (step === 1) sourceConfig();
      if (step === 2 && !chosen.length)
        throw new Error("请至少选择一个检查项目。");
      if (
        step === 2 &&
        (profile?.module === "cloud" || profile?.module === "host") &&
        !existing
      ) {
        // This explicit next-step action saves the input for a local preview.
        // A job is created only by the separate final submission below.
        preparing = true;
        busyRef.current = true;
        setBusy(true);
        setPreflight(null);
        await saveCurrentAsset();
      }
      setError("");
      setStep(Math.min(3, step + 1));
    } catch (failure) {
      setError(errorText(failure));
      setRequestId(errorRequestId(failure));
    } finally {
      if (preparing) {
        busyRef.current = false;
        setBusy(false);
        setStage("");
      }
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (step !== 3) {
      await next();
      return;
    }
    if (busyRef.current || !profile) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setRequestId(undefined);
    try {
      const asset = await saveCurrentAsset();
      const payload: InspectionRequest = {
        checks: chosen,
        name: (name.trim() || `${asset.name} · ${profile.label}`).slice(0, 120),
      };
      const signature = JSON.stringify({ asset_id: asset.id, ...payload });
      if (inspectionRequest.current?.signature !== signature) {
        setStage("正在检查运行条件…");
        const conditions = await api.preflight(asset.id, payload);
        setPreflight(conditions);
        if (!conditions.ready) {
          setError("运行条件尚未满足，请处理下方提示后再次开始检查。");
          return;
        }
        inspectionRequest.current = { signature, key: crypto.randomUUID() };
      }
      // A response may be lost after the server accepted a job. Replaying that
      // exact operation must reach the server even if input readiness changed;
      // the inspection service checks replay before running fresh preflight.
      setStage("正在创建检查任务…");
      created(
        await api.inspectAsset(
          asset.id,
          payload,
          inspectionRequest.current.key,
        ),
      );
    } catch (failure) {
      setError(errorText(failure));
      setRequestId(errorRequestId(failure));
    } finally {
      busyRef.current = false;
      setBusy(false);
      setStage("");
    }
  }
  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.assets(assets.length);
      setAssets((previous) => [
        ...new Map(
          [...previous, ...page.items].map((item) => [item.id, item]),
        ).values(),
      ]);
      setTotal(page.total);
    } catch (failure) {
      setError(errorText(failure));
      setRequestId(errorRequestId(failure));
    } finally {
      setLoadingMore(false);
    }
  }
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) close();
      }}
    >
      <div
        className="new-job-panel asset-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-job-title"
        ref={dialog}
      >
        <header className="panel-heading">
          <div>
            <span className="eyebrow">NEW CHECK / 新建检查</span>
            <h2 id="new-job-title">
              从一个资产开始<span>↗</span>
            </h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={close}
            disabled={busy}
            aria-label="关闭新建任务"
            ref={initialFocus}
          >
            <X size={20} />
          </button>
        </header>
        <ol className="wizard-progress" aria-label="检查步骤">
          {steps.map((label, index) => (
            <li
              key={label}
              aria-current={index === step ? "step" : undefined}
              className={
                index === step ? "current" : index < step ? "done" : ""
              }
            >
              <span>{index < step ? <Check size={13} /> : index + 1}</span>
              {label}
            </li>
          ))}
        </ol>
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
        >
          <div className="wizard-content" ref={content}>
            {loading ? (
              <Loading label="正在读取检查目录与资产…" />
            ) : !catalog ? (
              <ErrorBox
                requestId={requestId}
                retry={() => setLoadAttempt((value) => value + 1)}
              >
                {error || "无法读取检查目录。"}
              </ErrorBox>
            ) : (
              <>
                <div className="wizard-step-title">
                  <span className="eyebrow">STEP {step + 1} / 04</span>
                  <h3>{steps[step]}</h3>
                </div>
                {step === 0 && (
                  <>
                    <p className="section-description">
                      先选择要检查的对象。后面的项目会随资产类型变化。
                    </p>
                    <div className="asset-kind-picker">
                      {catalog.asset_kinds.map((item) => {
                        const Icon = icons[item.id];
                        return (
                          <button
                            type="button"
                            key={item.id}
                            className={kind === item.id ? "selected" : ""}
                            aria-pressed={kind === item.id}
                            onClick={() => switchKind(item.id)}
                          >
                            <Icon size={23} />
                            <strong>{item.label}</strong>
                            <small>{item.description}</small>
                          </button>
                        );
                      })}
                    </div>
                    <label className="field">
                      <span className="field-label">
                        使用已有资产 <small>可选</small>
                      </span>
                      <select
                        aria-label="选择已有资产"
                        value={existing?.id || ""}
                        onChange={(event) => {
                          const asset =
                            assets.find(
                              (item) => item.id === event.target.value,
                            ) || null;
                          setExisting(asset);
                          setAssetName(asset?.name || "");
                          setError("");
                        }}
                      >
                        <option value="">新建一个{assetKindLabel[kind]}</option>
                        {assets
                          .filter((asset) => asset.kind === kind)
                          .map((asset) => (
                            <option key={asset.id} value={asset.id}>
                              {asset.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <p className="field-hint">
                      {zeroOr(
                        total,
                        "暂无已保存资产。",
                        `已载入 ${assets.length} / ${total} 个资产，已有文件可直接复用。`,
                      )}
                    </p>
                    {assets.length < total && (
                      <button
                        type="button"
                        className="text-button"
                        disabled={loadingMore}
                        onClick={() => {
                          void loadMore();
                        }}
                      >
                        {loadingMore ? "正在读取…" : "载入更多资产"}
                      </button>
                    )}
                  </>
                )}
                {step === 1 && (
                  <>
                    {existing ? (
                      <div className="saved-asset-card">
                        <span className="subtle-tag">已保存资产</span>
                        <SourceBadge
                          source={sourceOfInput(
                            existing.source,
                            existing.kind,
                            existing.provenance,
                          )}
                        />
                        <h4>{existing.name}</h4>
                        <p>{profile?.label}</p>
                        <code>
                          {strings(existing.source.targets).join("\n") ||
                            textValue(existing.source.filename) ||
                            "内置可复现样例"}
                        </code>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => {
                            setExisting(null);
                            setFile(null);
                            setAssetName("");
                          }}
                        >
                          更换输入，另存为新资产 <ArrowRight size={13} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <label className="field">
                          <span className="field-label">检查方式</span>
                          <select
                            aria-label="选择检查方式"
                            value={profileId}
                            onChange={(event) =>
                              switchProfile(event.target.value)
                            }
                          >
                            {profiles.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.label}
                                {item.mode === "demo"
                                  ? " / 合成演示"
                                  : item.mode === "import" && kind === "website"
                                    ? " / 未复测"
                                    : ""}
                              </option>
                            ))}
                          </select>
                          <small className="field-hint">
                            {profile?.description}
                          </small>
                          {profile && (
                            <SourceBadge
                              source={sourceOfInput(
                                { mode: profile.mode },
                                kind,
                              )}
                            />
                          )}
                          {kind === "website" && (
                            <small className="field-hint">
                              从网站地址开始；导入文件与合成样例保留为其他来源，结果分别标记。
                            </small>
                          )}
                        </label>
                        <label className="field">
                          <span className="field-label">
                            资产名称 <small>可选</small>
                          </span>
                          <input
                            value={assetName}
                            maxLength={100}
                            onChange={(event) =>
                              setAssetName(event.target.value)
                            }
                            placeholder="便于下次查找的名称"
                          />
                        </label>
                        {profile?.input === "urls" && (
                          <>
                            <label className="field">
                              <span className="field-label">
                                {kind === "cloud"
                                  ? "云服务器服务地址"
                                  : "网站地址"}
                                <small>每行一个，最多 20 个</small>
                              </span>
                              <textarea
                                aria-label={
                                  kind === "cloud"
                                    ? "云服务器服务地址"
                                    : "网站地址"
                                }
                                rows={4}
                                value={targets}
                                onChange={(event) =>
                                  setTargets(event.target.value)
                                }
                                placeholder="https://your-domain.example/"
                              />
                              <small className="field-hint">
                                填写完整的 http:// 或 https://
                                地址，可指定端口。只观察这些服务，不扫描其他端口。
                              </small>
                            </label>
                            <label className="checkbox-field">
                              <input
                                type="checkbox"
                                checked={allowPrivate}
                                onChange={(event) =>
                                  setAllowPrivate(event.target.checked)
                                }
                              />
                              <span>
                                包含我的本机或内网地址
                                <small>默认只允许公网地址。</small>
                              </span>
                            </label>
                            {blockedTargets.length > 0 && (
                              <p className="wizard-warning" role="status">
                                检测到 {blockedTargets.length}{" "}
                                个本机/内网地址：不勾选「包含我的本机或内网地址」时，这些目标将被拒绝执行。
                              </p>
                            )}
                          </>
                        )}
                        {(profile?.input === "apk" ||
                          profile?.input === "json") && (
                          <>
                            <label
                              className={`upload-field ${file ? "has-file" : ""}`}
                            >
                              <FileUp size={24} />
                              <strong>
                                {file?.name ||
                                  (profile.input === "apk"
                                    ? "选择安卓 APK"
                                    : profile.module === "cloud"
                                      ? "选择云配置 JSON"
                                      : profile.module === "host"
                                        ? profile.mode === "baseline"
                                          ? "选择主机配置 JSON"
                                          : "选择服务器日志"
                                        : "选择资产文件")}
                              </strong>
                              <span>
                                {file
                                  ? `${(file.size / 1024).toFixed(1)} KiB`
                                  : profile.input === "apk"
                                    ? "最大 256 MiB"
                                    : "最大 2 MiB"}
                              </span>
                              <input
                                type="file"
                                aria-label={
                                  profile.input === "apk"
                                    ? "选择 APK 文件"
                                    : "选择配置或资产文件"
                                }
                                accept={
                                  profile.input === "apk"
                                    ? ".apk"
                                    : profile.module === "cloud"
                                      ? ".json"
                                      : profile.module === "host"
                                        ? profile.mode === "baseline"
                                          ? ".json"
                                          : ".log,.txt"
                                        : ".json,.csv,.jsonl,.ndjson"
                                }
                                onChange={(event) =>
                                  setFile(event.target.files?.[0] || null)
                                }
                              />
                            </label>
                            {profile.module === "cloud" && (
                              <p className="field-hint">
                                支持 Terraform Plan JSON 或独立 IAM
                                策略。只审查文件中的配置，不连接云账号。
                              </p>
                            )}
                          </>
                        )}
                        {profile?.module === "host" &&
                          profile.mode !== "demo" && (
                            <>
                              <label className="field">
                                <span className="field-label">主机标识</span>
                                <input
                                  value={hostId}
                                  onChange={(event) =>
                                    setHostId(event.target.value)
                                  }
                                  placeholder="例如 srv-web-01"
                                  maxLength={128}
                                />
                              </label>
                              <p className="field-hint">
                                用于固定资料与复测的主机身份；配置文件中的
                                host_id
                                应与此一致。此标识不会触发网络请求，也不代表已验证主机身份。
                              </p>
                              {profile.mode === "baseline" ? (
                                <HostPreparation />
                              ) : (
                                <p className="field-hint">
                                  上传 Nginx common/combined 访问日志或 SSH
                                  认证日志。时间无法确定时保留未知；结果仅展示脱敏字段。原始文件会保存在本机。
                                </p>
                              )}
                            </>
                          )}
                        {profile?.id === "android-demo" && (
                          <label className="field">
                            <span className="field-label">源码样例</span>
                            <select
                              value={sample}
                              onChange={(event) =>
                                setSample(event.target.value)
                              }
                            >
                              {samples.map(([id, label]) => (
                                <option key={id} value={id}>
                                  {label}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        {profile?.input === "demo" && (
                          <div className="sample-note">
                            <span className="mono">LOCAL FIXTURE</span>
                            <p>
                              使用随项目提供的合成样例运行分析，不联系外部目标。
                            </p>
                          </div>
                        )}
                        {profile?.input === "apk" && (
                          <details className="wizard-advanced">
                            <summary>高级设置</summary>
                            <label className="field">
                              <span className="field-label">
                                Apktool JAR 路径 <small>本机已配置可留空</small>
                              </span>
                              <input
                                value={apktool}
                                onChange={(event) =>
                                  setApktool(event.target.value)
                                }
                                placeholder="本机 apktool.jar 完整路径"
                              />
                            </label>
                          </details>
                        )}
                      </>
                    )}
                    {kind === "host" && (
                      <p className="wizard-boundary">
                        本轮仅分析提供的配置与日志，没有持续主机监控、远程执行或自动封禁。完整输入与明确时间有助于减少误判。
                      </p>
                    )}
                    {kind === "cloud" && (
                      <p className="wizard-boundary">
                        服务器地址用于外部服务观察。身份权限、安全组与存储配置需要配置文件，不能仅凭
                        IP 判断。
                      </p>
                    )}
                  </>
                )}
                {step === 2 && profile && (
                  <>
                    {(profile.module === "cloud" ||
                      profile.module === "host") &&
                      !existing && (
                        <p className="wizard-boundary">
                          点击“下一步”将把配置保存在本机并解析覆盖预览；还不会创建检查任务。确认预览后，再点击“开始检查”。
                        </p>
                      )}
                    <p className="section-description">
                      已推荐该方式下的检查项目。勾选决定执行内容，必要依赖会自动加入。
                    </p>
                    <div className="wizard-checks">
                      {profile.checks.map((item) => (
                        <label
                          className={`wizard-check ${chosen.includes(item.id) ? "selected" : ""}`}
                          key={item.id}
                        >
                          <input
                            type="checkbox"
                            checked={chosen.includes(item.id)}
                            disabled={item.required}
                            onChange={(event) => {
                              if (event.target.checked)
                                setSelected(
                                  dependencies(profile, [...selected, item.id]),
                                );
                              else {
                                const remove = new Set([item.id]);
                                let changed = true;
                                while (changed) {
                                  changed = false;
                                  profile.checks.forEach((check) => {
                                    if (
                                      check.depends_on.some((id) =>
                                        remove.has(id),
                                      ) &&
                                      !remove.has(check.id)
                                    ) {
                                      remove.add(check.id);
                                      changed = true;
                                    }
                                  });
                                }
                                setSelected(
                                  selected.filter((id) => !remove.has(id)),
                                );
                              }
                            }}
                          />
                          <span>
                            <strong>
                              {item.label}
                              {item.required && <small>必需</small>}
                            </strong>
                            <p>{item.description}</p>
                            {item.depends_on.length > 0 && (
                              <small>
                                依赖：
                                {item.depends_on
                                  .map(
                                    (id) =>
                                      profile.checks.find(
                                        (check) => check.id === id,
                                      )?.label || id,
                                  )
                                  .join("、")}
                              </small>
                            )}
                          </span>
                        </label>
                      ))}
                    </div>
                  </>
                )}
                {step === 3 && profile && (
                  <>
                    <div className="wizard-confirm">
                      <div>
                        <span>资产</span>
                        <strong>
                          {existing?.name ||
                            assetName ||
                            file?.name ||
                            targets.split("\n")[0] ||
                            `${assetKindLabel[kind]} · 样例`}
                        </strong>
                      </div>
                      <div>
                        <span>方式</span>
                        <strong>{profile.label}</strong>
                      </div>
                      <div>
                        <span>执行项目</span>
                        <strong>
                          {profile.checks
                            .filter((item) => chosen.includes(item.id))
                            .map((item) => item.label)
                            .join("、")}
                        </strong>
                      </div>
                      <div>
                        <span>请求范围</span>
                        <strong>
                          {profile.network
                            ? "向指定的 HTTP(S) 服务发送 GET 请求"
                            : "仅在本机分析，不发送目标网络请求"}
                        </strong>
                      </div>
                    </div>
                    {profile.network && (
                      <pre className="wizard-url-preview">
                        {existing
                          ? strings(existing.source.targets).join("\n")
                          : targets.trim()}
                      </pre>
                    )}
                    <label className="field">
                      <span className="field-label">
                        本次任务名称 <small>可选</small>
                      </span>
                      <input
                        value={name}
                        maxLength={100}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="默认使用资产名称与检查方式"
                        disabled={busy}
                      />
                    </label>
                    <p className="field-hint">
                      资产与输入保存在本机，后续可再次检查。结果明确记录已执行、跳过和信息不足的项目。
                    </p>
                    <section
                      className="preflight-panel"
                      aria-label="运行条件检查"
                    >
                      <div className="preflight-heading">
                        <strong>运行条件</strong>
                        {checking && (
                          <LoaderCircle size={14} className="spin" />
                        )}
                      </div>
                      {blockedTargets.length > 0 && (
                        <p className="wizard-warning" role="status">
                          将拒绝执行 {blockedTargets.length}{" "}
                          个本机/内网目标（未勾选「包含我的本机或内网地址」）：
                          {blockedTargets.slice(0, 3).join("、")}
                          {blockedTargets.length > 3 ? " 等" : ""}。
                        </p>
                      )}
                      {preflight ? (
                        <>
                          <p>
                            {preflight.ready
                              ? profile.network
                                ? "当前运行条件已满足。目标响应情况会在执行时记录。"
                                : "本地输入与运行条件已就绪。实际检查将在确认开始后执行。"
                              : "暂时无法开始，请处理标出的条件。"}
                          </p>
                          <ul>
                            {preflight.items.map((item) => (
                              <li
                                key={item.id}
                                className={`preflight-${item.status}`}
                              >
                                <span>
                                  {item.status === "blocked"
                                    ? "需处理"
                                    : item.status === "warning"
                                      ? "提示"
                                      : "就绪"}
                                </span>
                                <div>
                                  <strong>{item.label}</strong>
                                  <p>{item.message}</p>
                                </div>
                              </li>
                            ))}
                          </ul>
                          {preflight.input_preview &&
                            ("resources_total" in preflight.input_preview ? (
                              <CloudInputPreview
                                preview={preflight.input_preview}
                              />
                            ) : (
                              <HostInputPreview
                                preview={preflight.input_preview}
                              />
                            ))}
                        </>
                      ) : (
                        <p>
                          {checking
                            ? "正在检查已保存输入和运行环境…"
                            : "提交时检查输入是否可读、检查项目与运行环境是否就绪。此步骤不会向目标发送请求。"}
                        </p>
                      )}
                    </section>
                  </>
                )}
              </>
            )}
            {error && catalog && (
              <ErrorBox requestId={requestId}>{error}</ErrorBox>
            )}
          </div>
          <footer className="form-footer wizard-footer">
            <span>{stage || `第 ${step + 1} 步，共 4 步`}</span>
            <div>
              {step > 0 && (
                <button
                  className="button button-outline"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setStep(step - 1);
                    setError("");
                  }}
                >
                  <ArrowLeft size={14} />
                  上一步
                </button>
              )}
              <button
                className="button button-primary"
                type="submit"
                disabled={loading || !catalog || busy || checking}
              >
                {busy && <LoaderCircle size={15} className="spin" />}
                {busy ? "处理中" : step === 3 ? "开始检查" : "下一步"}
                {!busy && <ArrowRight size={15} />}
              </button>
            </div>
          </footer>
        </form>
      </div>
    </div>
  );
}
