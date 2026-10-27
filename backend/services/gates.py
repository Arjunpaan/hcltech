"""
services/gates.py - Quality gates and the release decision.

"AI generates. Engineering tools validate. Humans govern."
The decision is CALCULATED here from facts (tool results, findings, approvals)
using the rules in gates.yaml. The Release Agent only explains it.

Gates:
  Requirement gate  - acceptance criteria exist for every requirement, ambiguities listed
  Code gate         - code compiles, quality issues within the limit
  Test gate         - tests executed, pass rate >= minimum, every AC has a test
  Security gate     - no blocking security finding, no exposed credentials, scanners ran
  Traceability gate - requirement -> code -> test -> result complete
  Approval gate     - the design was approved by a human

Decision rules (in this order):
  NOT READY      - code does not compile, mandatory tests fail, or a blocking security issue
  MANUAL REVIEW  - a required check did not run, or a required approval is missing
  CONDITIONAL    - only non-blocking concerns remain
  READY          - every gate passed
"""

import json

import config
import db
from services import findings as findings_service
from services import traceability


def _latest_checks(run_id: int) -> dict[str, dict]:
    """Newest result of each check type for this run."""
    rows = db.query("SELECT * FROM checks WHERE run_id = ? ORDER BY id", (run_id,))
    latest: dict[str, dict] = {}
    for row in rows:
        latest[row["name"]] = row  # later rows replace earlier ones
    return latest


def _gate(name: str, status: str, reason: str, blocking: bool) -> dict:
    """One row of the gate table. status: passed | failed | not_executed."""
    return {"gate": name, "status": status, "reason": reason, "blocking": blocking}


def evaluate(run_id: int) -> dict:
    """Compute every gate and the release decision. Returns a full report."""
    rules = config.load_gates()
    checks = _latest_checks(run_id)
    open_items = findings_service.open_findings(run_id)
    trace_rows = traceability.build(run_id)
    analysis = (db.latest_artifact(run_id, "analysis") or {}).get("data") or {}
    gates = []

    # --- Requirement gate -------------------------------------------------
    reqs = {r["id"] for r in analysis.get("requirements", [])}
    covered = {ac.get("requirement_id") for ac in analysis.get("acceptance_criteria", [])}
    missing = sorted(reqs - covered)
    gates.append(_gate("Requirement", "failed" if (not reqs or missing) else "passed",
                       f"Requirements without acceptance criteria: {missing}" if missing else
                       f"{len(reqs)} requirements, {len(covered)} covered; "
                       f"{len(analysis.get('assumptions', []))} assumptions and "
                       f"{len(analysis.get('questions', []))} questions listed", blocking=False))

    # --- Code gate --------------------------------------------------------
    syntax, ruff = checks.get("syntax"), checks.get("ruff")
    ruff_count = len(json.loads(ruff["details"] or "{}").get("issues", [])) if ruff else 0
    if not syntax or syntax["status"] == "not_executed":
        gates.append(_gate("Code", "not_executed", "Build/syntax check did not run", True))
    elif syntax["status"] == "failed":
        gates.append(_gate("Code", "failed", "Code does not compile", True))
    elif not ruff or ruff["status"] == "not_executed":
        gates.append(_gate("Code", "not_executed", "Static analysis (Ruff) did not run", True))
    elif ruff_count > rules["max_ruff_issues"]:
        gates.append(_gate("Code", "failed", f"{ruff_count} Ruff issues (limit {rules['max_ruff_issues']})",
                           bool(rules["ruff_blocking"])))
    else:
        gates.append(_gate("Code", "passed", f"Compiles; {ruff_count} Ruff issues (limit {rules['max_ruff_issues']})", True))

    # --- Test gate --------------------------------------------------------
    pytest_check = checks.get("pytest")
    if not pytest_check or pytest_check["status"] == "not_executed":
        gates.append(_gate("Test", "not_executed", "Tests were not executed", True))
    else:
        details = json.loads(pytest_check["details"] or "{}")
        rate, total = details.get("pass_rate", 0.0), details.get("total", 0)
        unmapped = [r["acceptance_criterion_id"] for r in trace_rows if not r["tests"]]
        problems = []
        if total == 0:
            problems.append("no tests collected")
        if rate < rules["min_test_pass_rate"]:
            problems.append(f"pass rate {rate:.0%} below minimum {rules['min_test_pass_rate']:.0%}")
        if rules["require_ac_test_mapping"] and unmapped:
            problems.append(f"acceptance criteria without tests: {unmapped}")
        gates.append(_gate("Test", "failed" if problems else "passed",
                           "; ".join(problems) if problems else
                           f"{details.get('passed', 0)}/{total} passed; every AC has a test", True))

    # --- Security gate ----------------------------------------------------
    security_sources = ("bandit", "secret_scan", "security_agent", "pip_audit")
    blocking_security = [f for f in open_items if f["source"] in security_sources and f["blocking"]]
    not_run = [name for name in ("bandit", "secret_scan") if not checks.get(name) or checks[name]["status"] == "not_executed"]
    if blocking_security:
        gates.append(_gate("Security", "failed",
                           f"{len(blocking_security)} blocking security finding(s): "
                           + "; ".join(f["title"] for f in blocking_security[:3]), True))
    elif not_run:
        gates.append(_gate("Security", "not_executed", f"Required security checks did not run: {not_run}", True))
    else:
        gates.append(_gate("Security", "passed", "No blocking security findings; no exposed credentials", True))

    # --- Traceability gate ------------------------------------------------
    incomplete = [r["acceptance_criterion_id"] for r in trace_rows
                  if not r["implementation"] or r["result"] in ("NOT TESTED", "NOT EXECUTED")]
    if not trace_rows:
        gates.append(_gate("Traceability", "failed", "No acceptance criteria to trace", False))
    else:
        gates.append(_gate("Traceability", "failed" if incomplete else "passed",
                           f"Incomplete links for: {incomplete}" if incomplete else
                           f"All {len(trace_rows)} acceptance criteria linked to code, tests and results", False))

    # --- Approval gate ----------------------------------------------------
    design_ok = db.query_one("SELECT id FROM approvals WHERE run_id = ? AND stage = 'design' AND decision = 'approve'",
                             (run_id,))
    gates.append(_gate("Approval", "passed" if design_ok else "failed",
                       "Design approved by a human" if design_ok else "Design approval missing", True))

    # --- Decision ---------------------------------------------------------
    decision, reasons = _decide(gates, open_items, rules)
    blocking_findings = [f for f in open_items if f["blocking"]]
    return {
        "decision": decision,
        "reasons": reasons,
        "gates": gates,
        "open_findings": open_items,
        "blocking_findings": blocking_findings,
        "traceability": trace_rows,
        "rules": rules,
    }


def _decide(gates: list[dict], open_items: list[dict], rules: dict) -> tuple[str, list[str]]:
    """Apply the decision rules in order and say why."""
    by_name = {g["gate"]: g for g in gates}
    reasons = []

    hard_fail = [g for g in gates if g["status"] == "failed" and g["blocking"]]
    if hard_fail:
        reasons = [f"{g['gate']} gate failed: {g['reason']}" for g in hard_fail]
        return "NOT READY", reasons

    blocking_open = [f for f in open_items if f["blocking"]]
    if blocking_open:
        reasons = [f"Unresolved blocking finding: {f['title']} ({f['source']})" for f in blocking_open[:5]]
        return "NOT READY", reasons

    missing = [g for g in gates if g["status"] == "not_executed" and g["blocking"]]
    if missing or by_name.get("Approval", {}).get("status") != "passed":
        reasons = [f"{g['gate']} gate: {g['reason']}" for g in missing]
        if by_name.get("Approval", {}).get("status") != "passed":
            reasons.append("Required human design approval is missing")
        return "MANUAL REVIEW", reasons

    concerns = [f"{g['gate']} gate: {g['reason']}" for g in gates if g["status"] != "passed"]
    concerns += [f"Open {f['severity']} finding: {f['title']} ({f['source']})" for f in open_items
                 if config.severity_at_least(f["severity"], rules["conditional_min_severity"])]
    if concerns:
        return "CONDITIONAL", concerns

    return "READY", ["All mandatory gates passed and the design was approved"]


def has_blocking_issues(run_id: int) -> tuple[bool, list[str]]:
    """Used by the fix loop: is there anything the Fix Agent should try to fix?"""
    report = evaluate(run_id)
    if report["decision"] == "NOT READY":
        return True, report["reasons"]
    return False, []
