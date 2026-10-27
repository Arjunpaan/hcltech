"""
agents/developer.py - Agent 3: Developer.

Input : approved design + acceptance criteria.
Output: application files (app/...). It fills our fixed project template,
        so the code always has the same shape and runs more reliably.
Generated code is NEVER classified as production-ready.
"""

from agents.base import FILE_FORMAT_RULES, TRACE_RULES, as_json, ask_files
from models import AnalysisResult, DesignResult

SYSTEM_PROMPT = f"""You are a careful Python developer.
Write a small FastAPI application from the approved design.

Fixed project template (already exists, do not change): pytest.ini, requirements.txt, app/__init__.py.
You must write:
- app/main.py with the FastAPI object named `app`
- any other modules under app/ that the design lists (e.g. app/models.py, app/storage.py)

Coding rules:
- Python 3.11, FastAPI, Pydantic v2. Only standard library + fastapi + pydantic.
- Validate input with Pydantic, use HTTPException with a clear 'detail' for errors.
- No secrets, tokens or passwords in code. No network calls. No print statements.
- Add a short docstring to every module and function.
- If you need sample data, put it in app/storage.py with a reset() function that restores it.
{TRACE_RULES}
{FILE_FORMAT_RULES}"""


def run(run_id: int, analysis: AnalysisResult, design: DesignResult) -> list[dict]:
    """Return a list of {'path', 'content'} application files."""
    user_prompt = (
        f"Acceptance criteria:\n{as_json([ac.model_dump() for ac in analysis.acceptance_criteria])}\n\n"
        f"Approved design:\n{as_json(design.model_dump())}\n\nWrite the application files now."
    )
    files = ask_files(run_id, "developer", SYSTEM_PROMPT, user_prompt)
    if not any(f["path"] == "app/main.py" for f in files):
        # The tests and the template expect app/main.py, so ask once more, very explicitly.
        files = ask_files(run_id, "developer", SYSTEM_PROMPT,
                          user_prompt + "\n\nIMPORTANT: your previous answer had no app/main.py. The FastAPI "
                          "object `app` must be defined in a file block named exactly app/main.py.")
    # The developer only writes application code; tests belong to the Test Engineer.
    return [f for f in files if not f["path"].startswith("tests/")]
