import { useEffect, useRef, useState } from "react";
import { Check, Code2, Copy } from "lucide-react";
import { api, errorText } from "../../lib/api";
import type { Data, MethodCode } from "../../lib/types";
import { textValue } from "../../lib/types";
import { Empty, ErrorBox, Loading, SearchField } from "../Common";

export function MethodsReader({
  jobId,
  preferredFile,
  preferredRef,
}: {
  jobId: string;
  preferredFile: string;
  preferredRef: string;
}) {
  const [search, setSearch] = useState("");
  const [methods, setMethods] = useState<Data[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState<MethodCode | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [codeLoading, setCodeLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const preference = useRef(preferredRef);
  preference.current = preferredRef;
  const currentSearch = useRef(search);
  currentSearch.current = search;
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      void api
        .methods(jobId, search, 0)
        .then((result) => {
          if (cancelled) return;
          setMethods(result.data);
          setTotal(result.pagination.total);
          const ref =
            preference.current ||
            textValue(result.data[0]?.method_ref) ||
            textValue(result.data[0]?.reference);
          setSelected(ref);
          setOffset(0);
        })
        .catch((failure: unknown) => {
          if (!cancelled) setError(errorText(failure));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId, search]);
  useEffect(() => {
    if (
      preferredRef &&
      preferredRef.startsWith("L") &&
      preferredRef.includes("->")
    ) {
      setSelected(preferredRef);
      setOffset(0);
    } else if (preferredFile && methods.length) {
      const method = methods.find((item) => item.file === preferredFile);
      if (method) {
        setSelected(
          textValue(method.method_ref) || textValue(method.reference),
        );
        setOffset(0);
      } else {
        const file =
          preferredFile.split("/").pop()?.replace(".smali", "") || "";
        setSearch(file);
      }
    }
  }, [preferredFile, preferredRef]);
  useEffect(() => {
    if (!selected) {
      setPage(null);
      return;
    }
    let cancelled = false;
    setCodeLoading(true);
    setError("");
    void api
      .method(jobId, selected, offset)
      .then((result) => {
        if (!cancelled) setPage(result);
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setError(errorText(failure));
          setPage(null);
        }
      })
      .finally(() => {
        if (!cancelled) setCodeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, selected, offset]);
  async function moreMethods() {
    const loadedSearch = search;
    try {
      const result = await api.methods(jobId, search, methods.length);
      if (loadedSearch !== currentSearch.current) return;
      setMethods([...methods, ...result.data]);
      setTotal(result.pagination.total);
    } catch (failure) {
      setError(errorText(failure));
    }
  }
  async function copy() {
    if (!page) return;
    try {
      await navigator.clipboard.writeText(page.data.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("浏览器未允许复制，请直接选择代码文本复制。");
    }
  }
  return (
    <section className="result-section">
      <div className="result-section-heading">
        <div>
          <span className="eyebrow">SOURCE READER</span>
          <h3>方法源码</h3>
        </div>
        <span className="reader-total mono">{total} METHODS</span>
      </div>
      <div className="method-reader">
        <aside>
          <SearchField
            value={search}
            onChange={setSearch}
            label="搜索方法"
            placeholder="搜索类名或方法"
          />
          {loading ? (
            <Loading />
          ) : (
            <>
              <div className="method-list">
                {methods.map((method, index) => {
                  const ref =
                    textValue(method.method_ref) || textValue(method.reference);
                  return (
                    <button
                      key={ref || index}
                      className={selected === ref ? "selected" : ""}
                      onClick={() => {
                        setSelected(ref);
                        setOffset(0);
                      }}
                      title={ref}
                    >
                      <Code2 size={13} />
                      <span>
                        {ref.split("->").pop()}
                        <small>{ref.split(";")[0]?.split("/").pop()}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
              {!methods.length && (
                <p className="inline-empty">没有匹配的方法。</p>
              )}
              {total > methods.length && (
                <button
                  className="text-button load-methods"
                  onClick={() => {
                    void moreMethods();
                  }}
                >
                  加载更多方法 ↓
                </button>
              )}
            </>
          )}
        </aside>
        <div className="code-view">
          <header>
            <span className="mono">SAVED SOURCE / 代码快照</span>
            <button
              onClick={() => {
                void copy();
              }}
              disabled={!page}
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? "已复制" : "复制"}
            </button>
          </header>
          {error && <ErrorBox>{error}</ErrorBox>}
          {codeLoading ? (
            <Loading label="正在读取代码证据…" />
          ) : page ? (
            <>
              <div className="code-path mono">
                {page.data.file}
                <span>
                  L {page.data.start_line} —{" "}
                  {page.data.end_line ??
                    page.data.start_line +
                      page.data.code.split("\n").length -
                      1}
                </span>
              </div>
              <pre>
                <code>
                  {page.data.code.split("\n").map((line, index) => (
                    <span className="code-line" key={index}>
                      <span className="line-number" aria-hidden="true">
                        {page.data.start_line + index}
                      </span>
                      <span>{line || " "}</span>
                    </span>
                  ))}
                </code>
              </pre>
              <footer>
                <span className="mono" title={page.data.sha256}>
                  SHA256 / {page.data.sha256?.slice(0, 16) || "—"}
                </span>
                <div>
                  <button
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 80))}
                  >
                    ← 上一页
                  </button>
                  <button
                    disabled={!page.data.truncated}
                    onClick={() =>
                      setOffset(page.data.next_offset ?? offset + 80)
                    }
                  >
                    下一页 →
                  </button>
                </div>
              </footer>
            </>
          ) : (
            <Empty
              title="选择一个方法"
              detail="从保存的代码快照读取，行号与哈希跟随证据。"
            />
          )}
        </div>
      </div>
    </section>
  );
}
