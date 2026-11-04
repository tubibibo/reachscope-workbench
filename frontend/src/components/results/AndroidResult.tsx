import { useState } from "react";
import { ArrowDown, Code2, FileSearch } from "lucide-react";
import type { Job, ModuleResult } from "../../lib/types";
import {
  isRecord,
  readable,
  records,
  strings,
  textValue,
} from "../../lib/types";
import { Observations } from "./Observations";
import { AndroidBrief, AndroidReview } from "./AndroidReview";
import { AndroidInventory } from "./AndroidInventory";
import "./android-results.css";
import { MethodsReader } from "./MethodsReader";

export function AndroidResult({
  job,
  result,
  onEvidence,
}: {
  job: Job;
  result: ModuleResult;
  onEvidence: (id: string) => void;
}) {
  const chains = records(result.details.chains);
  const [chainIndex, setChainIndex] = useState(0);
  const [stepIndex, setStepIndex] = useState(0);
  const chain = chains[chainIndex];
  const steps = chain ? records(chain.steps) : [];
  const selectedStep = steps[stepIndex];
  const source =
    selectedStep && isRecord(selectedStep.source) ? selectedStep.source : null;
  return (
    <>
      <AndroidBrief job={job} result={result} />
      <nav className="android-section-nav" aria-label="安卓结果导航">
        {(
          [
            ["android-configuration", "配置复核"],
            ["android-entries", "组件与深链"],
            ["android-permissions", "权限清单"],
            ["android-code", "代码证据"],
          ] as const
        ).map(([id, label]) => (
          <button
            type="button"
            key={id}
            onClick={() => {
              const section = document.getElementById(id);
              section?.scrollIntoView({ behavior: "instant", block: "start" });
              section?.focus({ preventScroll: true });
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <AndroidReview result={result} onEvidence={onEvidence} />
      <AndroidInventory result={result} />
      <div id="android-code" tabIndex={-1}>
        {Boolean(result.details.artifact_id) ? (
          <>
            <section className="result-section">
              <div className="result-section-heading">
                <div>
                  <span className="eyebrow">CANDIDATE CODE PATHS</span>
                  <h3>
                    代码路径 <span>{chains.length}</span>
                  </h3>
                </div>
                <span className="subtle-tag">静态推断</span>
              </div>
              {!chains.length ? (
                <div className="path-empty">
                  <FileSearch size={26} />
                  <div>
                    <h4>本次分析没有建立候选路径</h4>
                    <p>
                      仍可在下方检查组件、可见方法和原始证据。分析未找到不代表实际不可达。
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="chain-tabs">
                    {chains.map((item, index) => (
                      <button
                        key={textValue(item.id) || index}
                        aria-pressed={index === chainIndex}
                        onClick={() => {
                          setChainIndex(index);
                          setStepIndex(0);
                        }}
                      >
                        路径 {String(index + 1).padStart(2, "0")}
                        <small>{records(item.steps).length} steps</small>
                      </button>
                    ))}
                  </div>
                  <div className="path-reader">
                    <div className="path-steps">
                      {chain && (
                        <p className="path-entry mono">
                          {strings(chain.entries).join(" → ") ||
                            readable(chain.entry)}
                        </p>
                      )}
                      {steps.map((step, index) => (
                        <div key={index}>
                          <button
                            className={index === stepIndex ? "selected" : ""}
                            onClick={() => setStepIndex(index)}
                            aria-current={
                              index === stepIndex ? "step" : undefined
                            }
                          >
                            <span className="step-number mono">
                              {String(index + 1).padStart(2, "0")}
                            </span>
                            <span>
                              <strong>
                                {readable(step.sink || step.kind || step.label)}
                              </strong>
                              <small>{readable(step.description)}</small>
                            </span>
                            <Code2 size={14} />
                          </button>
                          {index < steps.length - 1 && (
                            <ArrowDown size={13} className="step-connector" />
                          )}
                        </div>
                      ))}
                      {chain && (
                        <div className="chain-id mono">
                          CHAIN / {readable(chain.id)}
                        </div>
                      )}
                    </div>
                    <div className="step-evidence">
                      <span className="eyebrow">SELECTED STEP</span>
                      <h4>
                        {selectedStep
                          ? readable(selectedStep.sink || selectedStep.label)
                          : "选择一个步骤"}
                      </h4>
                      {source && (
                        <>
                          <div className="source-location mono">
                            {readable(source.file)}:{readable(source.line)}
                          </div>
                          <pre>{readable(source.snippet)}</pre>
                        </>
                      )}
                      {selectedStep && (
                        <p>{readable(selectedStep.description)}</p>
                      )}
                      <span className="scope-note">
                        这是代码层候选关系。执行条件与风险判据需单独核对。
                      </span>
                    </div>
                  </div>
                </>
              )}
            </section>
            <MethodsReader
              jobId={job.id}
              preferredFile={textValue(source?.file)}
              preferredRef={
                textValue(selectedStep?.method_ref) ||
                textValue(selectedStep?.from)
              }
            />
          </>
        ) : (
          <p className="scope-note">
            本次仅检查清单，未执行代码路径分析与方法源码索引。
          </p>
        )}
      </div>
      <Observations
        observations={result.observations}
        onEvidence={onEvidence}
      />
    </>
  );
}
