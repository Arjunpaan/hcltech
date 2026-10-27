// FinalReport.jsx - Screen 3: quality gates, requirement coverage (traceability),
// unresolved issues, the release recommendation, approvals and code download.
import React, { useEffect, useState } from "react";
import { api, link } from "../api.js";
import PreviewBox from "./PreviewBox.jsx";

// Coloured label for READY / CONDITIONAL / MANUAL REVIEW / NOT READY.
export function DecisionBadge({ decision }) {
  const key = (decision || "").split(" (")[0].replace(" ", "_").toLowerCase();
  return <span className={`decision ${key}`}>{decision}</span>;
}

// Table of gates: name, result, why, and whether it is mandatory.
export function GateTable({ gates }) {
  return (
    <table>
      <thead><tr><th>Gate</th><th>Result</th><th>Why</th><th>Mandatory</th></tr></thead>
      <tbody>
        {gates.map((g) => (
          <tr key={g.gate}>
            <td>{g.gate}</td>
            <td><span className={`badge ${g.status}`}>{{ passed: "PASSED", failed: "FAILED", not_executed: "NOT EXECUTED" }[g.status]}</span></td>
            <td>{g.reason}</td>
            <td>{g.blocking ? "yes" : "no"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function FinalReport({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  // The report is recalculated live, so changing gate settings shows its effect immediately.
  useEffect(() => {
    const load = () => api.get(`/api/runs/${runId}/report`).then(setData).catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [runId]);

  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <div className="page">Loading report…</div>;

  const saved = data.release_report;
  return (
    <div className="page">
      <h1>Final report · {data.run.title}</h1>
      <div className="cards">
        <div className="card">Live decision (current rules)<div className="big"><DecisionBadge decision={data.live_decision} /></div></div>
        {saved && <div className="card">Recorded at release assessment<div className="big"><DecisionBadge decision={saved.decision} /></div></div>}
        <div className="card">Fix rounds used<div className="big">{data.run.fix_round}</div></div>
        <div className="card">Open findings<div className="big">{data.open_findings.length}</div></div>
      </div>

      <PreviewBox runId={runId} />

      <h3>Why</h3>
      <ul>{data.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      {saved?.explanation && <div className="note"><b>Release Agent explanation:</b> {saved.explanation}</div>}

      <h3>Quality gates</h3>
      <GateTable gates={data.gates} />

      <h3>Requirement coverage (traceability)</h3>
      <table>
        <thead><tr><th>Requirement</th><th>Acceptance criterion</th><th>Implementation</th><th>Tests</th><th>Result</th></tr></thead>
        <tbody>
          {data.traceability.map((row) => (
            <tr key={row.acceptance_criterion_id}>
              <td><b>{row.requirement_id}</b> {row.requirement}</td>
              <td><b>{row.acceptance_criterion_id}</b> {row.acceptance_criterion}</td>
              <td>{row.implementation.length ? row.implementation.map((i) => <div key={i}><code>{i}</code></div>) : <span className="muted">not linked</span>}</td>
              <td>{row.tests.length ? row.tests.map((t) => <div key={t.name}><code>{t.name}</code></div>) : <span className="muted">no test</span>}</td>
              <td><span className={`badge ${row.result === "PASSED" ? "passed" : row.result === "FAILED" ? "failed" : "not_executed"}`}>{row.result}</span></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Unresolved issues</h3>
      {data.open_findings.length === 0 ? <p className="muted">None.</p> : (
        <table>
          <thead><tr><th>Severity</th><th>Source</th><th>Component</th><th>Finding</th><th>Blocks?</th></tr></thead>
          <tbody>{data.open_findings.map((f) => (
            <tr key={f.id}><td><span className={`sev ${f.severity}`}>{f.severity}</span></td><td>{f.source}</td><td>{f.file}</td><td>{f.title}</td><td>{f.blocking ? "YES" : "no"}</td></tr>
          ))}</tbody>
        </table>
      )}

      <h3>Human approvals</h3>
      <table>
        <thead><tr><th>Stage</th><th>Decision</th><th>By</th><th>Comment</th><th>When (UTC)</th></tr></thead>
        <tbody>{data.approvals.map((a) => (
          <tr key={a.id}><td>{a.stage}</td><td>{a.decision}</td><td>{a.approver}</td><td>{a.comment}</td><td>{a.created_at}</td></tr>
        ))}</tbody>
      </table>

      <div className="row">
        <a className="button primary" href={link(`/api/runs/${runId}/download`)}>Download generated code (.zip)</a>
      </div>
      <p className="muted">Generated code is never classified as production-ready automatically. A human engineer must review it.</p>
    </div>
  );
}
