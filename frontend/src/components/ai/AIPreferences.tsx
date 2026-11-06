import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Plug2, Stethoscope } from "lucide-react";
import { errorRequestId, errorText } from "../../lib/api";
import { aiApi } from "../../ai/api";
import { normalizeProviderId } from "../../ai/types";
import type {
  AIConfig,
  AIProviderId,
  AIProviderPreset,
  TokenLimitField,
} from "../../ai/types";
import type { AIDiagnosis } from "../../ai/types";
import { ErrorBox, Loading } from "../Common";
import { SavedModelsDiagnosis } from "./SavedModelsDiagnosis";

const effortLabels: Record<AIConfig["reasoning_effort"], string> = {
  default: "由模型默认（不发送参数）",
  none: "关闭",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "XHigh",
  max: "Max",
};
function diagnosisValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value))
    return value
      .filter((item): item is string => typeof item === "string")
      .join("；");
  return value === undefined || value === null
    ? "未返回"
    : JSON.stringify(value);
}

export function AIPreferences() {
  const [config, setConfig] = useState<AIConfig | null>(null),
    [presets, setPresets] = useState<AIProviderPreset[]>([]),
    [error, setError] = useState<unknown>(null),
    [revision, setRevision] = useState(0),
    [enabled, setEnabled] = useState(false),
    [providerId, setProviderId] = useState<AIProviderId>("custom"),
    [baseUrl, setBaseUrl] = useState(""),
    [model, setModel] = useState(""),
    [reasoningEffort, setReasoningEffort] =
      useState<AIConfig["reasoning_effort"]>("default"),
    [tokenLimitField, setTokenLimitField] =
      useState<TokenLimitField>("max_tokens"),
    [key, setKey] = useState(""),
    [allowLocal, setAllowLocal] = useState(false),
    [clearKey, setClearKey] = useState(false),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false),
    [diagnosing, setDiagnosing] = useState(false),
    [diagnosis, setDiagnosis] = useState<AIDiagnosis | null>(null),
    [diagnosisError, setDiagnosisError] = useState<unknown>(null);
  const busyRef = useRef(false);
  const diagnosisBusy = useRef(false);
  const drafts = useRef<
    Partial<
      Record<
        AIProviderId,
        {
          base_url: string;
          model: string;
          reasoning_effort: AIConfig["reasoning_effort"];
          token_limit_field: TokenLimitField;
        }
      >
    >
  >({});
  const preset = presets.find(
    (item) => normalizeProviderId(item.id) === normalizeProviderId(providerId),
  );
  const endpointChanged = Boolean(
    config &&
      (config.provider_id !== providerId ||
        config.base_url.replace(/\/+$/, "") !==
          baseUrl.trim().replace(/\/+$/, "")),
  );
  const dirty = Boolean(
    config &&
      (endpointChanged ||
        config.enabled !== enabled ||
        config.model !== model.trim() ||
        config.reasoning_effort !== reasoningEffort ||
        config.token_limit_field !== tokenLimitField ||
        config.allow_local !== allowLocal ||
        key ||
        clearKey),
  );
  useEffect(() => {
    setDiagnosis(null);
    setDiagnosisError(null);
  }, [providerId, baseUrl, allowLocal]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setError(null);
    void Promise.all([
      aiApi.config(controller.signal),
      aiApi.providers(controller.signal),
    ])
      .then(([value, catalogue]) => {
        if (active) {
          setConfig(value);
          setEnabled(value.enabled);
          setPresets(catalogue.items);
          setProviderId(normalizeProviderId(value.provider_id));
          setBaseUrl(value.base_url);
          setModel(value.model);
          drafts.current[normalizeProviderId(value.provider_id)] = {
            base_url: value.base_url,
            model: value.model,
            reasoning_effort: value.reasoning_effort,
            token_limit_field: value.token_limit_field,
          };
          setReasoningEffort(value.reasoning_effort || "default");
          setTokenLimitField(value.token_limit_field || "max_tokens");
          setAllowLocal(value.allow_local);
        }
      })
      .catch((failure) => {
        if (active) setError(failure);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [revision]);
  function chooseProvider(value: AIProviderId) {
    const normalized = normalizeProviderId(value);
    const next = presets.find(
      (item) => normalizeProviderId(item.id) === normalized,
    );
    if (!next || normalized === normalizeProviderId(providerId)) return;
    drafts.current[providerId] = {
      base_url: baseUrl,
      model,
      reasoning_effort: reasoningEffort,
      token_limit_field: tokenLimitField,
    };
    const draft = drafts.current[normalized];
    setProviderId(normalized);
    setBaseUrl(draft?.base_url ?? next.base_url);
    setModel(draft?.model ?? next.models[0] ?? "");
    setReasoningEffort(draft?.reasoning_effort ?? "default");
    setTokenLimitField(draft?.token_limit_field ?? next.token_limit_field);
    setKey("");
    setClearKey(false);
    setSaved(false);
    setDiagnosis(null);
    setDiagnosisError(null);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      const value = await aiApi.configure({
        enabled,
        provider_id: normalizeProviderId(providerId),
        base_url: baseUrl.trim(),
        model: model.trim(),
        reasoning_effort: reasoningEffort,
        token_limit_field: tokenLimitField,
        allow_local: allowLocal,
        ...(key ? { api_key: key } : {}),
        ...(clearKey ? { clear_key: true } : {}),
      });
      setConfig(value);
      setProviderId(normalizeProviderId(value.provider_id));
      setBaseUrl(value.base_url);
      setModel(value.model);
      setReasoningEffort(value.reasoning_effort || "default");
      setTokenLimitField(value.token_limit_field);
      setEnabled(value.enabled);
      setAllowLocal(value.allow_local);
      setKey("");
      setClearKey(false);
      setSaved(true);
    } catch (failure) {
      setError(failure);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function diagnose() {
    if (diagnosisBusy.current) return;
    diagnosisBusy.current = true;
    setDiagnosing(true);
    setDiagnosis(null);
    setDiagnosisError(null);
    try {
      setDiagnosis(
        await aiApi.diagnose({
          provider_id: providerId,
          base_url: baseUrl.trim(),
          allow_local: allowLocal,
        }),
      );
    } catch (failure) {
      setDiagnosisError(failure);
    } finally {
      setDiagnosing(false);
      diagnosisBusy.current = false;
    }
  }
  return (
    <>
      <section className="overview-heading">
        <div>
          <span className="eyebrow">MODEL CONNECTION / 公共接口设置</span>
          <h1>
            连接你选择的模型接口。<span>↗</span>
          </h1>
          <p>
            选择服务商、填写地址和模型，再检查连接。当前支持 Chat Completions
            兼容协议；每次研判前单独审阅摘要。
          </p>
        </div>
        <Plug2 className="ai-connection-mark" size={55} strokeWidth={1} />
      </section>
      {error && (
        <ErrorBox
          retry={() => setRevision((value) => value + 1)}
          requestId={errorRequestId(error)}
        >
          {errorText(error)}
        </ErrorBox>
      )}
      {!config && !error ? (
        <Loading label="正在读取接口设置…" />
      ) : (
        config && (
          <div className="ai-preferences-layout">
            <form
              className="ai-config-form"
              autoComplete="off"
              onChangeCapture={() => setSaved(false)}
              onSubmit={(event) => {
                void save(event);
              }}
            >
              <span className="eyebrow">OPENAI COMPATIBLE / 按需调用</span>
              <h2>AI 接口</h2>
              <label className="field">
                <span className="field-label">AI 提供商预设</span>
                <select
                  aria-label="AI 提供商预设"
                  value={providerId}
                  disabled={busy || diagnosing}
                  onChange={(event) =>
                    chooseProvider(event.target.value as AIProviderId)
                  }
                >
                  {presets.map((preset) => (
                    <option
                      key={preset.id}
                      value={normalizeProviderId(preset.id)}
                    >
                      {preset.label}
                    </option>
                  ))}
                </select>
                <small className="field-hint">
                  切换只更新下方表单，不连接服务商，也不会发送业务证据。
                  {preset?.notes}
                </small>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  aria-label="启用 AI 接口"
                  checked={enabled}
                  disabled={busy}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                <span>
                  启用手动研判
                  <small>开启后仍需逐次确认；保存设置不会调用模型。</small>
                </span>
              </label>
              <label className="field">
                <span className="field-label">兼容接口地址</span>
                <input
                  aria-label="AI 兼容接口地址"
                  type="url"
                  value={baseUrl}
                  required
                  maxLength={500}
                  disabled={busy || diagnosing || providerId === "deepseek"}
                  onChange={(event) => {
                    // An unsaved key belongs to the address it was typed for.
                    setKey("");
                    setBaseUrl(event.target.value);
                  }}
                  placeholder="https://api.openai.com/v1"
                />
                <small className="field-hint">
                  填写服务商文档中的 API Base URL，不要附加
                  /chat/completions。更改地址会清空尚未保存的密钥草稿；提供方会收到你确认发送的摘要。
                </small>
              </label>
              <label className="field">
                <span className="field-label">模型标识</span>
                {Boolean(preset?.models.length) ? (
                  <select
                    aria-label="AI 模型标识"
                    value={model}
                    disabled={busy}
                    onChange={(event) => setModel(event.target.value)}
                  >
                    {model && !preset?.models.includes(model) && (
                      <option value={model}>{model}（已保存）</option>
                    )}
                    {preset?.models.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label="AI 模型标识"
                    value={model}
                    maxLength={100}
                    required={enabled}
                    disabled={busy}
                    onChange={(event) => setModel(event.target.value)}
                    placeholder="填写你的服务商提供的模型标识"
                  />
                )}
              </label>
              <label className="field">
                <span className="field-label">推理强度</span>
                <select
                  aria-label="推理强度"
                  value={reasoningEffort}
                  disabled={busy}
                  onChange={(event) =>
                    setReasoningEffort(
                      event.target.value as AIConfig["reasoning_effort"],
                    )
                  }
                >
                  {(preset?.reasoning_efforts || ["default"]).map((value) => (
                    <option key={value} value={value}>
                      {value === "max" && providerId === "openai_compatible"
                        ? "Ultra"
                        : effortLabels[value]}
                      {value === "default" ? "" : `（${value}）`}
                    </option>
                  ))}
                </select>
                <small className="field-hint">
                  “由模型默认”不发送推理参数，适合不支持该参数的兼容服务。其他值是否可用仍取决于模型。
                </small>
              </label>
              <label className="field">
                <span className="field-label">
                  API 密钥 <small>仅当前后端会话</small>
                </span>
                <input
                  aria-label="AI API 密钥"
                  type="password"
                  value={key}
                  disabled={busy || clearKey}
                  required={enabled && endpointChanged && !clearKey}
                  autoComplete="new-password"
                  onChange={(event) => setKey(event.target.value)}
                  placeholder={
                    endpointChanged
                      ? "为新接口输入密钥"
                      : config.has_key
                        ? "已有密钥；留空保留"
                        : "输入会话密钥"
                  }
                />
                <small className="field-hint">
                  密钥不回显、不写浏览器存储、不写配置文件；后端重启后需重新提供会话密钥。
                </small>
              </label>
              {endpointChanged && (
                <p className="ai-endpoint-warning" role="status">
                  服务商或地址已变化。保存后旧接口的会话密钥会被清除；启用新接口请填写对应密钥。
                </p>
              )}
              <div className="ai-key-state">
                {config.has_key
                  ? `已有密钥 / ${config.credential_source === "environment" ? "服务端环境变量" : "当前后端会话"}`
                  : "尚未配置密钥"}
              </div>
              <label className="checkbox-field">
                <input
                  aria-label="清除会话密钥"
                  type="checkbox"
                  checked={clearKey}
                  disabled={busy}
                  onChange={(event) => {
                    setClearKey(event.target.checked);
                    if (event.target.checked) setKey("");
                  }}
                />
                <span>
                  清除当前会话密钥
                  <small>环境变量由本机服务启动配置管理。</small>
                </span>
              </label>
              <details className="ai-advanced">
                <summary>高级协议与本机接口</summary>
                <label className="field">
                  <span className="field-label">输出预算参数</span>
                  <select
                    aria-label="输出预算参数"
                    value={tokenLimitField}
                    disabled={busy || providerId === "deepseek"}
                    onChange={(event) =>
                      setTokenLimitField(event.target.value as TokenLimitField)
                    }
                  >
                    <option value="max_tokens">
                      max_tokens（通用兼容 / DeepSeek）
                    </option>
                    <option value="max_completion_tokens">
                      max_completion_tokens（OpenAI 推理模型）
                    </option>
                  </select>
                  <small className="field-hint">
                    按服务商文档选择字段；只发送所选的一种，输出预算由服务端限制。
                  </small>
                </label>
                <label className="checkbox-field">
                  <input
                    aria-label="允许本机 AI 接口"
                    type="checkbox"
                    checked={allowLocal}
                    disabled={busy || diagnosing}
                    onChange={(event) => setAllowLocal(event.target.checked)}
                  />
                  <span>
                    允许本机接口地址
                    <small>
                      用于你控制的本机兼容服务或协议验收；这不代表接口可信。
                    </small>
                  </span>
                </label>
              </details>
              {saved && (
                <p className="workspace-success" role="status">
                  <Check size={15} />
                  设置已保存；没有发送检查证据，也没有发起模型调用。
                  {!config.has_key && " 当前没有可用密钥，请补充后再发起研判。"}
                </p>
              )}
              <button
                type="submit"
                className="button button-primary"
                disabled={busy || diagnosing}
              >
                {busy ? "正在保存…" : "保存接口设置"}
                <ArrowRight size={14} />
              </button>
              <div className="ai-diagnosis-block">
                <div className="ai-diagnosis-heading">
                  <div>
                    <span className="eyebrow">
                      01 / CREDENTIAL-FREE CONNECTIVITY
                    </span>
                    <p>
                      检查当前表单地址能否收到 HTTP
                      响应，不保存草稿、不发送密钥或证据、不调用模型；鉴权与模型可用性需要实际请求验证。
                    </p>
                  </div>
                  <button
                    type="button"
                    className="button"
                    disabled={busy || diagnosing || !baseUrl.trim()}
                    onClick={() => {
                      void diagnose();
                    }}
                  >
                    <Stethoscope size={14} />
                    {diagnosing ? "正在诊断…" : "连接诊断"}
                  </button>
                </div>
                {Boolean(diagnosisError) && (
                  <ErrorBox requestId={errorRequestId(diagnosisError)}>
                    {errorText(diagnosisError)}
                  </ErrorBox>
                )}
                {diagnosis && (
                  <div className="ai-diagnosis-result" role="status">
                    <div>
                      <strong>检查地址</strong>
                      <span>{diagnosis.base_url}</span>
                    </div>
                    <div>
                      <strong>网络</strong>
                      <span>{diagnosisValue(diagnosis.network)}</span>
                    </div>
                    <div>
                      <strong>协议</strong>
                      <span>{diagnosisValue(diagnosis.protocol)}</span>
                    </div>
                    <div>
                      <strong>鉴权</strong>
                      <span>{diagnosis.authentication}</span>
                    </div>
                    <div>
                      <strong>模型验证</strong>
                      <span>未调用模型，不代表密钥与模型可用。</span>
                    </div>
                    {diagnosis.limitations?.length ? (
                      <p>{diagnosis.limitations.join("；")}</p>
                    ) : null}
                  </div>
                )}
              </div>
              <SavedModelsDiagnosis
                config={config}
                dirty={dirty}
                blocked={busy || diagnosing}
              />
            </form>
            <aside className="ai-connection-notes">
              <span className="eyebrow">WHAT CONNECTS / 接入范围</span>
              <h3>从 Web 开始，共用同一层。</h3>
              <ul>
                <li>
                  Web：真实网站的已完成检查，可以生成红队人工核查方向与蓝队补强清单。
                </li>
                <li>
                  Android 与云配置：预留公共接口，当前不发送这些模块的证据。
                </li>
                <li>演示与导入：继续保留原有结果，不标成真实 AI 研判。</li>
              </ul>
              <details>
                <summary>数据发送与结果边界</summary>
                <ul>
                  {config.limitations.map((value, index) => (
                    <li key={index}>{value}</li>
                  ))}
                </ul>
              </details>
              <a className="text-button" href="#/">
                返回分析记录 <ArrowRight size={13} />
              </a>
            </aside>
          </div>
        )
      )}
    </>
  );
}
