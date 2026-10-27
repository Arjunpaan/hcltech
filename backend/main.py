"""
main.py - The FastAPI backend (the "door" the React dashboard talks to).

Start it with:   uvicorn main:app --reload --port 8000   (from the backend/ folder)
API docs:        http://localhost:8000/docs

Every screen of the dashboard is built from these endpoints. All data comes
from SQLite, so whatever the backend does is visible on the dashboard.
"""

import json
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

import config
import db
import orchestrator
from models import ApprovalRequest, CreateRunRequest, GateUpdateRequest
from services import gates as gates_service
from services import preview, traceability, workspace


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create the database tables and output folder when the server starts."""
    db.init_db()
    config.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    yield
    preview.stop_all()  # stop any generated apps when the backend stops


app = FastAPI(title="SDLC Copilot API", version="1.0", lifespan=lifespan,
              description="AI generates. Engineering tools validate. Humans govern.")

# Allow the React dashboard (another port) to call this API during development.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _run_or_404(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ---------------------------------------------------------------------------
# Health and settings
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    """Quick check that the backend is up, and which AI / runner mode it uses."""
    return {"status": "ok", "llm_mode": config.LLM_MODE,
            "llm_model": "mock" if config.LLM_MODE == "mock" else config.LLM_MODEL,
            "runner_mode": config.RUNNER_MODE, "stages": orchestrator.STAGES}


@app.get("/api/config/gates")
def get_gates() -> dict:
    """Current quality-gate rules (from gates.yaml)."""
    return config.load_gates()


@app.put("/api/config/gates")
def update_gates(request: GateUpdateRequest) -> dict:
    """Change gate rules live. The next check / decision uses the new values."""
    return config.save_gates(request.values)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
@app.post("/api/runs")
def create_run(request: CreateRunRequest) -> dict:
    """Start a new workflow for a feature request."""
    run_id = orchestrator.start_run(request.requirement, request.title)
    return db.get_run(run_id)


@app.get("/api/runs")
def list_runs() -> list[dict]:
    """All runs, newest first."""
    return db.query("SELECT * FROM runs ORDER BY id DESC")


@app.get("/api/runs/{run_id}")
def get_run(run_id: int) -> dict:
    """One run plus what (if anything) is waiting for a human."""
    run = _run_or_404(run_id)
    run["waiting_for"] = {
        orchestrator.AWAITING_DESIGN_APPROVAL: "design",
        orchestrator.AWAITING_FIX_APPROVAL: "fix",
        orchestrator.AWAITING_RELEASE_APPROVAL: "release",
    }.get(run["current_stage"])
    run["stages"] = orchestrator.STAGES
    return run


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: int, request: ApprovalRequest) -> dict:
    """Human decision: approve or reject (with a comment saying what to change)."""
    _run_or_404(run_id)
    try:
        return orchestrator.handle_approval(run_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/resume")
def resume(run_id: int) -> dict:
    """Restart a failed or interrupted run from its current stage."""
    _run_or_404(run_id)
    orchestrator.resume(run_id)
    return db.get_run(run_id)


# ---------------------------------------------------------------------------
# Everything a run produced (for the middle panel of the dashboard)
# ---------------------------------------------------------------------------
@app.get("/api/runs/{run_id}/artifacts")
def artifacts(run_id: int) -> dict:
    """Newest analysis, design, reviews, release report, plus every file (with all versions)."""
    _run_or_404(run_id)
    result = {}
    for kind in ("analysis", "design", "review", "security", "release_report", "traceability"):
        row = db.latest_artifact(run_id, kind)
        result[kind] = {"version": row["version"], "data": row["data"], "created_at": row["created_at"]} if row else None
    files = db.query("SELECT name, version, content, created_at FROM artifacts WHERE run_id = ? AND kind = 'file' "
                     "ORDER BY name, version", (run_id,))
    grouped: dict[str, list] = {}
    for row in files:
        grouped.setdefault(row["name"], []).append(row)
    result["files"] = [{"path": name, "latest_version": rows[-1]["version"], "content": rows[-1]["content"],
                        "versions": [r["version"] for r in rows]} for name, rows in grouped.items()]
    return result


@app.get("/api/runs/{run_id}/checks")
def checks(run_id: int) -> list[dict]:
    """All test-engine results (without the long logs; use /api/checks/{id}/log)."""
    _run_or_404(run_id)
    rows = db.query("SELECT id, run_id, round, name, command, exit_code, status, summary, details, duration_ms, "
                    "created_at FROM checks WHERE run_id = ? ORDER BY round, id", (run_id,))
    for row in rows:
        row["details"] = json.loads(row["details"] or "{}")
        row["log_url"] = f"/api/checks/{row['id']}/log"
    return rows


@app.get("/api/checks/{check_id}/log", response_class=PlainTextResponse)
def check_log(check_id: int) -> str:
    """The full log of one check (opens in a new browser tab)."""
    row = db.query_one("SELECT * FROM checks WHERE id = ?", (check_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Check not found")
    return (f"Check: {row['name']}  |  round {row['round']}  |  status {row['status'].upper()}\n"
            f"Command: {row['command']}\nExit code: {row['exit_code']}\nSummary: {row['summary']}\n"
            f"{'=' * 70}\n{row['output'] or ''}")


@app.get("/api/runs/{run_id}/findings")
def list_findings(run_id: int) -> list[dict]:
    """Every finding (open and superseded), newest round first."""
    _run_or_404(run_id)
    return db.query("SELECT * FROM findings WHERE run_id = ? ORDER BY round DESC, blocking DESC, id", (run_id,))


@app.get("/api/runs/{run_id}/changes")
def list_changes(run_id: int) -> list[dict]:
    """Every AI code change (proposed / applied / rejected) with its diff."""
    _run_or_404(run_id)
    return db.query("SELECT id, round, file, diff, reason, status, created_at FROM changes WHERE run_id = ? "
                    "ORDER BY round, id", (run_id,))


@app.get("/api/runs/{run_id}/approvals")
def list_approvals(run_id: int) -> list[dict]:
    """Every human decision for this run."""
    _run_or_404(run_id)
    return db.query("SELECT * FROM approvals WHERE run_id = ? ORDER BY id", (run_id,))


@app.get("/api/runs/{run_id}/events")
def list_events(run_id: int, after_id: int = 0) -> list[dict]:
    """The live activity feed. The dashboard asks for new events every 2 seconds."""
    _run_or_404(run_id)
    rows = db.query("SELECT * FROM events WHERE run_id = ? AND id > ? ORDER BY id", (run_id, after_id))
    for row in rows:
        if row["ref_type"] == "check":
            row["link"] = f"/api/checks/{row['ref_id']}/log"
        elif row["ref_type"] == "llm_call":
            row["link"] = f"/api/llm_calls/{row['ref_id']}"
    return rows


@app.get("/api/runs/{run_id}/llm_calls")
def list_llm_calls(run_id: int) -> list[dict]:
    """Every AI call for this run (agent, model, time, tokens) - without the full prompt text."""
    _run_or_404(run_id)
    return db.query("SELECT id, agent, mode, model, prompt_chars, response_chars, prompt_tokens, completion_tokens, "
                    "duration_ms, from_cache, ok, error, created_at FROM llm_calls WHERE run_id = ? ORDER BY id",
                    (run_id,))


@app.get("/api/llm_calls/{call_id}", response_class=PlainTextResponse)
def llm_call_detail(call_id: int) -> str:
    """Full prompt and answer of one AI call (for auditing)."""
    row = db.query_one("SELECT * FROM llm_calls WHERE id = ?", (call_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return (f"Agent: {row['agent']} | model: {row['model']} | mode: {row['mode']} | ok: {bool(row['ok'])} | "
            f"{row['duration_ms']} ms | cached: {bool(row['from_cache'])}\nError: {row['error']}\n"
            f"{'=' * 30} PROMPT {'=' * 30}\n{row['prompt']}\n{'=' * 30} ANSWER {'=' * 30}\n{row['response']}")


# ---------------------------------------------------------------------------
# Final report, download, executive summary
# ---------------------------------------------------------------------------
@app.get("/api/runs/{run_id}/report")
def report(run_id: int) -> dict:
    """Live gate table, traceability, open issues, decision and the release explanation."""
    run = _run_or_404(run_id)
    live = gates_service.evaluate(run_id)
    saved = db.latest_artifact(run_id, "release_report")
    return {
        "run": run,
        "live_decision": live["decision"],
        "reasons": live["reasons"],
        "gates": live["gates"],
        "traceability": live["traceability"],
        "open_findings": live["open_findings"],
        "release_report": saved["data"] if saved else None,
        "approvals": db.query("SELECT * FROM approvals WHERE run_id = ? ORDER BY id", (run_id,)),
        "rules": live["rules"],
    }


@app.get("/api/runs/{run_id}/traceability")
def trace(run_id: int) -> list[dict]:
    """Requirement -> acceptance criterion -> code -> test -> result."""
    _run_or_404(run_id)
    return traceability.build(run_id)


@app.get("/api/runs/{run_id}/download")
def download(run_id: int) -> Response:
    """Download the generated project as a zip file."""
    _run_or_404(run_id)
    data = workspace.zip_project(run_id)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="run_{run_id}_project.zip"'})


@app.get("/api/runs/{run_id}/code", response_class=HTMLResponse)
def view_code(run_id: int) -> str:
    """A browser page showing every final file the agents wrote (link from the dashboard)."""
    _run_or_404(run_id)
    return preview.code_page(run_id)


@app.get("/api/runs/{run_id}/preview")
def preview_status(run_id: int) -> dict:
    """Is the generated app running? Where?"""
    _run_or_404(run_id)
    return preview.status(run_id)


@app.post("/api/runs/{run_id}/preview/start")
def preview_start(run_id: int) -> dict:
    """Start the generated app on its own port so it can be tried live (http://localhost:<port>/docs)."""
    _run_or_404(run_id)
    try:
        return preview.launch(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/preview/stop")
def preview_stop(run_id: int) -> dict:
    """Stop the generated app."""
    _run_or_404(run_id)
    return preview.stop(run_id)


@app.get("/api/dashboard/summary")
def summary() -> dict:
    """Executive view: runs by stage and decision, test results, security findings."""
    runs = db.query("SELECT id, title, current_stage, status, decision, fix_round, created_at FROM runs ORDER BY id DESC")
    decisions = Counter((r["decision"] or "PENDING").split(" (")[0] for r in runs)
    stages = Counter(r["current_stage"] for r in runs)
    open_findings = db.query("SELECT severity, source FROM findings WHERE status = 'open'")
    latest_tests = db.query(
        "SELECT c.run_id, c.details FROM checks c JOIN (SELECT run_id, MAX(id) AS id FROM checks "
        "WHERE name = 'pytest' GROUP BY run_id) m ON c.id = m.id")
    total = passed = 0
    for row in latest_tests:
        details = json.loads(row["details"] or "{}")
        total += details.get("total", 0)
        passed += details.get("passed", 0)
    return {
        "features_processed": len(runs),
        "by_decision": dict(decisions),
        "by_stage": dict(stages),
        "tests": {"total": total, "passed": passed},
        "open_findings_by_severity": dict(Counter(f["severity"] for f in open_findings)),
        "security_findings_open": sum(1 for f in open_findings
                                      if f["source"] in ("bandit", "secret_scan", "security_agent", "pip_audit")),
        "runs": runs,
    }
