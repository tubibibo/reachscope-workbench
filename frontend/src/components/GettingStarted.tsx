import { useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Cloud,
  FileSearch,
  GitCompareArrows,
  Globe2,
  Smartphone,
  Server,
} from "lucide-react";
import type { ModuleId } from "../lib/types";

const paths = {
  web: {
    title: "网站",
    icon: Globe2,
    input: "一个你有权检查的完整网址，例如 https://example.com/。",
    scope:
      "只请求你提供的地址，查看 HTTP 响应、TLS 与页面配置。检查前可逐项选择。",
    boundary: "不自动爬站或登录；缺失响应头是待核查配置，不代表已经证实漏洞。",
    after: "完成后打开检查结果，先核对响应与证据，再决定是否手动请求 AI 建议。",
  },
  android: {
    title: "Android 应用",
    icon: Smartphone,
    input: "本机 APK 文件；也可以先用内置合成样例熟悉结果结构。",
    scope:
      "先复核调试、备份、网络安全与入口配置，再按需查看 WebView 和候选代码路径。",
    boundary:
      "不会启动应用。真实 APK 解析需要本机配置 apktool，执行前会检查依赖。",
    after:
      "从配置事实打开证据和修复指引；关联修订 APK 复测后，由你记录结论并关闭案例。",
  },
  cloud: {
    title: "云资产",
    icon: Cloud,
    input: "导出的 AWS 资源配置 JSON，或你有权检查的云服务 HTTP(S) 地址。",
    scope:
      "JSON 离线审查网络、IAM 与存储配置；服务地址只做选定的 Web 外部检查。",
    boundary:
      "不需要云访问密钥，不调用云账号 API；静态配置不证明线上可达或有效权限。",
    after: "核对原始字段和未知条件，保留证据后再创建需要跟进的整改事项。",
  },
  host: {
    title: "主机防御",
    icon: Server,
    input: "本地导出的 SSH / Nginx 配置资料，或服务器访问与认证日志。",
    scope: "离线复核有限配置基线与日志规则，展示输入覆盖、脱敏事件和来源依据。",
    boundary:
      "不登录主机、不持续监控、不自动封禁。未知时间、未解析记录和配置缺口保持可见。",
    after:
      "核对保存证据与人工指引，建立整改事项；配置修订后关联同一主机的新资料复测。",
  },
} as const;

export function GettingStarted({
  start,
  assets,
  records,
  collaboration,
  ai,
}: {
  start: (module: ModuleId) => void;
  assets: () => void;
  records: () => void;
  collaboration: () => void;
  ai: () => void;
}) {
  const [module, setModule] = useState<ModuleId>("web");
  const path = paths[module];
  return (
    <>
      <section className="overview-heading">
        <div>
          <span className="eyebrow">FIELD GUIDE / 从这里开始</span>
          <h1>
            从一个资产，走完一次检查。<span>↗</span>
          </h1>
          <p>
            保存输入、选择检查、核对证据，再跟进整改。基础分析不需要配置 AI。
          </p>
        </div>
        <FileSearch
          className="guide-heading-icon"
          size={54}
          strokeWidth={1}
          aria-hidden="true"
        />
      </section>
      <section className="getting-started" aria-labelledby="guide-title">
        <div className="guide-section-label">
          <span className="eyebrow">01 / CHOOSE YOUR INPUT</span>
          <span>先选你手里的对象</span>
        </div>
        <h2 id="guide-title">这次检查什么？</h2>
        <div className="guide-paths" role="group" aria-label="选择入门资产类型">
          {(Object.keys(paths) as ModuleId[]).map((id) => {
            const Icon = paths[id].icon;
            return (
              <button
                key={id}
                aria-pressed={module === id}
                onClick={() => setModule(id)}
              >
                <Icon size={22} />
                <span>{paths[id].title}</span>
                <ArrowRight size={16} />
              </button>
            );
          })}
        </div>
        <div className="guide-path-detail" aria-live="polite">
          <div>
            <span className="eyebrow">准备输入</span>
            <h3>{path.input}</h3>
            <p>{path.scope}</p>
            <small>{path.boundary}</small>
          </div>
          <button
            className="button button-primary"
            onClick={() => start(module)}
          >
            开始{path.title}检查
            <ArrowRight size={15} />
          </button>
        </div>
      </section>
      <section
        className="guide-workflow"
        aria-labelledby="guide-workflow-title"
      >
        <div className="section-title">
          <div>
            <span className="eyebrow">02 / EVIDENCE TO ACTION</span>
            <h2 id="guide-workflow-title">每一步都有去处</h2>
          </div>
          <span className="guide-local-note">记录保存在本机工作空间</span>
        </div>
        <ol>
          <li>
            <span className="guide-step-number">01</span>
            <div>
              <h3>保存资产与检查项</h3>
              <p>
                四步向导逐项确认输入、检查范围与执行条件。同一个资产后续可以直接复用。
              </p>
              <button className="text-button" onClick={assets}>
                打开我的资产
                <ArrowRight size={13} />
              </button>
            </div>
          </li>
          <li>
            <span className="guide-step-number">02</span>
            <div>
              <h3>核对原始证据</h3>
              <p>{path.after} 未知、采集失败和未执行的检查会单独保留。</p>
              <button className="text-button" onClick={records}>
                查看分析记录
                <ArrowRight size={13} />
              </button>
            </div>
          </li>
          <li>
            <span className="guide-step-number">03</span>
            <div>
              <h3>建立验证与整改事项</h3>
              <p>
                为已有资产创建工作组，从保存的观察项建立事项，再分配负责人、日期与处理结论。
              </p>
              <button className="text-button" onClick={collaboration}>
                打开验证与整改
                <GitCompareArrows size={13} />
              </button>
            </div>
          </li>
          <li>
            <span className="guide-step-number">04</span>
            <div>
              <h3>修复后复测</h3>
              <p>
                用可比较的新检查验证变化，补充人工说明后关闭事项。检查失败或缺少结果不能视为修复成功。
              </p>
              <span className="guide-verification">
                <CheckCircle2 size={13} />
                保留原始记录与决策历史
              </span>
            </div>
          </li>
        </ol>
      </section>
      <div className="guide-bottom-grid">
        <section className="guide-source-note">
          <span className="eyebrow">READ THE LABEL / 识别结果来源</span>
          <h3>先看来源，再看结论。</h3>
          <dl>
            <div>
              <dt>网络采集</dt>
              <dd>本次请求取得的响应，不等同于已证实漏洞。</dd>
            </div>
            <div>
              <dt>本机文件 / 导入</dt>
              <dd>静态文件或已有结果，不能替代当前线上验证。</dd>
            </div>
            <div>
              <dt>合成演示</dt>
              <dd>内置练习数据，不代表真实资产和实际检测能力。</dd>
            </div>
          </dl>
        </section>
        <section className="guide-ai-note">
          <span className="eyebrow">OPTIONAL / 按需接入</span>
          <h3>先有证据，再请 AI 排优先级。</h3>
          <p>
            当前只支持真实网站的已完成检查。每次调用前可预览摘要并确认；建议不能自动执行测试、修改配置或关闭事项。
          </p>
          <button className="text-button" onClick={ai}>
            配置模型接口
            <ArrowRight size={13} />
          </button>
        </section>
      </div>
    </>
  );
}
