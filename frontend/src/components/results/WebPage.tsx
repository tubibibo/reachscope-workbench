import { useState } from "react";
import { ArrowRight, FileCode2 } from "lucide-react";
import type { Data } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { KeyValues } from "../Common";
import { JsonData } from "./JsonData";

export function WebPages({
  assets,
  onEvidence,
}: {
  assets: Data[];
  onEvidence: (id: string) => void;
}) {
  const [selected, setSelected] = useState("");
  const available = assets.filter((asset) => isRecord(asset.page));
  const asset = available.find((item) => item.id === selected) || available[0];
  return (
    <section className="result-section web-pages">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">PAGE INVENTORY</span>
          <h3>
            页面画像 <span>{available.length}</span>
          </h3>
        </div>
        <FileCode2 size={22} className="web-section-icon" />
      </div>
      <p className="section-description">
        从已经采集的正文整理表单和资源，不执行脚本，不跟随页面链接，也不提交表单。
      </p>
      {available.length ? (
        <>
          <div className="web-filter-bar">
            <label>
              选择资产
              <select
                aria-label="选择画像资产"
                value={textValue(asset?.id)}
                onChange={(event) => setSelected(event.target.value)}
              >
                {available.map((item) => (
                  <option key={textValue(item.id)} value={textValue(item.id)}>
                    {readable(item.url || item.host)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {asset && (
            <>
              <PageProfile asset={asset} />
              {strings(asset.evidence_ids).map((id) => (
                <button
                  key={id}
                  className="text-button"
                  onClick={() => onEvidence(id)}
                >
                  查看响应证据 <ArrowRight size={12} />
                </button>
              ))}
            </>
          )}
        </>
      ) : (
        <p className="inline-empty">
          此记录没有页面画像。请运行 HTTP
          探测；旧版记录和导入文件不会被当作本次采集的页面。
        </p>
      )}
    </section>
  );
}

export function PageProfile({ asset }: { asset: Data }) {
  const page = isRecord(asset.page) ? asset.page : null;
  const cookies = records(asset.cookies);
  const [resourceTab, setResourceTab] = useState("scripts");
  const resourceLabels: Record<string, string> = {
    scripts: "脚本",
    stylesheets: "样式",
    images: "图片",
    links: "链接",
  };
  const resources = page ? records(page[resourceTab]) : [];
  const counts = page && isRecord(page.counts) ? page.counts : {};
  return (
    <div className="page-profile">
      {page?.analyzed ? (
        <>
          <div className="page-counts">
            {[
              ["forms", "表单"],
              ["scripts", "脚本"],
              ["stylesheets", "样式"],
              ["images", "图片"],
              ["links", "链接"],
            ].map(([key, label]) => (
              <div key={key}>
                <strong>{readable(counts[key || ""])}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>
          <div className="page-signals" aria-label="页面线索统计">
            <span>
              密码字段 <strong>{readable(counts.password_fields)}</strong>
            </span>
            <span>
              跨源脚本 <strong>{readable(counts.external_scripts)}</strong>
            </span>
            <span>
              混合内容 <strong>{readable(counts.mixed_content)}</strong>
            </span>
          </div>
          <KeyValues
            data={{
              语言: page.language || "未声明",
              页面描述: page.description || "未声明",
              规范地址: page.canonical || "未声明",
            }}
          />
          {Boolean(page.truncated || asset.body_truncated) && (
            <p className="scope-note">
              正文或条目达到采集上限，以下是已采集范围内的画像。
            </p>
          )}
          <div className="profile-block">
            <h4>表单与输入</h4>
            {records(page.forms).length ? (
              records(page.forms).map((form, index) => (
                <div className="form-profile" key={index}>
                  <span className="mono">
                    FORM {String(index + 1).padStart(2, "0")}
                  </span>
                  <strong>
                    <span className="http-status">{readable(form.method)}</span>{" "}
                    {readable(form.action)}
                  </strong>
                  <p>
                    密码字段 {readable(form.password_fields)} · 字段名{" "}
                    {strings(form.input_names).join("、") || "未记录"}
                  </p>
                  {(Boolean(form.external) || Boolean(form.mixed_content)) && (
                    <div className="form-signals">
                      {Boolean(form.external) && (
                        <span className="check-state">跨源提交地址</span>
                      )}
                      {Boolean(form.mixed_content) && (
                        <span className="check-state check-review">
                          HTTP 提交地址
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="inline-empty">已采集正文中没有发现表单。</p>
            )}
          </div>
          <div className="profile-block">
            <h4>页面资源</h4>
            <div className="web-inline-tabs">
              {Object.entries(resourceLabels).map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={resourceTab === key}
                  onClick={() => setResourceTab(key)}
                >
                  {label} <span>{records(page[key]).length}</span>
                </button>
              ))}
            </div>
            {resources.length ? (
              <ul className="resource-list">
                {resources.map((resource, index) => (
                  <li key={index}>
                    <code>{readable(resource.url)}</code>
                    <span>{resource.external ? "跨源" : "同源"}</span>
                    {Boolean(resource.mixed_content) && (
                      <span className="check-state check-review">混合内容</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="inline-empty">
                未记录这一类 URL；内联代码不作为外部资源展示。
              </p>
            )}
          </div>
        </>
      ) : (
        <p className="inline-empty">
          {page
            ? readable(page.reason || "该响应未解析为 HTML 页面。")
            : "此记录没有页面画像。"}
        </p>
      )}
      <div className="profile-block">
        <h4>
          Cookie 属性 <span>{cookies.length}</span>
        </h4>
        <p className="section-description">
          仅记录 Set-Cookie 的名称与属性，Cookie 值不保存。
        </p>
        {cookies.length ? (
          <div className="table-scroll">
            <table className="cookie-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>Secure</th>
                  <th>HttpOnly</th>
                  <th>SameSite</th>
                  <th>范围</th>
                </tr>
              </thead>
              <tbody>
                {cookies.map((cookie, index) => (
                  <tr key={index}>
                    <td className="mono">
                      {readable(cookie.name)}
                      {Boolean(cookie.partitioned || cookie.prefix) && (
                        <small>
                          {[
                            cookie.partitioned ? "Partitioned" : "",
                            textValue(cookie.prefix),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      )}
                    </td>
                    <td>{cookie.secure ? "是" : "未声明"}</td>
                    <td>
                      {cookie.http_only || cookie.httponly ? "是" : "未声明"}
                    </td>
                    <td>
                      {readable(
                        cookie.same_site || cookie.samesite || "未声明",
                      )}
                    </td>
                    <td>
                      {readable(cookie.domain || "当前主机")}
                      <small>{readable(cookie.path || "默认路径")}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="inline-empty">该响应没有记录 Cookie 属性。</p>
        )}
      </div>
      {page && (
        <details className="raw-record">
          <summary>查看画像采集信息</summary>
          <JsonData data={page} />
        </details>
      )}
    </div>
  );
}
