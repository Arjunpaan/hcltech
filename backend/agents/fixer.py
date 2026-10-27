"""
agents/fixer.py - Agent 6: Defect Resolution (Fix) Agent.

Input : the failure LOGS and findings read back from SQLite + the current code.
Output: changed files, each with a reason. The orchestrator saves every change
        (before / after / diff) and, if gates.yaml says so, waits for a human to
        approve before applying it. Then the test engine runs again.
"""

from agents.base import FILE_FORMAT_RULES, as_json, ask_files, files_as_text

SYSTEM_PROMPT = f"""You are a Defect Resolution engineer.
You get: failing check logs, open findings, and the current files.
For each problem: find the probable cause, find the affected code, and fix it.

Rules:
- Return ONLY the files you change, each COMPLETE (not a diff).
- Right after each '### FILE:' line, add one line '### REASON: <what you fixed and which finding/test>'.
- Keep every existing '# Implements: AC-xx' comment.
- Fix the APPLICATION when a test proves the acceptance criterion is not met.
  Change a test only if the test itself contradicts the acceptance criteria.
- Never remove a test to make the build pass. Never add secrets.
{FILE_FORMAT_RULES}"""


def run(run_id: int, failure_logs: str, findings: list[dict], files: dict[str, str],
        acceptance_criteria: list[dict], human_comment: str = "") -> list[dict]:
    """Return a list of {'path', 'content', 'reason'} corrected files."""
    user_prompt = (
        f"Acceptance criteria:\n{as_json(acceptance_criteria)}\n\n"
        f"Failing checks (from the test-engine logs):\n{failure_logs}\n\n"
        f"Open findings:\n{as_json(findings)}\n\n"
    )
    if human_comment:
        user_prompt += f"Human reviewer instructions:\n{human_comment}\n\n"
    user_prompt += f"Current files:\n{files_as_text(files)}\n\nReturn the corrected files now."
    return ask_files(run_id, "fixer", SYSTEM_PROMPT, user_prompt)
