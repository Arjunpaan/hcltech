"""
services/runner.py - THE TEST ENGINE.

It runs real engineering tools on the generated project. No AI is involved here:
these results are facts, and the release decision is built on them.

Checks (in this order):
  1. syntax       python -m compileall   -> does every file compile?
  2. pytest       python -m pytest       -> do the generated tests pass? (each test case parsed)
  3. ruff         python -m ruff check   -> code-quality issues
  4. bandit       python -m bandit       -> security issues in app code
  5. secret_scan  built-in regex scan    -> passwords / API keys in code
  6. pip_audit    pip-audit (optional)   -> known-vulnerable dependencies

Every check is saved to the `checks` table with its command, exit code, FULL log
and parsed details. The dashboard links to each log, and the Fix Agent reads the
failing logs from SQLite to correct the code.

Safety:
  - local mode: runs in the run's own folder, with a time limit, and with an
    environment that contains NO secrets (API keys are not passed through).
  - docker mode: runs inside a container with no network and a memory/CPU cap.
  - A check that could not run is saved as "not_executed" with the reason.
    It is NEVER shown as passed.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import config
import db
from services import workspace

MAX_LOG_CHARS = 30000  # keep logs readable in the database and on screen


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_all(run_id: int, round_no: int) -> list[dict]:
    """Build the project folder, run every check, save results, return them."""
    gates = config.load_gates()
    folder = workspace.build(run_id)
    stage = "CHECKING"
    db.log_event(run_id, stage, "test_engine",
                 f"Round {round_no}: project written to {folder.name}/ - starting checks ({config.RUNNER_MODE} mode)")

    results = []
    for check in (check_syntax, check_pytest, check_ruff, check_bandit, check_secrets, check_pip_audit):
        db.log_event(run_id, stage, "test_engine", f"Running {check.__name__.replace('check_', '')} ...")
        result = check(folder, gates)
        result["id"] = _save(run_id, round_no, result)
        db.log_event(run_id, stage, "test_engine",
                     f"{result['name']}: {result['status'].upper()} - {result['summary']}",
                     ref_type="check", ref_id=result["id"])
        results.append(result)
    return results


def _save(run_id: int, round_no: int, result: dict) -> int:
    """Store one check result in SQLite and return its id."""
    return db.execute(
        "INSERT INTO checks (run_id, round, name, command, exit_code, status, summary, output, details, "
        "duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, round_no, result["name"], result.get("command"), result.get("exit_code"),
         result["status"], result.get("summary"), (result.get("output") or "")[-MAX_LOG_CHARS:],
         json.dumps(result.get("details") or {}), result.get("duration_ms"), db.now()),
    )


# ---------------------------------------------------------------------------
# How commands are executed (local or docker)
# ---------------------------------------------------------------------------
def _execute(args: list[str], folder: Path, timeout: int) -> dict:
    """
    Run one command and capture everything.
    Returns {'command', 'exit_code', 'output', 'duration_ms', 'error'}.
    """
    if config.RUNNER_MODE == "docker":
        if not shutil.which("docker"):
            return {"command": " ".join(args), "exit_code": None, "output": "",
                    "duration_ms": 0, "error": "Docker is not installed or not on PATH"}
        # python is the container's own interpreter; mount the project read-write at /work.
        inner = ["python" if a == sys.executable else a for a in args]
        args = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
                "-v", f"{folder.resolve()}:/work", "-w", "/work", config.RUNNER_IMAGE, *inner]

    started = time.time()
    try:
        completed = subprocess.run(
            args, cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=_clean_env(folder),
        )
        output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        return {"command": " ".join(args), "exit_code": completed.returncode, "output": output,
                "stdout": completed.stdout or "",
                "duration_ms": int((time.time() - started) * 1000), "error": None}
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {"command": " ".join(args), "exit_code": None, "output": partial,
                "duration_ms": int((time.time() - started) * 1000),
                "error": f"Stopped after {timeout} seconds (time limit)"}
    except FileNotFoundError as exc:
        return {"command": " ".join(args), "exit_code": None, "output": "",
                "duration_ms": 0, "error": f"Tool not found: {exc}"}


def _clean_env(folder: Path) -> dict:
    """An environment WITHOUT secrets: only what Python needs to run."""
    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "PATHEXT", "COMSPEC")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONPATH"] = str(folder)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _not_executed(name: str, reason: str, command: str = "") -> dict:
    """A check that could not run. Shown as NOT EXECUTED, never as passed."""
    return {"name": name, "status": "not_executed", "summary": f"Not executed: {reason}",
            "command": command, "exit_code": None, "output": reason, "details": {}, "duration_ms": 0}


def _py_files(folder: Path, sub: str | None = None) -> list[Path]:
    """All .py files of the project (or of one sub-folder)."""
    base = folder / sub if sub else folder
    if not base.exists():
        return []
    return [p for p in base.rglob("*.py") if ".reports" not in p.parts and "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# 1. Syntax check
# ---------------------------------------------------------------------------
def check_syntax(folder: Path, gates: dict) -> dict:
    """Does every Python file compile? (Build check for an interpreted language.)"""
    targets = [name for name in ("app", "tests") if (folder / name).exists()]
    run = _execute([sys.executable, "-m", "compileall", "-q", *targets], folder, gates["check_timeout_seconds"])
    if run["error"]:
        return _not_executed("syntax", run["error"], run["command"])
    passed = run["exit_code"] == 0
    return {"name": "syntax", "status": "passed" if passed else "failed",
            "summary": "All files compile" if passed else "Compilation errors found",
            "command": run["command"], "exit_code": run["exit_code"], "output": run["output"],
            "details": {}, "duration_ms": run["duration_ms"]}


# ---------------------------------------------------------------------------
# 2. Pytest (each test case is parsed from a JUnit XML report)
# ---------------------------------------------------------------------------
def check_pytest(folder: Path, gates: dict) -> dict:
    """Run the generated tests and record every single test case result."""
    if not _py_files(folder, "tests"):
        return _not_executed("pytest", "No test files were generated")
    report = folder / ".reports" / "junit.xml"
    report.parent.mkdir(exist_ok=True)
    run = _execute([sys.executable, "-m", "pytest", "--junitxml", ".reports/junit.xml", "-rA"],
                   folder, gates["check_timeout_seconds"])
    if run["error"]:
        return _not_executed("pytest", run["error"], run["command"])

    cases = _parse_junit(report)
    total = len(cases)
    passed = sum(1 for c in cases if c["outcome"] == "passed")
    failed = sum(1 for c in cases if c["outcome"] in ("failed", "error"))
    if total == 0:
        status, summary = "failed", "No tests were collected (pytest exit code %s)" % run["exit_code"]
    else:
        status = "passed" if failed == 0 and run["exit_code"] == 0 else "failed"
        summary = f"{passed}/{total} tests passed" + (f", {failed} failed" if failed else "")
    return {"name": "pytest", "status": status, "summary": summary, "command": run["command"],
            "exit_code": run["exit_code"], "output": run["output"],
            "details": {"total": total, "passed": passed, "failed": failed,
                        "pass_rate": round(passed / total, 3) if total else 0.0, "cases": cases},
            "duration_ms": run["duration_ms"]}


def _parse_junit(report: Path) -> list[dict]:
    """Read pytest's JUnit XML into [{'name', 'file', 'outcome', 'message'}]."""
    if not report.exists():
        return []
    cases = []
    for case in ET.parse(report).getroot().iter("testcase"):
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = "failed" if tag == "failure" else tag
                message = (node.get("message") or "") + "\n" + (node.text or "")
                break
        classname = case.get("classname", "")
        cases.append({"name": case.get("name", ""),
                      "file": classname.replace(".", "/") + ".py" if classname else "",
                      "outcome": outcome, "message": message.strip()[:2000]})
    return cases


# ---------------------------------------------------------------------------
# 3. Ruff (code quality)
# ---------------------------------------------------------------------------
def check_ruff(folder: Path, gates: dict) -> dict:
    """Static code-quality analysis. Each issue becomes a finding."""
    run = _execute([sys.executable, "-m", "ruff", "check", "--output-format", "json", "--no-cache", "."],
                   folder, gates["check_timeout_seconds"])
    if run["error"]:
        return _not_executed("ruff", run["error"], run["command"])
    try:
        issues = json.loads(run["stdout"].strip() or "[]")
    except json.JSONDecodeError:
        return _not_executed("ruff", "Could not read Ruff output: " + run["output"][:300], run["command"])
    simple = [{"code": i.get("code"), "message": i.get("message"),
               "file": _rel(folder, i.get("filename", "")),
               "line": (i.get("location") or {}).get("row")} for i in issues]
    return {"name": "ruff", "status": "passed" if not simple else "failed",
            "summary": "No quality issues" if not simple else f"{len(simple)} quality issue(s)",
            "command": run["command"], "exit_code": run["exit_code"], "output": run["output"],
            "details": {"issues": simple}, "duration_ms": run["duration_ms"]}


# ---------------------------------------------------------------------------
# 4. Bandit (security scanner) - application code only, not tests
# ---------------------------------------------------------------------------
def check_bandit(folder: Path, gates: dict) -> dict:
    """Deterministic security scan of the app/ folder."""
    if not _py_files(folder, "app"):
        return _not_executed("bandit", "No application files to scan")
    run = _execute([sys.executable, "-m", "bandit", "-r", "app", "-f", "json", "-q"],
                   folder, gates["check_timeout_seconds"])
    if run["error"]:
        return _not_executed("bandit", run["error"], run["command"])
    try:
        text = run["stdout"]
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return _not_executed("bandit", "Could not read Bandit output: " + run["output"][:300], run["command"])
    issues = [{"test_id": r.get("test_id"), "severity": str(r.get("issue_severity", "LOW")).lower(),
               "confidence": str(r.get("issue_confidence", "")).lower(), "message": r.get("issue_text"),
               "file": _rel(folder, r.get("filename", "")), "line": r.get("line_number"),
               "code": (r.get("code") or "").strip()[:300]} for r in data.get("results", [])]
    return {"name": "bandit", "status": "passed" if not issues else "failed",
            "summary": "No security issues" if not issues else f"{len(issues)} security issue(s)",
            "command": run["command"], "exit_code": run["exit_code"], "output": run["output"],
            "details": {"issues": issues}, "duration_ms": run["duration_ms"]}


# ---------------------------------------------------------------------------
# 5. Secret scan (built in, no external tool needed)
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    ("Hard-coded credential", re.compile(
        r"""(?i)\b\w*(api[_-]?key|secret|token|passw(or)?d|pwd)\w*\s*[:=]\s*["'][^"'\s]{6,}["']""")),
    ("API key pattern (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


def check_secrets(folder: Path, gates: dict) -> dict:
    """Look for passwords / API keys in application files (tests are skipped: they use fake data)."""
    started = time.time()
    hits = []
    for path in _py_files(folder, "app") + [p for p in folder.glob("*.*") if p.suffix in (".env", ".ini", ".txt")]:
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    hits.append({"file": _rel(folder, str(path)), "line": number, "type": label,
                                 "evidence": _mask(line.strip())})
                    break
    log = "\n".join(f"{h['file']}:{h['line']}  {h['type']}  {h['evidence']}" for h in hits) or "No secrets found."
    return {"name": "secret_scan", "status": "passed" if not hits else "failed",
            "summary": "No exposed credentials" if not hits else f"{len(hits)} possible secret(s)",
            "command": "built-in secret scanner (regex)", "exit_code": 0 if not hits else 1,
            "output": log, "details": {"hits": hits}, "duration_ms": int((time.time() - started) * 1000)}


def _mask(line: str) -> str:
    """Hide most of a secret so the log itself does not leak it."""
    return re.sub(r"""(["'])([^"']{4})[^"']*(["'])""", r"\1\2****\3", line)[:200]


# ---------------------------------------------------------------------------
# 6. pip-audit (optional dependency scan)
# ---------------------------------------------------------------------------
def check_pip_audit(folder: Path, gates: dict) -> dict:
    """Known-vulnerable dependencies. Needs internet, so it is optional."""
    if not gates.get("run_pip_audit"):
        return _not_executed("pip_audit", "Disabled in gates.yaml (run_pip_audit: false)")
    if not shutil.which("pip-audit"):
        return _not_executed("pip_audit", "pip-audit is not installed")
    run = _execute(["pip-audit", "-r", "requirements.txt", "-f", "json"], folder,
                   max(gates["check_timeout_seconds"], 120))
    if run["error"]:
        return _not_executed("pip_audit", run["error"], run["command"])
    try:
        text = run["stdout"]
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        vulns = [{"package": d.get("name"), "version": d.get("version"), "ids": [v.get("id") for v in d.get("vulns", [])]}
                 for d in data.get("dependencies", []) if d.get("vulns")]
    except (json.JSONDecodeError, ValueError):
        return _not_executed("pip_audit", "Could not read pip-audit output", run["command"])
    return {"name": "pip_audit", "status": "passed" if not vulns else "failed",
            "summary": "No known vulnerable dependencies" if not vulns else f"{len(vulns)} vulnerable package(s)",
            "command": run["command"], "exit_code": run["exit_code"], "output": run["output"],
            "details": {"vulnerabilities": vulns}, "duration_ms": run["duration_ms"]}


def _rel(folder: Path, filename: str) -> str:
    """Show paths relative to the project folder (app/main.py instead of a long path)."""
    try:
        return Path(filename).resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return filename.replace("\\", "/").lstrip("./")
