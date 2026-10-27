"""
agents/designer.py - Agent 2: Solution Designer.

Input : the analysed requirements (plus human feedback after a rejection).
Output: components, API endpoints, data models, validation, error handling,
        logging, security notes and the file structure.
A human must approve this design before any code is written.
"""

from agents.base import as_json, ask_json
from models import AnalysisResult, DesignResult

SYSTEM_PROMPT = """You are a Solution Architect. Design a SMALL Python FastAPI service.

Return ONLY a JSON object with these keys:
{
  "overview": "...",
  "components": ["..."],
  "endpoints": [{"method": "PUT", "path": "/...", "description": "...", "request_model": "...",
                 "response_model": "...", "status_codes": ["200 ...", "422 ..."]}],
  "data_models": [{"name": "...", "fields": ["name: type (rules)"]}],
  "validation_rules": ["..."],
  "error_handling": ["..."],
  "logging": ["..."],
  "security": ["..."],
  "file_structure": ["app/main.py", "app/models.py", "app/storage.py", "tests/test_<feature>.py"]
}
Constraints for the code that will be generated from this design:
- Python 3.11, FastAPI, Pydantic v2 only. No database server: use an in-memory store in app/storage.py.
- The FastAPI object must be called `app` in app/main.py.
- No external network calls, no secrets in code.
"""


def run(run_id: int, analysis: AnalysisResult, feedback: str = "") -> DesignResult:
    """Produce a technical design from the approved requirements."""
    user_prompt = f"Approved requirements:\n{as_json(analysis.model_dump())}\n"
    if feedback:
        user_prompt += f"\nHuman feedback to apply:\n{feedback}\n"
    return ask_json(run_id, "designer", SYSTEM_PROMPT, user_prompt, DesignResult)
