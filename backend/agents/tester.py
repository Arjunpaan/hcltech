"""
agents/tester.py - Agent 4: Test Engineer.

Input : requirements + acceptance criteria + design + generated code.
Output: pytest test files. Every test name contains its AC id
        (test_ac_03_invalid_phone_returns_422) so the platform can map
        tests back to acceptance criteria automatically.
Covers positive, negative, boundary, validation, authorization and error tests.
"""

from agents.base import FILE_FORMAT_RULES, TRACE_RULES, as_json, ask_files, files_as_text
from models import AnalysisResult, DesignResult

SYSTEM_PROMPT = f"""You are a Test Engineer. Write pytest tests for a FastAPI app.

Rules:
- Put tests in tests/test_<feature>.py.
- Use `from fastapi.testclient import TestClient` and `from app.main import app`.
- Write AT LEAST one test per acceptance criterion; test names must include the AC id.
- Include positive, negative, boundary, validation, authorization and error-response tests.
- If app/storage.py has reset(), call it in an autouse fixture so each test starts clean.
- Tests must not use the network or real secrets.
- Test what the ACCEPTANCE CRITERIA say, not what the code happens to do.
{TRACE_RULES}
{FILE_FORMAT_RULES}"""


def run(run_id: int, analysis: AnalysisResult, design: DesignResult, code_files: dict[str, str]) -> list[dict]:
    """Return a list of {'path', 'content'} test files."""
    user_prompt = (
        f"Acceptance criteria:\n{as_json([ac.model_dump() for ac in analysis.acceptance_criteria])}\n\n"
        f"Design endpoints:\n{as_json([e.model_dump() for e in design.endpoints])}\n\n"
        f"Application code:\n{files_as_text(code_files)}\n\nWrite the test files now."
    )
    files = ask_files(run_id, "tester", SYSTEM_PROMPT, user_prompt)
    return [f for f in files if f["path"].startswith("tests/")]
