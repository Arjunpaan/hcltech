// GateSettings.jsx - Change the quality-gate rules live (saved to backend/gates.yaml).
// Example demo: set "min_test_pass_rate" to 0.8, then open a final report and watch the decision change.
import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// Plain-English help for each setting.
const HELP = {
  max_fix_rounds: "How many times the Fix Agent may try automatically",
  require_fix_approval: "A human must approve every AI code change",
  min_test_pass_rate: "Share of tests that must pass (1.0 = all)",
  block_severity: "Security findings at or above this level block release",
  reviewer_block_severity: "Code-review findings at or above this level block release",
  conditional_min_severity: "Open findings at or above this level make the result CONDITIONAL",
  max_ruff_issues: "Code-quality issues allowed",
  ruff_blocking: "If on, too many quality issues block release",
  require_ac_test_mapping: "Every acceptance criterion must have a test",
  run_pip_audit: "Run the dependency vulnerability scan (needs internet)",
  check_timeout_seconds: "Stop any single check after this many seconds",
};
const SEVERITIES = ["low", "medium", "high", "critical"];

export default function GateSettings() {
  const [values, setValues] = useState(null);
  const [message, setMessage] = useState("");

  useEffect(() => { api.get("/api/config/gates").then(setValues); }, []);

  // Save all values; the backend writes gates.yaml.
  const save = async () => {
    try {
      setValues(await api.put("/api/config/gates", { values }));
      setMessage("Saved. The next check and every report now use these rules.");
    } catch (e) {
      setMessage(e.message);
    }
  };

  if (!values) return <div className="page">Loading…</div>;
  return (
    <div className="page narrow">
      <h1>Quality-gate settings</h1>
      <table>
        <tbody>
          {Object.entries(values).map(([key, value]) => (
            <tr key={key}>
              <td><code>{key}</code><div className="muted">{HELP[key]}</div></td>
              <td>
                {typeof value === "boolean" ? (
                  <input type="checkbox" checked={value} onChange={(e) => setValues({ ...values, [key]: e.target.checked })} />
                ) : SEVERITIES.includes(value) ? (
                  <select value={value} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                    {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                ) : (
                  <input type="number" step="any" value={value} onChange={(e) => setValues({ ...values, [key]: Number(e.target.value) })} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="primary" onClick={save}>Save rules</button>
      {message && <p className="muted">{message}</p>}
    </div>
  );
}
