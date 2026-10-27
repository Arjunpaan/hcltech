"""
services/findings.py - Turn test-engine results and agent reviews into "findings".

A finding = one problem with: source, severity, file, line, title, evidence,
recommended fix, and whether it BLOCKS the release (decided by gates.yaml).

Each check round starts fresh: findings from older rounds are marked
"superseded", because the code they talked about has changed.
"""

import config
import db


def supersede_old(run_id: int, current_round: int) -> None:
    """Close findings from earlier rounds: the code has changed since then."""
    db.execute("UPDATE findings SET status = 'superseded' WHERE run_id = ? AND round < ? AND status = 'open'",
               (run_id, current_round))


def add(run_id: int, round_no: int, source: str, severity: str, title: str, *, category: str = "",
        file: str = "", line: int | None = None, evidence: str = "", recommendation: str = "",
        blocking: bool = False) -> int:
    """Insert one finding and return its id."""
    return db.execute(
        "INSERT INTO findings (run_id, round, source, severity, category, file, line, title, evidence, "
        "recommendation, blocking, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
        (run_id, round_no, source, severity, category, file, line, title, (evidence or "")[:2000],
         recommendation, 1 if blocking else 0, db.now()),
    )


def from_checks(run_id: int, round_no: int, checks: list[dict]) -> int:
    """Create findings from the tool results. Returns how many were created."""
    gates = config.load_gates()
    count = 0
    for check in checks:
        name, details = check["name"], check.get("details") or {}

        if name == "syntax" and check["status"] == "failed":
            add(run_id, round_no, "compiler", "high", "Code does not compile", category="build",
                evidence=check.get("output", "")[-1500:], recommendation="Fix the syntax error shown in the log.",
                blocking=True)
            count += 1

        elif name == "pytest" and check["status"] == "failed":
            failing = [c for c in details.get("cases", []) if c["outcome"] in ("failed", "error")]
            if not failing:  # e.g. no tests collected
                add(run_id, round_no, "pytest", "high", check["summary"], category="tests",
                    evidence=check.get("output", "")[-1500:], blocking=True)
                count += 1
            for case in failing:
                add(run_id, round_no, "pytest", "high", f"Test failed: {case['name']}", category="tests",
                    file=case.get("file", ""), evidence=case.get("message", ""),
                    recommendation="Make the application meet the acceptance criterion this test checks.",
                    blocking=True)
                count += 1

        elif name == "ruff":
            for issue in details.get("issues", []):
                # F-codes (pyflakes) are real bugs like undefined names; others are style.
                severity = "medium" if str(issue.get("code", "")).startswith("F") else "low"
                add(run_id, round_no, "ruff", severity, f"{issue.get('code')}: {issue.get('message')}",
                    category="quality", file=issue.get("file", ""), line=issue.get("line"),
                    recommendation="Follow the Ruff rule.", blocking=bool(gates["ruff_blocking"]))
                count += 1

        elif name == "bandit":
            for issue in details.get("issues", []):
                severity = issue.get("severity", "low")
                add(run_id, round_no, "bandit", severity, f"{issue.get('test_id')}: {issue.get('message')}",
                    category="security", file=issue.get("file", ""), line=issue.get("line"),
                    evidence=issue.get("code", ""), recommendation="See the Bandit rule documentation.",
                    blocking=config.severity_at_least(severity, gates["block_severity"]))
                count += 1

        elif name == "secret_scan":
            for hit in details.get("hits", []):
                add(run_id, round_no, "secret_scan", "high", f"Exposed credential: {hit['type']}",
                    category="secrets", file=hit["file"], line=hit["line"], evidence=hit["evidence"],
                    recommendation="Remove the secret from code; load it from the environment and rotate it.",
                    blocking=True)
                count += 1

        elif name == "pip_audit":
            for vuln in details.get("vulnerabilities", []):
                add(run_id, round_no, "pip_audit", "high", f"Vulnerable dependency: {vuln['package']}",
                    category="dependencies", evidence=", ".join(vuln.get("ids") or []),
                    recommendation="Upgrade to a fixed version.",
                    blocking=config.severity_at_least("high", gates["block_severity"]))
                count += 1
    return count


def from_agent(run_id: int, round_no: int, source: str, review) -> int:
    """Store the Reviewer / Security agent findings. Blocking is decided by gates.yaml."""
    gates = config.load_gates()
    threshold = gates["block_severity"] if source == "security_agent" else gates["reviewer_block_severity"]
    for item in review.findings:
        add(run_id, round_no, source, item.severity, item.title, category=item.category, file=item.file,
            line=item.line, evidence=item.evidence, recommendation=item.recommendation,
            blocking=config.severity_at_least(item.severity, threshold))
    return len(review.findings)


def open_findings(run_id: int) -> list[dict]:
    """All findings that still apply to the current code."""
    return db.query("SELECT * FROM findings WHERE run_id = ? AND status = 'open' ORDER BY blocking DESC, id",
                    (run_id,))
