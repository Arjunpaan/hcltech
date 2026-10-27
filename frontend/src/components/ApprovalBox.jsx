// ApprovalBox.jsx - The human-in-the-loop controls.
// Design stage : Approve, or send back to Requirements / Design with a comment (e.g. answers to the questions).
// Fix stage    : Approve the AI's code change, or reject it with instructions (the Fix Agent tries again).
// Release stage: Accept the recommendation, or request changes (goes back to the Fix Agent).
import React, { useState } from "react";
import { api } from "../api.js";

const TEXT = {
  design: { title: "Approve the design?", help: "Read the requirements, assumptions, questions and design. Approve to start coding, or say what to change." },
  fix: { title: "Approve the AI's code changes?", help: "See section 7 for the diff and the reason. Approve to apply them and re-run every check." },
  release: { title: "Final release review", help: "Accept the recommendation, or request changes (they go to the Fix Agent)." },
};

export default function ApprovalBox({ run }) {
  const kind = run.waiting_for;
  const [comment, setComment] = useState("");
  const [approver, setApprover] = useState("developer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Send the decision to the backend; it records it and continues the workflow.
  const send = async (decision, target) => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/api/runs/${run.id}/approve`, { decision, comment, approver, target });
      setComment("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel approval">
      <h4>✋ {TEXT[kind].title}</h4>
      <p className="muted">{TEXT[kind].help}</p>
      <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name" />
      <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)}
        placeholder={kind === "design" ? "Answers to the questions / what to change" : "What should change? (needed to reject)"} />
      <div className="buttons">
        {kind === "design" && (
          <>
            <button className="primary" disabled={busy} onClick={() => send("approve")}>Approve design</button>
            <button className="secondary" disabled={busy} onClick={() => send("reject", "design")}>Change design</button>
            <button className="secondary" disabled={busy} onClick={() => send("reject", "requirements")}>Change requirements</button>
          </>
        )}
        {kind === "fix" && (
          <>
            <button className="primary" disabled={busy} onClick={() => send("approve")}>Approve & re-test</button>
            <button className="secondary" disabled={busy} onClick={() => send("reject")}>Reject & re-propose</button>
          </>
        )}
        {kind === "release" && (
          <>
            <button className="primary" disabled={busy} onClick={() => send("approve")}>Accept recommendation</button>
            <button className="secondary" disabled={busy} onClick={() => send("reject")}>Request changes</button>
          </>
        )}
      </div>
      {error && <div className="banner error">{error}</div>}
    </div>
  );
}
