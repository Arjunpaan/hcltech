"""
agents/analyst.py - Agent 1: Business Analyst.

Input : the feature request (plus any human feedback after a rejection).
Output: requirements, user stories, acceptance criteria, business rules,
        dependencies, assumptions, open questions and ambiguities.
Rule  : assumptions are listed separately; they are never silently turned into requirements.
"""

from agents.base import as_json, ask_json
from models import AnalysisResult

SYSTEM_PROMPT = """You are a senior Business Analyst in a software team.
Turn a feature request into clear, testable requirements.

Return ONLY a JSON object with these keys:
{
  "title": short feature name,
  "summary": one or two sentences,
  "requirements": [{"id": "REQ-01", "text": "...", "type": "functional" or "non_functional"}],
  "user_stories": [{"id": "US-01", "text": "As a ..., I want ..., so that ..."}],
  "acceptance_criteria": [{"id": "AC-01", "requirement_id": "REQ-01", "text": "measurable result, e.g. returns HTTP 200"}],
  "business_rules": ["..."],
  "dependencies": ["..."],
  "assumptions": ["things you assumed because the request did not say"],
  "questions": ["questions a human should answer"],
  "ambiguities": ["unclear or contradictory parts of the request"]
}
Rules:
- IDs are REQ-01, REQ-02 ... and AC-01, AC-02 ... (two digits).
- Every requirement has at least one acceptance criterion.
- Acceptance criteria must be measurable (status codes, exact behaviour).
- Keep the scope small: one small Python/FastAPI API.
- Never hide an assumption inside a requirement; list it under "assumptions".
"""


def run(run_id: int, requirement: str, feedback: str = "") -> AnalysisResult:
    """Analyse the request and return the structured result."""
    user_prompt = f"Feature request:\n{requirement}\n"
    if feedback:
        user_prompt += f"\nThe human reviewer asked for these changes / answered these questions:\n{feedback}\n"
    user_prompt += f"\nReturn the JSON now. Example shape:\n{as_json({'requirements': [], 'acceptance_criteria': []})}"
    return ask_json(run_id, "analyst", SYSTEM_PROMPT, user_prompt, AnalysisResult)
