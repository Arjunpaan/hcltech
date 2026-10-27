// Workflow.jsx - Screen 2: one run, live.
// Left  : the SDLC stages (what is done, what is running now)
// Middle: the output of the selected stage (requirements, design, code, tests, checks, findings, fixes, release)
// Right : run status, the human approval box, latest check results with log links, live backend activity
import React, { useEffect, useState } from "react";
import { api, link } from "../api.js";
import ApprovalBox from "./ApprovalBox.jsx";
import EventLog from "./EventLog.jsx";
import PreviewBox from "./PreviewBox.jsx";
import { DecisionBadge, GateTable } from "./FinalReport.jsx";

// The sidebar sections and which backend stages belong to each one.
const SECTIONS = [
  { key: "requirements", label: "1. Requirements", stages: ["ANALYZING"] },
  { key: "design", label: "2. Design + approval", stages: ["DESIGNING", "AWAITING_DESIGN_APPROVAL"] },
  { key: "code", label: "3. Code", stages: ["DEVELOPING"] },
  { key: "tests", label: "4. Tests", stages: ["WRITING_TESTS"] },
  { key: "checks", label: "5. Test engine", stages: ["CHECKING"] },
  { key: "review", label: "6. Review & security", stages: ["REVIEWING"] },
  { key: "fixes", label: "7. Fixes (+ approval)", stages: ["FIXING", "AWAITING_FIX_APPROVAL"] },
  { key: "release", label: "8. Release (+ approval)", stages: ["RELEASE_ASSESSMENT", "AWAITING_RELEASE_APPROVAL", "COMPLETED"] },
];

export default function Workflow({ runId, onShowReport }) {
  const [run, setRun] = useState(null);
  const [artifacts, setArtifacts] = useState(null);
  const [checks, setChecks] = useState([]);
  const [findings, setFindings] = useState([]);
  const [changes, setChanges] = useState([]);
  const [selected, setSelected] = useState("requirements");
  const [error, setError] = useState("");

  // Load everything about this run, then again every 2 seconds (live view of the backend).
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [r, a, c, f, ch] = await Promise.all([
          api.get(`/api/runs/${runId}`),
          api.get(`/api/runs/${runId}/artifacts`),
          api.get(`/api/runs/${runId}/checks`),
          api.get(`/api/runs/${runId}/findings`),
          api.get(`/api/runs/${runId}/changes`),
        ]);
        if (!alive) return;
        setRun(r); setArtifacts(a); setChecks(c); setFindings(f); setChanges(ch); setError("");
      } catch (e) {
        if (alive) setError(e.message);
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [runId]);

  // When the backend moves to a new stage, jump to that stage's section automatically.
  const currentStage = run?.current_stage;
  useEffect(() => {
    const section = SECTIONS.find((s) => s.stages.includes(currentStage));
    if (section) setSelected(section.key);
  }, [currentStage]);

  if (error && !run) return <div className="banner error">{error}</div>;
  if (!run || !artifacts) return <div className="page">Loading run #{runId}…</div>;

  const files = artifacts.files || [];
  // Does a section already have output? (used for the ✔ marks)
  const hasOutput = {
    requirements: !!artifacts.analysis, design: !!artifacts.design,
    code: files.some((f) => f.path.startsWith("app/")), tests: files.some((f) => f.path.startsWith("tests/")),
    checks: checks.length > 0, review: !!artifacts.review, fixes: changes.length > 0, release: !!artifacts.release_report,
  };

  return (
    <div className="workflow">
      {/* LEFT: stages */}
      <aside className="stages">
        <h3>{run.title}</h3>
        {SECTIONS.map((s) => {
          const active = s.stages.includes(run.current_stage);
          const icon = active ? (run.status === "failed" ? "✖" : run.status === "waiting_for_human" ? "⏸" : "▶") : hasOutput[s.key] ? "✔" : "○";
          return (
            <button key={s.key} className={`stage ${selected === s.key ? "selected" : ""} ${active ? "active" : ""}`} onClick={() => setSelected(s.key)}>
              <span className="icon">{icon}</span> {s.label}
            </button>
          );
        })}
        <button className="secondary full" onClick={onShowReport}>Open final report</button>
        <a className="button secondary full" href={link(`/api/runs/${runId}/download`)}>Download code (.zip)</a>
      </aside>

      {/* MIDDLE: output of the selected stage */}
      <section className="output">
        {selected === "requirements" && <RequirementsView analysis={artifacts.analysis} />}
        {selected === "design" && <DesignView design={artifacts.design} />}
        {selected === "code" && <FilesView files={files.filter((f) => f.path.startsWith("app/"))} title="Generated application code" />}
        {selected === "tests" && <FilesView files={files.filter((f) => f.path.startsWith("tests/"))} title="Generated tests" />}
        {selected === "checks" && <ChecksView checks={checks} />}
        {selected === "review" && <ReviewView findings={findings} review={artifacts.review} security={artifacts.security} />}
        {selected === "fixes" && <FixesView changes={changes} />}
        {selected === "release" && <ReleaseView report={artifacts.release_report} onShowReport={onShowReport} />}
      </section>

      {/* RIGHT: status, approvals, results, live activity */}
      <aside className="side">
        <div className="panel">
          <div><b>Stage:</b> {run.current_stage}</div>
          <div><b>Status:</b> <span className={`status ${run.status}`}>{run.status}</span></div>
          <div><b>Fix rounds used:</b> {run.fix_round}</div>
          {run.decision && <div><b>Decision:</b> <DecisionBadge decision={run.decision} /></div>}
          {run.status === "failed" && (
            <>
              <div className="banner error">{run.error}</div>
              <button className="primary" onClick={() => api.post(`/api/runs/${runId}/resume`)}>Retry this stage</button>
            </>
          )}
        </div>

        {run.waiting_for && <ApprovalBox run={run} />}

        {hasOutput.code && <PreviewBox runId={runId} />}

        <div className="panel">
          <h4>Latest check results</h4>
          {latestRound(checks).length === 0 && <div className="muted">No checks yet.</div>}
          {latestRound(checks).map((c) => (
            <div key={c.id} className="checkline">
              <StatusBadge status={c.status} /> {c.name}
              <a href={link(c.log_url)} target="_blank" rel="noreferrer">log</a>
            </div>
          ))}
        </div>

        <EventLog runId={runId} />
      </aside>
    </div>
  );
}

// Checks of the newest round only.
function latestRound(checks) {
  if (!checks.length) return [];
  const max = Math.max(...checks.map((c) => c.round));
  return checks.filter((c) => c.round === max);
}

export function StatusBadge({ status }) {
  const label = { passed: "PASSED", failed: "FAILED", not_executed: "NOT EXECUTED" }[status] || status;
  return <span className={`badge ${status}`}>{label}</span>;
}

// ---- Middle-panel views -------------------------------------------------------------

function RequirementsView({ analysis }) {
  if (!analysis) return <Waiting what="the Business Analyst Agent" />;
  const a = analysis.data;
  return (
    <div>
      <h2>Requirements <small>v{analysis.version}</small></h2>
      <p>{a.summary}</p>
      <table>
        <thead><tr><th>ID</th><th>Requirement</th><th>Type</th></tr></thead>
        <tbody>{a.requirements.map((r) => <tr key={r.id}><td>{r.id}</td><td>{r.text}</td><td>{r.type}</td></tr>)}</tbody>
      </table>
      <h3>Acceptance criteria</h3>
      <table>
        <thead><tr><th>ID</th><th>For</th><th>Criterion</th></tr></thead>
        <tbody>{a.acceptance_criteria.map((c) => <tr key={c.id}><td>{c.id}</td><td>{c.requirement_id}</td><td>{c.text}</td></tr>)}</tbody>
      </table>
      <List title="User stories" items={a.user_stories.map((s) => `${s.id}: ${s.text}`)} />
      <List title="Business rules" items={a.business_rules} />
      <List title="Assumptions (not requirements!)" items={a.assumptions} highlight />
      <List title="Open questions for the human" items={a.questions} highlight />
      <List title="Ambiguities" items={a.ambiguities} />
      <List title="Dependencies" items={a.dependencies} />
    </div>
  );
}

function DesignView({ design }) {
  if (!design) return <Waiting what="the Solution Designer Agent" />;
  const d = design.data;
  return (
    <div>
      <h2>Technical design <small>v{design.version}</small></h2>
      <p>{d.overview}</p>
      <List title="Components" items={d.components} />
      <h3>API endpoints</h3>
      <table>
        <thead><tr><th>Method</th><th>Path</th><th>Request</th><th>Response</th><th>Status codes</th></tr></thead>
        <tbody>{d.endpoints.map((e, i) => (
          <tr key={i}><td>{e.method}</td><td><code>{e.path}</code></td><td>{e.request_model}</td><td>{e.response_model}</td><td>{e.status_codes.join(", ")}</td></tr>
        ))}</tbody>
      </table>
      <h3>Data models</h3>
      {d.data_models.map((m) => <div key={m.name}><b>{m.name}</b>: {m.fields.join(" · ")}</div>)}
      <List title="Validation rules" items={d.validation_rules} />
      <List title="Error handling" items={d.error_handling} />
      <List title="Logging" items={d.logging} />
      <List title="Security" items={d.security} />
      <List title="File structure" items={d.file_structure} />
    </div>
  );
}

function FilesView({ files, title }) {
  const [current, setCurrent] = useState(null);
  if (!files.length) return <Waiting what="the agents to write files" />;
  const file = files.find((f) => f.path === current) || files[0];
  return (
    <div>
      <h2>{title}</h2>
      <div className="chips">
        {files.map((f) => (
          <button key={f.path} className={`chip ${f.path === file.path ? "selected" : ""}`} onClick={() => setCurrent(f.path)}>
            {f.path} <small>v{f.latest_version}</small>
          </button>
        ))}
      </div>
      <p className="muted">Showing the newest version (v{file.latest_version}). Versions kept: {file.versions.join(", ")}. Generated code is never production-ready without human review.</p>
      <pre className="code">{file.content}</pre>
    </div>
  );
}

function ChecksView({ checks }) {
  if (!checks.length) return <Waiting what="the test engine" />;
  const rounds = [...new Set(checks.map((c) => c.round))].sort((a, b) => b - a);
  return (
    <div>
      <h2>Test engine results</h2>
      <p className="muted">Real tools, no AI. Round 0 = first check; each approved fix starts a new round. "NOT EXECUTED" is never counted as passed.</p>
      {rounds.map((round) => (
        <div key={round} className="round">
          <h3>Round {round}</h3>
          <table>
            <thead><tr><th>Check</th><th>Result</th><th>Summary</th><th>Time</th><th>Log</th></tr></thead>
            <tbody>
              {checks.filter((c) => c.round === round).map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td><td><StatusBadge status={c.status} /></td><td>{c.summary}</td>
                  <td>{c.duration_ms} ms</td><td><a href={link(c.log_url)} target="_blank" rel="noreferrer">view log</a></td>
                </tr>
              ))}
            </tbody>
          </table>
          {checks.filter((c) => c.round === round && c.name === "pytest").map((c) =>
            c.details?.cases?.length ? (
              <table key={`cases-${c.id}`} className="compact">
                <thead><tr><th>Test case</th><th>Outcome</th><th>Message</th></tr></thead>
                <tbody>{c.details.cases.map((t) => (
                  <tr key={t.name}><td>{t.name}</td><td><StatusBadge status={t.outcome === "passed" ? "passed" : "failed"} /></td><td className="msg">{t.message.slice(0, 200)}</td></tr>
                ))}</tbody>
              </table>
            ) : null
          )}
        </div>
      ))}
    </div>
  );
}

function ReviewView({ findings, review, security }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? findings : findings.filter((f) => f.status === "open");
  return (
    <div>
      <h2>Code review & security</h2>
      {review && <p><b>Reviewer:</b> {review.data.summary}</p>}
      {security && <p><b>Security:</b> {security.data.summary}</p>}
      <label className="muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show older (superseded) findings too</label>
      {rows.length === 0 ? <p className="muted">No findings to show.</p> : (
        <table>
          <thead><tr><th>Round</th><th>Source</th><th>Severity</th><th>Component</th><th>Finding</th><th>Evidence</th><th>Recommended fix</th><th>Blocks?</th><th>Status</th></tr></thead>
          <tbody>{rows.map((f) => (
            <tr key={f.id} className={f.status !== "open" ? "dim" : ""}>
              <td>{f.round}</td><td>{f.source}</td><td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
              <td>{f.file}{f.line ? `:${f.line}` : ""}</td><td>{f.title}</td><td className="msg">{(f.evidence || "").slice(0, 160)}</td>
              <td className="msg">{f.recommendation}</td><td>{f.blocking ? "YES" : "no"}</td><td>{f.status}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function FixesView({ changes }) {
  if (!changes.length) return <p className="muted">No fixes needed (yet). If the test engine finds blocking issues, the Fix Agent's proposals appear here for your approval.</p>;
  return (
    <div>
      <h2>AI code changes (every change is recorded)</h2>
      {changes.map((c) => (
        <div key={c.id} className="change">
          <div><b>Fix round {c.round}</b> · <code>{c.file}</code> · <span className={`badge ${c.status === "applied" ? "passed" : c.status === "rejected" ? "failed" : "not_executed"}`}>{c.status.toUpperCase()}</span></div>
          <div className="muted">Reason: {c.reason || "—"}</div>
          <pre className="code diff">{c.diff}</pre>
        </div>
      ))}
    </div>
  );
}

function ReleaseView({ report, onShowReport }) {
  if (!report) return <Waiting what="the release assessment" />;
  const r = report.data;
  return (
    <div>
      <h2>Release recommendation: <DecisionBadge decision={r.decision} /></h2>
      <p>{r.explanation}</p>
      <GateTable gates={r.gates} />
      <button className="primary" onClick={onShowReport}>Open full report (traceability, open issues)</button>
    </div>
  );
}

// ---- Small helpers ----------------------------------------------------------------
function List({ title, items, highlight }) {
  if (!items || !items.length) return null;
  return (
    <div className={highlight ? "note" : ""}>
      <h4>{title}</h4>
      <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </div>
  );
}

function Waiting({ what }) {
  return <p className="muted">Waiting for {what}… (this page refreshes by itself)</p>;
}
