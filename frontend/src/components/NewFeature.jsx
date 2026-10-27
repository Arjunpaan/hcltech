// NewFeature.jsx - Screen 1: type a feature request and press "Analyze".
import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// The example from the hackathon brief, so the demo can start with one click.
const SAMPLE =
  "Develop an API allowing customers to update their contact information. Validate mandatory fields, " +
  "prevent unauthorized modification, maintain an audit record and return appropriate API error responses.";

export default function NewFeature({ onCreated, onOpen }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState([]);

  // Show the latest runs under the form so you can reopen one quickly.
  useEffect(() => {
    api.get("/api/runs").then((rows) => setRecent(rows.slice(0, 5))).catch(() => {});
  }, []);

  // Send the requirement to the backend; it starts the agent workflow.
  const analyze = async () => {
    setBusy(true);
    setError("");
    try {
      const run = await api.post("/api/runs", { requirement: text });
      onCreated(run);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <h1>New feature request</h1>
      <p className="muted">Describe one small API feature. The agents will analyse it, design it, write code and tests, run real checks and fix problems. You approve the design, every fix and the release.</p>
      <textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Develop an API allowing customers to ..." />
      <div className="row">
        <button className="secondary" onClick={() => setText(SAMPLE)}>Use example from the brief</button>
        <button className="primary" disabled={busy || text.trim().length < 10} onClick={analyze}>
          {busy ? "Starting…" : "Analyze"}
        </button>
      </div>
      {error && <div className="banner error">{error}</div>}

      {recent.length > 0 && (
        <>
          <h3>Recent runs</h3>
          <table>
            <thead><tr><th>#</th><th>Title</th><th>Stage</th><th>Decision</th><th></th></tr></thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td><td>{r.title}</td><td>{r.current_stage}</td><td>{r.decision || "—"}</td>
                  <td><button className="link" onClick={() => onOpen(r.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
