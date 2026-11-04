import {
  AlertCircle,
  ArrowUpRight,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Data, Job, Status } from "../lib/types";
import { readable, statusLabel } from "../lib/types";

export function StatusTag({ status }: { status: Status }) {
  return (
    <span className={`status-tag status-${status}`}>
      <i />
      {statusLabel[status]}
    </span>
  );
}
export function ErrorBox({
  children,
  retry,
  requestId,
}: {
  children: ReactNode;
  retry?: () => void;
  requestId?: string;
}) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={16} />
      <div className="error-message">
        {children}
        {requestId && (
          <details className="error-reference">
            <summary>查看操作编号</summary>
            <code>{requestId}</code>
          </details>
        )}
      </div>
      {retry && <button onClick={retry}>重试 ↗</button>}
    </div>
  );
}
export function Loading({ label = "正在读取…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={18} className="spin" />
      {label}
    </div>
  );
}
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-mark">↗</span>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
export function SectionTitle({
  label,
  title,
  trailing,
}: {
  label: string;
  title: string;
  trailing?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <span className="eyebrow">{label}</span>
        <h2>{title}</h2>
      </div>
      {trailing}
    </div>
  );
}
export function SearchField({
  value,
  onChange,
  placeholder = "搜索",
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label: string;
}) {
  return (
    <label className="search-field">
      <Search size={15} />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="清除搜索"
        >
          <X size={13} />
        </button>
      )}
    </label>
  );
}
export function KeyValues({ data }: { data: Data }) {
  return (
    <dl className="key-values">
      {Object.entries(data).map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{readable(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
export function ProgressBar({ job }: { job: Job }) {
  return (
    <div className="job-progress">
      <div className="progress-caption">
        <span>{job.message || statusLabel[job.status]}</span>
        <strong>{Math.min(100, Math.max(0, Math.round(job.progress)))}%</strong>
      </div>
      <div className="progress-track">
        <span
          style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }}
        />
      </div>
    </div>
  );
}
export function LinkButton({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a className="button button-secondary" href={href} download>
      {children}
      <ArrowUpRight size={14} />
    </a>
  );
}
