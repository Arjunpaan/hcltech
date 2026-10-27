"""
agents/security.py - Security Review Agent.

Input : code + results from the deterministic security scanners (Bandit, secret scan).
Output: security findings. High-severity findings BLOCK release readiness
        (the blocking itself is decided by gates.yaml, not by the AI).
"""

from agents.base import ask_json, files_as_text
from models import ReviewResult

SYSTEM_PROMPT = """You are an application security reviewer.
Check: authentication, authorization, input validation, secrets exposure, SQL injection,
command injection, unsafe deserialization, dependency risks, logging of sensitive data,
insecure configuration.

Return ONLY JSON:
{"summary": "...", "findings": [{"severity": "low|medium|high|critical", "category": "...",
  "file": "...", "line": 0, "title": "...", "evidence": "...", "recommendation": "..."}]}
Use "high" only for issues that must block a release. Report only issues with evidence.
"""


def run(run_id: int, code_files: dict[str, str], scanner_summary: str) -> ReviewResult:
    """Return security findings for the current code."""
    user_prompt = f"Scanner results:\n{scanner_summary}\n\nCode:\n{files_as_text(code_files)}"
    return ask_json(run_id, "security", SYSTEM_PROMPT, user_prompt, ReviewResult)
