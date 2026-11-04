import { isRecord, textValue } from "../../lib/types";

const states: Record<string, { label: string; next: string }> = {
  collected: {
    label: "资料已导出",
    next: "仍需核对主机、采集上下文和规则适用性；导出成功不等于配置安全或运行中已生效。",
  },
  unavailable: {
    label: "命令不可用",
    next: "确认对应软件是否安装、当前账户是否有只读采集条件，再在你管理的环境中重新导出。",
  },
  failed: {
    label: "采集失败",
    next: "先在目标主机核对命令退出状态、软件配置和读取权限；不要把缺失资料当作安全结果。",
  },
  timeout: {
    label: "采集超时",
    next: "检查目标主机负载和命令响应，保留此次失败记录；补齐新的完整资料后再分析。",
  },
  budget_exceeded: {
    label: "触及采集预算",
    next: "当前投影不完整。核对导出范围与预算限制，不能从截断结果认定整改完成。",
  },
  unsupported: {
    label: "投影暂不支持",
    next: "保留未知项，使用受支持的导出方式补充对应范围；不要手工填入安全值来消除未知。",
  },
};

export function HostCollection({ value }: { value: unknown }) {
  if (!isRecord(value))
    return (
      <p className="host-note">
        此资料没有 v2
        采集器元数据。旧格式检查能力保留，不补记采集成功；跨采集格式或投影版本需建立对应的新基线。
      </p>
    );
  const components = isRecord(value.components) ? value.components : {};
  return (
    <section className="host-collection" aria-label="采集资料状态">
      <h4>先处理采集缺口，再判断配置</h4>
      <p className="host-note">
        格式 v{textValue(String(value.format_version || "未知"))} · 采集器{" "}
        {textValue(value.version) || "版本未知"} · 最小投影{" "}
        <code>{textValue(value.projection) || "未知"}</code>
        。这些元数据随文件提供，未独立认证采集过程、主机身份或当前运行状态；本页面不会启动采集器。
      </p>
      <div className="host-collection-grid">
        {["ssh", "nginx"].map((key) => {
          const component = isRecord(components[key]) ? components[key] : {};
          const state = textValue(component.state),
            copy = Object.hasOwn(states, state) ? states[state] : null;
          return (
            <article key={key} data-collector-component={key}>
              <header>
                <strong>{key === "ssh" ? "SSH 资料" : "Nginx 资料"}</strong>
                <span
                  className={`check-state ${state === "collected" ? "check-info" : "check-unknown"}`}
                >
                  {copy?.label || "采集状态未知"}
                </span>
              </header>
              <p>
                {copy?.next ||
                  "没有可解释的采集状态。先核对导出文件和执行计划，未提供的字段仍保持未知。"}
              </p>
              <dl>
                <div>
                  <dt>完整性声明</dt>
                  <dd>
                    {component.complete === true
                      ? "输入声明完整"
                      : component.complete === false
                        ? "存在采集或投影缺口"
                        : "未记录"}
                  </dd>
                </div>
                <div>
                  <dt>命令退出码</dt>
                  <dd>
                    {typeof component.exit_code === "number" &&
                    Number.isInteger(component.exit_code)
                      ? component.exit_code
                      : "未记录"}
                  </dd>
                </div>
              </dl>
            </article>
          );
        })}
      </div>
      <p className="host-note">
        只投影允许的配置字段，采集器会省略未支持内容；省略不代表目标没有该配置。失败组件保持未知。v1
        原始配置与 v2 最小投影的范围不同，不能直接冒充可比整改前后资料。
      </p>
    </section>
  );
}
