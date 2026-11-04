import { useState } from "react";
import type { Data, ModuleResult } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { SearchField } from "../Common";

function exportedState(item: Data): "yes" | "no" | "unknown" {
  const value = Object.hasOwn(item, "effective_exported")
    ? item.effective_exported
    : item.exported;
  return value === true ? "yes" : value === false ? "no" : "unknown";
}

export function AndroidInventory({ result }: { result: ModuleResult }) {
  const [componentSearch, setComponentSearch] = useState("");
  const [exportFilter, setExportFilter] = useState("all");
  const [linkSearch, setLinkSearch] = useState("");
  const [permissionSearch, setPermissionSearch] = useState("");
  const components = records(result.details.components);
  const deeplinks = records(result.details.deeplinks);
  const requested = strings(result.details.permissions);
  const declared = isRecord(result.details.declared_permissions)
    ? result.details.declared_permissions
    : {};
  const matches = components.filter(
    (item) =>
      (exportFilter === "all" || exportedState(item) === exportFilter) &&
      [
        item.name,
        item.type,
        item.component_type,
        item.permission,
        item.inherited_permission,
      ].some((value) =>
        textValue(value).toLowerCase().includes(componentSearch.toLowerCase()),
      ),
  );
  const links = deeplinks.filter((item) =>
    [item.component, item.scheme, item.host, item.path].some((value) =>
      textValue(value).toLowerCase().includes(linkSearch.toLowerCase()),
    ),
  );
  const permissions = requested.filter((permission) =>
    permission.toLowerCase().includes(permissionSearch.toLowerCase()),
  );
  const customPermissions = Object.entries(declared).filter(([name]) =>
    name.toLowerCase().includes(permissionSearch.toLowerCase()),
  );
  const limits = isRecord(result.details.limits) ? result.details.limits : null;
  const totalComponents =
    result.details.components_total ?? limits?.components_total;
  return (
    <>
      <section
        className="result-section android-inventory"
        id="android-entries"
        tabIndex={-1}
      >
        <div className="result-section-heading">
          <div>
            <span className="eyebrow">MANIFEST / ENTRY POINTS</span>
            <h3>
              组件与入口 <span>{components.length}</span>
            </h3>
          </div>
        </div>
        <p className="android-note">
          导出状态优先使用 targetSdk
          和声明条件推导的有效配置；权限声明与实现可见性不代表调用已获授权或接口可利用。
        </p>
        <div className="android-toolbar">
          <SearchField
            value={componentSearch}
            onChange={setComponentSearch}
            label="搜索组件"
            placeholder="组件、类型或权限"
          />
          <label className="android-select-label">
            导出状态
            <select
              aria-label="筛选安卓组件导出状态"
              value={exportFilter}
              onChange={(event) => setExportFilter(event.target.value)}
            >
              <option value="all">全部组件</option>
              <option value="yes">已导出</option>
              <option value="no">未导出</option>
              <option value="unknown">信息不足</option>
            </select>
          </label>
          <span className="android-result-count" role="status">
            显示 {matches.length} / {components.length} 项
          </span>
        </div>
        {matches.length ? (
          <div className="table-scroll">
            <table className="android-components-table">
              <thead>
                <tr>
                  <th>组件 / 类型</th>
                  <th>导出配置与依据</th>
                  <th>配置权限</th>
                  <th>实现可见性</th>
                </tr>
              </thead>
              <tbody>
                {matches.map((item, index) => {
                  const exported = exportedState(item);
                  const permission = Object.hasOwn(item, "effective_permission")
                    ? textValue(item.effective_permission)
                    : textValue(item.permission) ||
                      textValue(item.inherited_permission);
                  return (
                    <tr key={textValue(item.id) || index}>
                      <td className="component-name">
                        <code>{readable(item.name)}</code>
                        <small>
                          {readable(item.type || item.component_type)}
                        </small>
                      </td>
                      <td>
                        <span
                          className={`android-state android-state-${exported === "yes" ? "review" : exported === "no" ? "pass" : "unknown"}`}
                        >
                          {exported === "yes"
                            ? "已导出"
                            : exported === "no"
                              ? "未导出"
                              : "信息不足"}
                        </span>
                        <small>
                          {textValue(item.export_reason) ||
                            (item.exported_inferred === true
                              ? "依据清单默认行为推导；历史引擎结果"
                              : "依据保存的清单配置")}
                        </small>
                      </td>
                      <td>
                        <code>{permission || "未声明组件或继承权限"}</code>
                        {textValue(item.permission_protection) && (
                          <small>
                            声明保护级别：
                            {textValue(item.permission_protection)}
                          </small>
                        )}
                        {Object.hasOwn(item, "read_permission") &&
                          item.type === "provider" && (
                            <small>
                              读权限：
                              {textValue(item.read_permission) || "无声明权限"}
                              ； 写权限：
                              {textValue(item.write_permission) || "无声明权限"}
                            </small>
                          )}
                        {typeof item.path_permissions === "number" &&
                          item.type === "provider" && (
                            <small>
                              路径权限声明 {item.path_permissions} 项； URI
                              临时授权：
                              {item.grant_uri_permissions === true
                                ? "已声明"
                                : item.grant_uri_permissions === false
                                  ? "未声明"
                                  : "未知"}
                            </small>
                          )}
                      </td>
                      <td>
                        {item.impl_present === true
                          ? "索引内可见"
                          : item.impl_present === false
                            ? "索引内未找到"
                            : "未评估"}
                        <small>{textValue(item.impl_reason)}</small>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="inline-empty">
            {components.length
              ? "没有符合条件的组件。"
              : "本次结果未返回组件，请核对输入和解析范围。"}
          </p>
        )}
        {typeof totalComponents === "number" &&
          totalComponents > components.length && (
            <p className="android-coverage-warning">
              共记录 {totalComponents} 个组件，本页保存 {components.length}{" "}
              个；其余组件未在此列表内展示。
            </p>
          )}
      </section>
      <section
        className="result-section android-inventory"
        aria-label="安卓深链声明"
      >
        <div className="result-section-heading">
          <div>
            <span className="eyebrow">DECLARED / DEEP LINKS</span>
            <h3>
              深链声明 <span>{deeplinks.length}</span>
            </h3>
          </div>
          <SearchField
            value={linkSearch}
            onChange={setLinkSearch}
            label="搜索安卓深链"
            placeholder="协议、主机、路径或组件"
          />
        </div>
        <p className="android-note">
          autoVerify 只表示清单请求域名验证，未验证服务器的 Digital Asset Links
          或设备实际关联。路径模式保留声明文本，不作为已访问地址。
        </p>
        {links.length ? (
          <div className="table-scroll">
            <table className="android-deeplinks-table">
              <thead>
                <tr>
                  <th>协议 / 主机</th>
                  <th>路径声明</th>
                  <th>接收组件</th>
                  <th>autoVerify</th>
                </tr>
              </thead>
              <tbody>
                {links.map((item, index) => (
                  <tr key={textValue(item.id) || index}>
                    <td>
                      <code>{textValue(item.scheme) || "未知协议"}</code>
                      <small className="mono">
                        {textValue(item.host) || "未声明主机"}
                      </small>
                    </td>
                    <td>
                      <code>{textValue(item.path) || "未声明路径限制"}</code>
                    </td>
                    <td>
                      <code>{readable(item.component)}</code>
                    </td>
                    <td>
                      {item.auto_verify === true
                        ? "声明请求验证"
                        : item.auto_verify === false
                          ? "未声明"
                          : "未知"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="inline-empty">
            {deeplinks.length
              ? "没有匹配的深链声明。"
              : "返回结果中没有深链声明；未返回不证明应用没有其他入口。"}
          </p>
        )}
      </section>
      <section
        className="result-section android-inventory"
        id="android-permissions"
        tabIndex={-1}
      >
        <div className="result-section-heading">
          <div>
            <span className="eyebrow">DECLARED / PERMISSIONS</span>
            <h3>
              权限清单 <span>{requested.length}</span>
            </h3>
          </div>
          <SearchField
            value={permissionSearch}
            onChange={setPermissionSearch}
            label="搜索安卓权限"
            placeholder="权限名称"
          />
        </div>
        <p className="android-note">
          请求权限仅表示清单声明；不证明用户已授予、系统当前允许或应用实际使用。自定义权限保护级别需结合签名和调用场景复核。
        </p>
        <h4 className="android-subheading">应用请求的权限</h4>
        {permissions.length ? (
          <div className="permission-list">
            {permissions.map((permission) => (
              <code key={permission}>{permission}</code>
            ))}
          </div>
        ) : (
          <p className="inline-empty">
            {requested.length
              ? "没有匹配的请求权限。"
              : "本次未返回请求权限；请结合清单证据确认。"}
          </p>
        )}
        {(Object.keys(declared).length > 0 || permissionSearch) && (
          <>
            <h4 className="android-subheading">应用定义的权限</h4>
            {customPermissions.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>权限名</th>
                      <th>声明保护级别</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customPermissions.map(([name, value]) => (
                      <tr key={name}>
                        <td>
                          <code>{name}</code>
                        </td>
                        <td>{readable(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="inline-empty">没有匹配的自定义权限。</p>
            )}
          </>
        )}
      </section>
    </>
  );
}
