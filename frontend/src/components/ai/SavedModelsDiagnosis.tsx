import { useEffect, useRef, useState } from "react";
import { ListChecks } from "lucide-react";
import { aiApi } from "../../ai/api";
import { errorRequestId, errorText } from "../../lib/api";
import type { AIConfig, ModelDiagnosis } from "../../ai/types";
import { ErrorBox } from "../Common";

export function SavedModelsDiagnosis({
  config,
  dirty,
  blocked,
}: {
  config: AIConfig;
  dirty: boolean;
  blocked: boolean;
}) {
  const [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<ModelDiagnosis | null>(null),
    [error, setError] = useState<unknown>(null);
  const running = useRef(false);
  const currentConfiguration = useRef(config.configuration_sha256);
  currentConfiguration.current = config.configuration_sha256;
  useEffect(() => {
    setConsent(false);
    setResult(null);
    setError(null);
  }, [config.configuration_sha256]);
  async function diagnose() {
    if (running.current || !consent || dirty) return;
    running.current = true;
    setBusy(true);
    setResult(null);
    setError(null);
    const revision = config.configuration_sha256;
    try {
      const value = await aiApi.diagnoseModels(revision);
      if (currentConfiguration.current === revision) setResult(value);
    } catch (failure) {
      if (currentConfiguration.current === revision) setError(failure);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="ai-model-diagnosis"
      aria-label="已保存凭据与模型目录诊断"
    >
      <span className="eyebrow">02 / AUTHENTICATION & MODEL DIRECTORY</span>
      <h3>验证已保存凭据与模型目录</h3>
      <p>
        只向已保存的服务地址发送认证信息并读取模型目录，不发送检查证据、不发起模型推理。目录可见与模型实际可用是不同的验证阶段。
      </p>
      <code>
        {config.base_url} · {config.model || "尚未填写模型"}
      </code>
      {dirty && (
        <p className="ai-endpoint-warning">
          表单存在未保存修改。请先保存，再确认对这份配置使用凭据。
        </p>
      )}
      <label className="checkbox-field">
        <input
          type="checkbox"
          aria-label="同意验证已保存凭据与模型目录"
          checked={consent}
          disabled={busy || blocked || dirty || !config.has_key}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <span>
          同意仅向已保存地址发送凭据，读取模型目录
          <small>这一步不会生成研判报告，也不验证推理能力。</small>
        </span>
      </label>
      <button
        type="button"
        className="button"
        disabled={
          busy ||
          blocked ||
          dirty ||
          !config.has_key ||
          !config.configuration_sha256 ||
          !consent
        }
        onClick={() => void diagnose()}
      >
        <ListChecks size={14} />
        {busy ? "正在读取模型目录…" : "验证已保存凭据与模型目录"}
      </button>
      {Boolean(error) && (
        <ErrorBox requestId={errorRequestId(error)}>
          {errorText(error)}
        </ErrorBox>
      )}
      {result && (
        <div className="ai-diagnosis-result" role="status">
          <div>
            <strong>检查地址</strong>
            <span>{result.base_url}</span>
          </div>
          <div>
            <strong>认证</strong>
            <span>
              {result.authentication === "accepted"
                ? "目录接口接受了凭据"
                : result.authentication === "rejected"
                  ? "目录接口拒绝了凭据"
                  : "无法判断认证结果"}
            </span>
          </div>
          <div>
            <strong>指定模型</strong>
            <span>
              {result.model} /{" "}
              {result.model_available === true
                ? "目录中可见"
                : result.model_available === false
                  ? "目录中未找到"
                  : "未能验证"}
            </span>
          </div>
          <div>
            <strong>实际推理</strong>
            <span>未发起，未验证</span>
          </div>
          <p>{result.message}</p>
          {result.limitations.map((value) => (
            <p key={value}>{value}</p>
          ))}
        </div>
      )}
      <div className="ai-inference-next">
        <span className="eyebrow">03 / EXPLICIT INFERENCE</span>
        <p>
          真正生成红蓝研判请回到已完成的网站检查，在「AI
          研判」页审阅摘要并逐次授权。该操作可能产生服务商推理费用，不会由诊断自动触发。
        </p>
        <a className="text-button" href="#/">
          前往分析记录 ↗
        </a>
      </div>
    </section>
  );
}
