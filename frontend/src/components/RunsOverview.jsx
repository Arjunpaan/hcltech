// RunsOverview.jsx - Executive view: all features, decisions, tests and security at a glance.
import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { DecisionBadge } from "./FinalReport.jsx";

export default function RunsOverview({ onOpen }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  // Refresh every 5 seconds so running workflows update by themselves.
  useEffect(() => {
    const load = () => api.get("/api/dashboard/summary").then(setData).catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <div className="page">Loading…</div>;

  const decisions = ["READY", "CONDITIONAL", "MANUAL REVIEW", "NOT READY", "PENDING"];
  return (
    <div className="page">
      <h1>All runs (executive view)</h1>
      <div className="cards">
        <div className="card"><div className="big">{data.features_processed}</div>Features processed</div>
        {decisions.map((d) => (
          <div className="card" key={d}><div className="big">{data.by_decision[d] || 0}</div>{d}</div>
        ))}
        <div className="card"><div className="big">{data.tests.passed}/{data.tests.total}</div>Latest tests passed</div>
        <div className="card"><div className="big">{data.security_findings_open}</div>Open security findings</div>
      </div>

      <h3>Features by stage</h3>
      <div className="chips">
        {Object.entries(data.by_stage).map(([stage, count]) => <span className="chip" key={stage}>{stage}: {count}</span>)}
      </div>

      <h3>Runs</h3>
      <table>
        <thead><tr><th>#</th><th>Title</th><th>Stage</th><th>Status</th><th>Fix rounds</th><th>Decision</th><th></th></tr></thead>
        <tbody>
          {data.runs.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td><td>{r.title}</td><td>{r.current_stage}</td><td>{r.status}</td><td>{r.fix_round}</td>
              <td>{r.decision ? <DecisionBadge decision={r.decision} /> : "—"}</td>
              <td><button className="link" onClick={() => onOpen(r.id)}>Open</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
