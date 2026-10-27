"""
services/traceability.py - Requirement -> Acceptance criterion -> Code -> Test -> Result.

How the links are found (no AI guessing):
- Code:  comments like "# Implements: AC-01, REQ-02" placed above a function/class.
- Tests: test names that contain the AC id, e.g. test_ac_03_invalid_phone_returns_422.
- Result: the pytest case results saved by the test engine.

Example row:
  REQ-02 | AC-03 invalid phone returns 422 | app/main.py -> update_contact() |
  tests/test_contact.py -> test_ac_03_invalid_phone_returns_422 | PASSED
"""

import json
import re

import db

IMPLEMENTS = re.compile(r"#\s*Implements:\s*(.+)", re.IGNORECASE)
DEFINITION = re.compile(r"^\s*(?:async\s+)?(def|class)\s+(\w+)")
ID_PATTERN = re.compile(r"\b(REQ|AC)-?(\d+)\b", re.IGNORECASE)
TEST_AC = re.compile(r"ac_?0*(\d+)", re.IGNORECASE)


def _norm(prefix: str, number: str | int) -> str:
    """'ac', '3' -> 'AC-03' so IDs always look the same."""
    return f"{prefix.upper()}-{int(number):02d}"


def implementation_map(files: dict[str, str]) -> dict[str, list[str]]:
    """Find '# Implements:' comments and the function/class that follows each one."""
    found: dict[str, list[str]] = {}
    for path, content in files.items():
        if not path.startswith("app/"):
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            match = IMPLEMENTS.search(line)
            if not match:
                continue
            target = "module"
            for following in lines[index + 1:index + 8]:  # look a few lines down for the def/class
                definition = DEFINITION.match(following)
                if definition:
                    target = f"{definition.group(2)}()" if definition.group(1) == "def" else definition.group(2)
                    break
            for prefix, number in ID_PATTERN.findall(match.group(1)):
                found.setdefault(_norm(prefix, number), []).append(f"{path} -> {target}")
    return found


def latest_test_cases(run_id: int) -> tuple[list[dict], str]:
    """Test cases from the newest pytest check, plus that check's status."""
    check = db.query_one("SELECT * FROM checks WHERE run_id = ? AND name = 'pytest' ORDER BY id DESC LIMIT 1",
                         (run_id,))
    if not check:
        return [], "missing"
    details = json.loads(check["details"] or "{}")
    return details.get("cases", []), check["status"]


def build(run_id: int) -> list[dict]:
    """Return one row per acceptance criterion."""
    analysis = db.latest_artifact(run_id, "analysis")
    if not analysis:
        return []
    data = analysis["data"]
    requirements = {r["id"].upper(): r for r in data.get("requirements", [])}
    impl = implementation_map(db.current_files(run_id))
    cases, pytest_status = latest_test_cases(run_id)

    rows = []
    for ac in data.get("acceptance_criteria", []):
        ac_num = int(re.sub(r"\D", "", ac["id"]) or 0)
        ac_id = _norm("AC", ac_num)
        req_id = _norm("REQ", re.sub(r"\D", "", ac.get("requirement_id", "0")) or 0)
        tests = [c for c in cases if (m := TEST_AC.search(c["name"])) and int(m.group(1)) == ac_num]
        code = impl.get(ac_id, []) or impl.get(req_id, [])

        if pytest_status == "not_executed":
            result = "NOT EXECUTED"
        elif not tests:
            result = "NOT TESTED"
        elif all(t["outcome"] == "passed" for t in tests):
            result = "PASSED"
        else:
            result = "FAILED"

        rows.append({
            "requirement_id": req_id,
            "requirement": (requirements.get(req_id) or requirements.get(ac.get("requirement_id", "").upper()) or {}).get("text", ""),
            "acceptance_criterion_id": ac_id,
            "acceptance_criterion": ac.get("text", ""),
            "implementation": code,
            "tests": [{"name": t["name"], "file": t.get("file", ""), "outcome": t["outcome"]} for t in tests],
            "result": result,
        })
    return rows
