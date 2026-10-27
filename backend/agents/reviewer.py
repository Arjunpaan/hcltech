"""
agents/reviewer.py - Agent 5: Code Reviewer.

Input : code + test results + tool results (from the test engine).
Output: findings, each with Severity | Component(file) | Finding | Evidence | Recommended fix.
The reviewer gives opinions; the release decision still comes from the gate rules.
"""

from agents.base import ask_json, files_as_text
from models import ReviewResult

SYSTEM_PROMPT = """You are a strict senior code reviewer.
Look for: logic defects, missing validation, exception handling, maintainability,
duplicate logic, incorrect API behaviour, dead code, resource handling,
performance concerns and testability.

Return ONLY JSON:
{"summary": "...", "findings": [{"severity": "low|medium|high|critical", "category": "...",
  "file": "app/main.py", "line": 12, "title": "...", "evidence": "the exact code or test output",
  "recommendation": "the concrete fix"}]}
Only report real problems you can point to with evidence. An empty list is fine.
"""


def run(run_id: int, code_files: dict[str, str], tool_summary: str) -> ReviewResult:
    """Review the code and return findings."""
    user_prompt = f"Tool results from the test engine:\n{tool_summary}\n\nCode to review:\n{files_as_text(code_files)}"
    return ask_json(run_id, "reviewer", SYSTEM_PROMPT, user_prompt, ReviewResult)
