import { Download, FileCode2 } from "lucide-react";

export function HostPreparation() {
  return (
    <section className="host-preparation" aria-label="准备主机配置资料">
      <span className="eyebrow">PREPARE / LOCAL EXPORT</span>
      <h4>在你管理的 Linux 主机上，先审阅再导出</h4>
      <p>
        采集器默认只显示执行计划。你核对计划后，才能用明确的参数导出最小配置资料；页面不会运行下载文件、登录主机或上传导出结果。
      </p>
      <div className="host-downloads">
        <a
          className="button button-outline"
          href="/api/host/collector"
          download="reachscope-host-collector.pyz"
        >
          <Download size={14} />
          下载只读采集器
        </a>
        <a
          className="text-button"
          href="/api/host/collector/source"
          download="reachscope-host-collector-source.zip"
        >
          <FileCode2 size={14} />
          下载源码审阅
        </a>
        <a
          className="text-button"
          href="/api/host/template"
          download="reachscope-host-template.json"
        >
          使用 v1 格式模板 ↗
        </a>
      </div>
      <ol className="host-preparation-steps">
        <li>
          <strong>先看计划</strong>
          <p>
            在你管理的主机上运行{" "}
            <code>
              python3 reachscope-host-collector.pyz --host-id srv-web-01
              --ssh-context global --output snapshot.json
            </code>
            ，核对本机命令、读取范围、输出位置和计划摘要。
          </p>
        </li>
        <li>
          <strong>确认后导出</strong>
          <p>
            示例中的 <code>srv-web-01</code>{" "}
            应与你填写的主机标识一致；用计划中的摘要替换{" "}
            <code>PLAN_SHA256</code>，再手动运行：
          </p>
          <pre>
            python3 reachscope-host-collector.pyz --host-id srv-web-01
            --ssh-context global --collect --plan-sha256 PLAN_SHA256 --output
            snapshot.json
          </pre>
        </li>
        <li>
          <strong>预览后再上传</strong>
          <p>
            先检查导出文件和失败状态，再选择下方文件。采集器不自动提权、上传、修改配置或重启服务。
          </p>
        </li>
      </ol>
      <p className="host-note">
        SSH 当前只支持声明的 global 上下文；它不能覆盖所有 Match
        条件。主机标识与采集时间仍需你核对，不能作为已认证身份或配置已在运行中生效的证明。
      </p>
    </section>
  );
}
