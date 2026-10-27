// PreviewBox.jsx - See and try what the agents built:
//  - "View final code" opens every generated file in a new browser tab
//  - "Run generated app" starts the AI-built API and gives a live localhost link (/docs = try it in the browser)
import React, { useEffect, useState } from "react";
import { api, link } from "../api.js";

export default function PreviewBox({ runId }) {
  const [state, setState] = useState({ running: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Check every 5 seconds whether the generated app is running.
  useEffect(() => {
    const load = () => api.get(`/api/runs/${runId}/preview`).then(setState).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [runId]);

  const call = async (action) => {
    setBusy(true);
    setError("");
    try {
      setState(await api.post(`/api/runs/${runId}/preview/${action}`));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel preview">
      <h4>See and try the generated code</h4>
      <div className="buttons">
        <a className="button secondary" href={link(`/api/runs/${runId}/code`)} target="_blank" rel="noreferrer">View final code</a>
        {!state.running ? (
          <button className="primary" disabled={busy} onClick={() => call("start")}>{busy ? "Starting…" : "Run generated app"}</button>
        ) : (
          <button className="secondary" disabled={busy} onClick={() => call("stop")}>Stop app</button>
        )}
      </div>
      {state.running && (
        <p>
          Live now: <a href={state.docs_url} target="_blank" rel="noreferrer">{state.docs_url}</a>
          <br /><span className="muted">Open it, pick an endpoint, click "Try it out", then "Execute".</span>
        </p>
      )}
      {error && <div className="banner error" style={{ whiteSpace: "pre-wrap" }}>{error}</div>}
    </div>
  );
}
