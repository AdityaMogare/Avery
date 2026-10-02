import { useMemo, useState } from "react";
import { EvalResult, Scenario } from "./api";

type Filter = "all" | "core" | "edge";

export function TestCaseDrawer({
  scenarios,
  results,
  onRun,
  onStep,
  onClose,
}: {
  scenarios: Scenario[];
  results: Record<string, EvalResult>;
  onRun: (s: Scenario) => void;
  onStep: (s: Scenario) => void;
  onClose: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return scenarios.filter((s) => {
      const edge = s.category === "edge_case";
      if (filter === "core" && edge) return false;
      if (filter === "edge" && !edge) return false;
      if (!q) return true;
      return [s.id, s.description, s.gate ?? "", s.source ?? "", ...s.turns].join(" ").toLowerCase().includes(q);
    });
  }, [scenarios, filter, query]);

  const counts = {
    all: scenarios.length,
    core: scenarios.filter((s) => s.category !== "edge_case").length,
    edge: scenarios.filter((s) => s.category === "edge_case").length,
  };
  const passed = Object.values(results).filter((r) => r.passed).length;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Test cases">
        <header className="drawer-head">
          <div>
            <h2>Test cases</h2>
            <p className="muted">
              Executable specs from <code>fixtures/specs/scenarios.json</code>. Run sends every turn in a new session
              and checks the spec's expectations and trace properties. Step lets you send turns one at a time.
              {Object.keys(results).length > 0 && (
                <>
                  {" "}
                  Checked this session: <b>{passed}</b>/{Object.keys(results).length} passed.
                </>
              )}
            </p>
          </div>
          <button className="btn" onClick={onClose} aria-label="Close test cases">
            ✕
          </button>
        </header>

        <div className="drawer-tools">
          <div className="tabs" role="tablist">
            {(["all", "core", "edge"] as Filter[]).map((f) => (
              <button
                key={f}
                role="tab"
                aria-selected={filter === f}
                className={`tab ${filter === f ? "active" : ""}`}
                onClick={() => setFilter(f)}
              >
                {{ all: "All", core: "Core SOP", edge: "Edge cases" }[f]} <span className="count">{counts[f]}</span>
              </button>
            ))}
          </div>
          <input
            className="search"
            placeholder="Search id, gate, description or turn text…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <ul className="cases">
          {visible.map((s) => {
            const r = results[s.id];
            const expanded = open === s.id;
            return (
              <li key={s.id} className="case">
                <div className="case-top">
                  <div className="case-title">
                    <code>{s.id}</code>
                    {r && <span className={`badge ${r.passed ? "ok" : "bad"}`}>{r.passed ? "pass" : "fail"}</span>}
                  </div>
                  <div className="case-actions">
                    <button className="btn small primary" onClick={() => onRun(s)}>
                      Run
                    </button>
                    <button className="btn small" onClick={() => onStep(s)}>
                      Step
                    </button>
                  </div>
                </div>
                <p className="case-desc">{s.description}</p>
                <div className="case-tags">
                  <span className={`badge ${s.category === "edge_case" ? "warn" : "muted"}`}>
                    {s.category === "edge_case" ? "edge case" : "core"}
                  </span>
                  {s.gate && <span className="badge muted">{s.gate}</span>}
                  <span className="badge muted">
                    {s.turns.length} turn{s.turns.length > 1 ? "s" : ""}
                  </span>
                  {s.consent_scenario && s.consent_scenario !== "default" && (
                    <span className="badge muted">consent: {s.consent_scenario}</span>
                  )}
                </div>
                {s.source && <p className="case-source">Origin: {s.source}</p>}
                <button className="link" onClick={() => setOpen(expanded ? null : s.id)}>
                  {expanded ? "Hide" : "Show"} turns &amp; expectations
                </button>
                {expanded && (
                  <div className="case-detail">
                    <ol className="turns">
                      {s.turns.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ol>
                    <pre className="expect">{JSON.stringify(s.expect, null, 2)}</pre>
                  </div>
                )}
                {r && !r.passed && (
                  <ul className="failures">
                    {r.failures.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {visible.length === 0 && <li className="muted">No test cases match.</li>}
        </ul>
      </aside>
    </div>
  );
}

export function ScenarioBanner({
  spec,
  next,
  mode,
  busy,
  result,
  onNext,
  onClose,
}: {
  spec: Scenario;
  next: number;
  mode: "run" | "step";
  busy: boolean;
  result: EvalResult | null;
  onNext: () => void;
  onClose: () => void;
}) {
  const done = next >= spec.turns.length;
  return (
    <div className={`banner ${result ? (result.passed ? "pass" : "fail") : ""}`}>
      <div className="banner-row">
        <div className="banner-title">
          <span className="muted">Test case</span> <code>{spec.id}</code>
          <span className="badge muted">
            turn {Math.min(next, spec.turns.length)}/{spec.turns.length}
          </span>
          {result && <span className={`badge ${result.passed ? "ok" : "bad"}`}>{result.passed ? "PASS" : "FAIL"}</span>}
          {!result && done && <span className="badge muted">checking…</span>}
        </div>
        <div className="case-actions">
          {mode === "step" && !done && (
            <button className="btn small primary" disabled={busy} onClick={onNext} title={spec.turns[next]}>
              Send turn {next + 1}
            </button>
          )}
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      {mode === "step" && !done && <p className="banner-next">Next: “{spec.turns[next]}”</p>}
      {result && !result.passed && (
        <ul className="failures">
          {result.failures.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      )}
      {result && result.passed && (
        <p className="banner-next">
          All expectations and {Object.keys(result.trace_properties).length} trace properties hold.
        </p>
      )}
    </div>
  );
}
