// App.jsx - The top bar and the screen switcher.
// Screens: New feature | All runs (executive view) | Gate settings | Workflow (one run) | Final report
import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import NewFeature from "./components/NewFeature.jsx";
import RunsOverview from "./components/RunsOverview.jsx";
import Workflow from "./components/Workflow.jsx";
import FinalReport from "./components/FinalReport.jsx";
import GateSettings from "./components/GateSettings.jsx";

export default function App() {
  const [screen, setScreen] = useState("new");      // which screen is visible
  const [runId, setRunId] = useState(null);          // the run being looked at
  const [health, setHealth] = useState(null);        // backend status (AI mode etc.)
  const [backendError, setBackendError] = useState("");

  // Check once that the backend is reachable, and show which AI mode it uses.
  useEffect(() => {
    api.get("/api/health").then(setHealth).catch((e) => setBackendError(e.message));
  }, []);

  // Open a run on the workflow screen.
  const openRun = (id) => {
    setRunId(id);
    setScreen("workflow");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          SDLC Copilot <span className="tagline">AI generates · Tools validate · Humans govern</span>
        </div>
        <nav>
          <button className={screen === "new" ? "active" : ""} onClick={() => setScreen("new")}>New feature</button>
          <button className={screen === "runs" ? "active" : ""} onClick={() => setScreen("runs")}>All runs</button>
          {runId && (
            <>
              <button className={screen === "workflow" ? "active" : ""} onClick={() => setScreen("workflow")}>Workflow #{runId}</button>
              <button className={screen === "report" ? "active" : ""} onClick={() => setScreen("report")}>Final report #{runId}</button>
            </>
          )}
          <button className={screen === "gates" ? "active" : ""} onClick={() => setScreen("gates")}>Gate settings</button>
        </nav>
        <div className="mode">
          {health ? `AI: ${health.llm_mode} (${health.llm_model}) · Runner: ${health.runner_mode}` : backendError ? "Backend offline" : "…"}
        </div>
      </header>

      {backendError && (
        <div className="banner error">
          Cannot reach the backend at the configured URL ({backendError}). Start it with: <code>uvicorn main:app --reload</code> in the backend folder.
        </div>
      )}

      <main>
        {screen === "new" && <NewFeature onCreated={(run) => openRun(run.id)} onOpen={openRun} />}
        {screen === "runs" && <RunsOverview onOpen={openRun} />}
        {screen === "workflow" && runId && <Workflow runId={runId} onShowReport={() => setScreen("report")} />}
        {screen === "report" && runId && <FinalReport runId={runId} />}
        {screen === "gates" && <GateSettings />}
      </main>
    </div>
  );
}
