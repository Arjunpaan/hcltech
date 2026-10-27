"""
agents/release.py - Agent 7: Release Assurance.

IMPORTANT: this agent does NOT decide. The decision (READY / CONDITIONAL /
MANUAL REVIEW / NOT READY) is calculated in services/gates.py from tool results.
This agent only explains the decision in plain words, using that evidence.
"""

from agents.base import as_json
from services import llm

SYSTEM_PROMPT = """You are a Release Assurance engineer.
You receive a release decision that was ALREADY CALCULATED by engineering rules, plus the evidence.
Explain it in 4-6 plain sentences for a manager: what passed, what failed, what is still open,
and what a human must do next. Do not change the decision. Do not invent evidence.
Always say that generated code needs human engineering review before production."""


def run(run_id: int, decision: str, gate_report: dict, traceability_rows: list[dict]) -> str:
    """Return a short plain-text explanation of the computed decision."""
    user_prompt = (
        f"DECISION: {decision}\n\n"
        f"Gate results:\n{as_json(gate_report.get('gates', []))}\n\n"
        f"Reasons:\n{as_json(gate_report.get('reasons', []))}\n\n"
        f"Traceability (requirement -> criterion -> code -> test -> result):\n{as_json(traceability_rows)}"
    )
    return llm.chat(run_id, "release", SYSTEM_PROMPT, user_prompt).strip()
