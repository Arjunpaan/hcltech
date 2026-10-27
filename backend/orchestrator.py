"""
orchestrator.py - The MANAGER. Moves one run through the SDLC, stage by stage.

How it works:
- Each run has a `current_stage` saved in SQLite.
- `advance(run_id)` looks at the stage, does that stage's work, saves the result,
  and moves to the next stage. It keeps going until it reaches a stage that
  needs a HUMAN, then it pauses (status = waiting_for_human).
- When the human clicks Approve / Reject on the dashboard, `handle_approval()`
  records the decision and starts `advance()` again from the right stage.
- Because the stage is stored in the database, a restarted server can resume.

Stage flow:
  ANALYZING -> DESIGNING -> AWAITING_DESIGN_APPROVAL (human)
  -> DEVELOPING -> WRITING_TESTS -> CHECKING -> REVIEWING
  -> (blocking issues and rounds left?) FIXING -> AWAITING_FIX_APPROVAL (human) -> CHECKING ...
  -> RELEASE_ASSESSMENT -> AWAITING_RELEASE_APPROVAL (human) -> COMPLETED
"""

import difflib
import json
import threading

import config
import db
from agents import analyst, designer, developer, fixer, release, reviewer, security, tester
from models import AnalysisResult, ApprovalRequest, DesignResult
from services import findings as findings_service
from services import gates as gates_service
from services import runner

# All stages, in order (the dashboard uses this list for its left sidebar).
ANALYZING = "ANALYZING"
DESIGNING = "DESIGNING"
AWAITING_DESIGN_APPROVAL = "AWAITING_DESIGN_APPROVAL"
DEVELOPING = "DEVELOPING"
WRITING_TESTS = "WRITING_TESTS"
CHECKING = "CHECKING"
REVIEWING = "REVIEWING"
FIXING = "FIXING"
AWAITING_FIX_APPROVAL = "AWAITING_FIX_APPROVAL"
RELEASE_ASSESSMENT = "RELEASE_ASSESSMENT"
AWAITING_RELEASE_APPROVAL = "AWAITING_RELEASE_APPROVAL"
COMPLETED = "COMPLETED"

STAGES = [ANALYZING, DESIGNING, AWAITING_DESIGN_APPROVAL, DEVELOPING, WRITING_TESTS, CHECKING, REVIEWING,
          FIXING, AWAITING_FIX_APPROVAL, RELEASE_ASSESSMENT, AWAITING_RELEASE_APPROVAL, COMPLETED]
WAITING_STAGES = {AWAITING_DESIGN_APPROVAL, AWAITING_FIX_APPROVAL, AWAITING_RELEASE_APPROVAL}

# One lock per run, so the same run is never processed twice at the same time.
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(run_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


# ---------------------------------------------------------------------------
# Starting and resuming
# ---------------------------------------------------------------------------
def start_run(requirement: str, title: str | None = None) -> int:
    """Create a run and start processing it in the background."""
    run_id = db.create_run(requirement.strip(), title or "New feature", ANALYZING)
    db.log_event(run_id, ANALYZING, "system", "Requirement received. Starting the workflow.")
    spawn(run_id)
    return run_id


def spawn(run_id: int) -> None:
    """Run `advance` in a background thread (or directly when RUN_SYNC is on, e.g. in tests)."""
    if config.RUN_SYNC:
        advance(run_id)
    else:
        threading.Thread(target=advance, args=(run_id,), daemon=True).start()


def resume(run_id: int) -> None:
    """Continue a run that failed or was interrupted (it restarts its current stage)."""
    run = db.get_run(run_id)
    if run and run["current_stage"] not in WAITING_STAGES and run["current_stage"] != COMPLETED:
        db.update_run(run_id, status="running", error=None)
        db.log_event(run_id, run["current_stage"], "system", "Resuming the workflow.")
        spawn(run_id)


# ---------------------------------------------------------------------------
# The main loop
# ---------------------------------------------------------------------------
def advance(run_id: int) -> None:
    """Do stage after stage until a human is needed or the run ends."""
    lock = _lock_for(run_id)
    if not lock.acquire(blocking=False):
        return  # already being processed
    try:
        while True:
            run = db.get_run(run_id)
            stage = run["current_stage"]
            if stage in WAITING_STAGES or stage == COMPLETED or run["status"] == "failed":
                return
            try:
                next_stage = STAGE_HANDLERS[stage](run)
            except Exception as exc:  # any error stops the run with a clear message
                db.update_run(run_id, status="failed", error=f"{stage}: {exc}")
                db.log_event(run_id, stage, "system", f"Stage failed: {exc}")
                return
            status = "waiting_for_human" if next_stage in WAITING_STAGES else (
                "completed" if next_stage == COMPLETED else "running")
            db.update_run(run_id, current_stage=next_stage, status=status)
            if next_stage in WAITING_STAGES:
                db.log_event(run_id, next_stage, "system", "Waiting for human approval on the dashboard.")
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Stage handlers. Each one does its work and returns the NEXT stage.
# ---------------------------------------------------------------------------
def _analysis(run_id: int) -> AnalysisResult:
    return AnalysisResult.model_validate(db.latest_artifact(run_id, "analysis")["data"])


def _design(run_id: int) -> DesignResult:
    return DesignResult.model_validate(db.latest_artifact(run_id, "design")["data"])


def _latest_reject_comment(run_id: int, stage: str, target: str | None = None) -> str:
    """The newest 'reject' comment for a stage (the human's change request)."""
    sql = "SELECT comment FROM approvals WHERE run_id = ? AND stage = ? AND decision = 'reject'"
    params: tuple = (run_id, stage)
    if target:
        sql += " AND target = ?"
        params += (target,)
    row = db.query_one(sql + " ORDER BY id DESC LIMIT 1", params)
    return (row or {}).get("comment") or ""


def do_analysis(run: dict) -> str:
    """Agent 1: Business Analyst."""
    run_id = run["id"]
    db.log_event(run_id, ANALYZING, "analyst", "Business Analyst is reading the requirement...")
    feedback = _latest_reject_comment(run_id, "design", "requirements")
    result = analyst.run(run_id, run["requirement"], feedback)
    artifact_id, version = db.save_artifact(run_id, "analysis", "analysis", result.model_dump())
    db.update_run(run_id, title=result.title)
    db.log_event(run_id, ANALYZING, "analyst",
                 f"Produced {len(result.requirements)} requirements, {len(result.acceptance_criteria)} acceptance "
                 f"criteria, {len(result.assumptions)} assumptions, {len(result.questions)} questions (v{version}).",
                 ref_type="artifact", ref_id=artifact_id)
    return DESIGNING


def do_design(run: dict) -> str:
    """Agent 2: Solution Designer. Then wait for human approval."""
    run_id = run["id"]
    db.log_event(run_id, DESIGNING, "designer", "Solution Designer is creating the technical design...")
    feedback = _latest_reject_comment(run_id, "design", "design")
    result = designer.run(run_id, _analysis(run_id), feedback)
    artifact_id, version = db.save_artifact(run_id, "design", "design", result.model_dump())
    db.log_event(run_id, DESIGNING, "designer",
                 f"Design v{version}: {len(result.endpoints)} endpoint(s), {len(result.data_models)} data model(s).",
                 ref_type="artifact", ref_id=artifact_id)
    return AWAITING_DESIGN_APPROVAL


def do_develop(run: dict) -> str:
    """Agent 3: Developer writes the application files."""
    run_id = run["id"]
    db.log_event(run_id, DEVELOPING, "developer", "Developer Agent is writing the application code...")
    files = developer.run(run_id, _analysis(run_id), _design(run_id))
    for item in files:
        artifact_id, version = db.save_artifact(run_id, "file", item["path"], item["content"])
        db.log_event(run_id, DEVELOPING, "developer", f"Wrote {item['path']} (v{version})",
                     ref_type="artifact", ref_id=artifact_id)
    return WRITING_TESTS


def do_tests(run: dict) -> str:
    """Agent 4: Test Engineer writes pytest tests mapped to acceptance criteria."""
    run_id = run["id"]
    db.log_event(run_id, WRITING_TESTS, "tester", "Test Engineer Agent is writing tests...")
    code = {p: c for p, c in db.current_files(run_id).items() if p.startswith("app/")}
    files = tester.run(run_id, _analysis(run_id), _design(run_id), code)
    for item in files:
        artifact_id, version = db.save_artifact(run_id, "file", item["path"], item["content"])
        db.log_event(run_id, WRITING_TESTS, "tester", f"Wrote {item['path']} (v{version})",
                     ref_type="artifact", ref_id=artifact_id)
    return CHECKING


def do_checks(run: dict) -> str:
    """The TEST ENGINE: run real tools, save every result and log, create findings."""
    run_id, round_no = run["id"], run["fix_round"]
    findings_service.supersede_old(run_id, round_no)
    checks = runner.run_all(run_id, round_no)
    created = findings_service.from_checks(run_id, round_no, checks)
    db.log_event(run_id, CHECKING, "test_engine", f"Round {round_no} finished: {created} finding(s) from tools.")
    return REVIEWING


def _tool_summary(run_id: int, round_no: int) -> str:
    """Short text of this round's check results, for the AI reviewers."""
    rows = db.query("SELECT name, status, summary, details FROM checks WHERE run_id = ? AND round = ? ORDER BY id",
                    (run_id, round_no))
    lines = []
    for row in rows:
        lines.append(f"- {row['name']}: {row['status']} - {row['summary']}")
        details = json.loads(row["details"] or "{}")
        for case in details.get("cases", []):
            if case["outcome"] != "passed":
                lines.append(f"    failed test {case['name']}: {case['message'][:300]}")
        for issue in details.get("issues", [])[:10]:
            lines.append(f"    {issue.get('file')}:{issue.get('line')} {issue.get('test_id') or issue.get('code')} "
                         f"{issue.get('message')}")
        for hit in details.get("hits", []):
            lines.append(f"    {hit['file']}:{hit['line']} {hit['type']}")
    return "\n".join(lines)


def do_review(run: dict) -> str:
    """Agents 5 + Security: AI review using the code AND the tool results. Then decide: fix or release?"""
    run_id, round_no = run["id"], run["fix_round"]
    code = {p: c for p, c in db.current_files(run_id).items() if p.startswith("app/")}
    summary = _tool_summary(run_id, round_no)

    db.log_event(run_id, REVIEWING, "reviewer", "Code Reviewer Agent is reviewing the code...")
    review = reviewer.run(run_id, code, summary)
    db.save_artifact(run_id, "review", "review", {"round": round_no, **review.model_dump()})
    findings_service.from_agent(run_id, round_no, "reviewer_agent", review)

    db.log_event(run_id, REVIEWING, "security", "Security Agent is reviewing scanner results and code...")
    sec = security.run(run_id, code, summary)
    db.save_artifact(run_id, "security", "security", {"round": round_no, **sec.model_dump()})
    findings_service.from_agent(run_id, round_no, "security_agent", sec)
    db.log_event(run_id, REVIEWING, "reviewer",
                 f"Review done: {len(review.findings)} code finding(s), {len(sec.findings)} security finding(s).")

    blocked, reasons = gates_service.has_blocking_issues(run_id)
    max_rounds = config.load_gates()["max_fix_rounds"]
    if blocked and run["fix_round"] < max_rounds:
        db.log_event(run_id, REVIEWING, "system",
                     f"Blocking issues found ({'; '.join(reasons[:3])}). Sending to the Fix Agent "
                     f"(round {run['fix_round'] + 1} of {max_rounds}).")
        return FIXING
    if blocked:
        db.log_event(run_id, REVIEWING, "system",
                     f"Blocking issues remain but the fix limit ({max_rounds}) is reached. Going to release assessment.")
    return RELEASE_ASSESSMENT


def _failure_logs(run_id: int, round_no: int) -> str:
    """Read the FAILING check logs back from SQLite - this is what the Fix Agent works from."""
    rows = db.query("SELECT name, exit_code, summary, output FROM checks "
                    "WHERE run_id = ? AND round = ? AND status = 'failed' ORDER BY id", (run_id, round_no))
    return "\n\n".join(f"=== {r['name']} (exit code {r['exit_code']}) - {r['summary']} ===\n{(r['output'] or '')[-3000:]}"
                       for r in rows) or "No failing checks."


def _pending_human_comment(run_id: int) -> str:
    """Human instructions given since the last applied fix (from fix or release rejections)."""
    last_applied = db.query_one("SELECT MAX(created_at) AS t FROM changes WHERE run_id = ? AND status = 'applied'",
                                (run_id,))
    since = (last_applied or {}).get("t") or ""
    rows = db.query("SELECT comment FROM approvals WHERE run_id = ? AND decision = 'reject' "
                    "AND stage IN ('fix', 'release') AND created_at >= ? AND comment != '' ORDER BY id",
                    (run_id, since))
    return "\n".join(r["comment"] for r in rows)


def do_fix(run: dict) -> str:
    """Agent 6: Fix Agent proposes corrected files from the logs and findings stored in SQLite."""
    run_id, round_no = run["id"], run["fix_round"]
    next_round = round_no + 1
    db.log_event(run_id, FIXING, "fixer", f"Fix Agent is reading round {round_no} logs and findings from SQLite...")

    open_items = findings_service.open_findings(run_id)
    relevant = [{k: f[k] for k in ("source", "severity", "file", "line", "title", "evidence", "recommendation", "blocking")}
                for f in open_items if f["blocking"] or config.severity_at_least(f["severity"], "medium")]
    files = db.current_files(run_id)
    acs = [ac.model_dump() for ac in _analysis(run_id).acceptance_criteria]
    proposals = fixer.run(run_id, _failure_logs(run_id, round_no), relevant, files, acs,
                          _pending_human_comment(run_id))

    # Throw away earlier proposals for this round that were never applied.
    db.execute("UPDATE changes SET status = 'rejected' WHERE run_id = ? AND round = ? AND status = 'proposed'",
               (run_id, next_round))
    saved = 0
    for item in proposals:
        before = files.get(item["path"], "")
        if before == item["content"]:
            continue  # no real change
        diff = "".join(difflib.unified_diff(before.splitlines(True), item["content"].splitlines(True),
                                            fromfile=f"a/{item['path']}", tofile=f"b/{item['path']}"))
        change_id = db.execute(
            "INSERT INTO changes (run_id, round, file, before, after, diff, reason, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
            (run_id, next_round, item["path"], before, item["content"], diff, item.get("reason", ""), db.now()))
        db.log_event(run_id, FIXING, "fixer", f"Proposed change to {item['path']}: {item.get('reason') or 'see diff'}",
                     ref_type="change", ref_id=change_id)
        saved += 1

    if saved == 0:
        db.log_event(run_id, FIXING, "fixer", "The Fix Agent proposed no usable changes. Going to release assessment.")
        return RELEASE_ASSESSMENT
    if config.load_gates()["require_fix_approval"]:
        return AWAITING_FIX_APPROVAL
    apply_fix(run_id, approver="auto (require_fix_approval: false)")
    return CHECKING


def apply_fix(run_id: int, approver: str) -> None:
    """Apply the proposed changes as new file versions. Old check results become outdated."""
    run = db.get_run(run_id)
    next_round = run["fix_round"] + 1
    changes = db.query("SELECT * FROM changes WHERE run_id = ? AND round = ? AND status = 'proposed'",
                       (run_id, next_round))
    for change in changes:
        db.save_artifact(run_id, "file", change["file"], change["after"])
        db.execute("UPDATE changes SET status = 'applied' WHERE id = ?", (change["id"],))
    db.update_run(run_id, fix_round=next_round)
    db.log_event(run_id, FIXING, "system",
                 f"Applied {len(changes)} change(s) (approved by {approver}). Previous check results are now "
                 f"outdated - re-running all checks as round {next_round}.")


def do_release(run: dict) -> str:
    """Compute the gates and decision in CODE, then let Agent 7 explain it."""
    run_id = run["id"]
    db.log_event(run_id, RELEASE_ASSESSMENT, "system", "Calculating quality gates and traceability...")
    report = gates_service.evaluate(run_id)
    db.save_artifact(run_id, "traceability", "traceability", report["traceability"])
    try:
        explanation = release.run(run_id, report["decision"], report, report["traceability"])
    except Exception as exc:  # the decision stands even if the explanation fails
        explanation = f"(Explanation unavailable: {exc}) Decision computed from gate rules: {report['decision']}."
    artifact_id, _ = db.save_artifact(run_id, "release_report", "release_report", {
        "decision": report["decision"], "reasons": report["reasons"], "gates": report["gates"],
        "explanation": explanation, "fix_rounds_used": run["fix_round"], "rules": report["rules"],
    })
    db.update_run(run_id, decision=report["decision"])
    db.log_event(run_id, RELEASE_ASSESSMENT, "release",
                 f"Release recommendation: {report['decision']}", ref_type="artifact", ref_id=artifact_id)
    return AWAITING_RELEASE_APPROVAL


STAGE_HANDLERS = {
    ANALYZING: do_analysis,
    DESIGNING: do_design,
    DEVELOPING: do_develop,
    WRITING_TESTS: do_tests,
    CHECKING: do_checks,
    REVIEWING: do_review,
    FIXING: do_fix,
    RELEASE_ASSESSMENT: do_release,
}


# ---------------------------------------------------------------------------
# Human decisions from the dashboard
# ---------------------------------------------------------------------------
def handle_approval(run_id: int, request: ApprovalRequest) -> dict:
    """Record a human Approve / Reject and move the run to the right next stage."""
    run = db.get_run(run_id)
    if not run:
        raise ValueError("Run not found")
    stage = run["current_stage"]
    if stage not in WAITING_STAGES:
        raise ValueError(f"This run is not waiting for approval (current stage: {stage})")

    stage_key = {AWAITING_DESIGN_APPROVAL: "design", AWAITING_FIX_APPROVAL: "fix",
                 AWAITING_RELEASE_APPROVAL: "release"}[stage]
    if request.decision == "reject" and stage_key != "release" and not request.comment.strip():
        raise ValueError("Please write what should change when you reject.")

    version_kind = {"design": "design", "release": "release_report"}.get(stage_key)
    artifact = db.latest_artifact(run_id, version_kind) if version_kind else None
    target = request.target or ("design" if stage_key == "design" else None)
    db.execute(
        "INSERT INTO approvals (run_id, stage, artifact_version, decision, target, comment, approver, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, stage_key, artifact["version"] if artifact else run["fix_round"] + 1, request.decision,
         target, request.comment.strip(), request.approver, db.now()))
    db.log_event(run_id, stage, "human",
                 f"{request.approver} chose {request.decision.upper()} at {stage_key} stage"
                 + (f": {request.comment.strip()}" if request.comment.strip() else ""))

    # Decide where to go next.
    if stage_key == "design":
        if request.decision == "approve":
            next_stage = DEVELOPING
        else:
            next_stage = ANALYZING if target == "requirements" else DESIGNING
    elif stage_key == "fix":
        if request.decision == "approve":
            apply_fix(run_id, request.approver)
            next_stage = CHECKING
        else:
            db.execute("UPDATE changes SET status = 'rejected' WHERE run_id = ? AND status = 'proposed'", (run_id,))
            next_stage = FIXING  # Fix Agent tries again, using the human's comment
    else:  # release
        if request.decision == "approve":
            next_stage = COMPLETED
        elif request.comment.strip():
            # The human wants changes: record it as a blocking finding and send it to the Fix Agent.
            findings_service.add(run_id, run["fix_round"], "human", "high", "Change requested by reviewer",
                                 category="human_review", evidence=request.comment.strip(),
                                 recommendation=request.comment.strip(), blocking=True)
            next_stage = FIXING
        else:
            db.update_run(run_id, current_stage=COMPLETED, status="completed",
                          decision=f"{run['decision'] or 'NOT READY'} (rejected by {request.approver}: MANUAL REVIEW)")
            return db.get_run(run_id)

    db.update_run(run_id, current_stage=next_stage,
                  status="completed" if next_stage == COMPLETED else "running")
    if next_stage != COMPLETED:
        spawn(run_id)
    else:
        db.log_event(run_id, COMPLETED, "system", "Workflow complete. Final human approval recorded.")
    return db.get_run(run_id)
