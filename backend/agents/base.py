"""
agents/base.py - Shared helpers for all agents.

Every agent is just: a system prompt (its job description) + a user prompt
(the facts it needs) -> one AI call -> a checked answer.

Two answer formats are used:
1. JSON (for requirements, design, review findings) - checked with Pydantic.
2. FILE BLOCKS (for code and tests), because code inside JSON often breaks:

       ### FILE: app/main.py
       ### REASON: why this file changed (fixer only, optional)
       ...file content...
       ### END FILE

If the answer cannot be read, we ask the AI ONE more time and tell it what was
wrong. If it fails again, the stage fails with a clear error (never a guess).
"""

import json
import re
from pathlib import PurePosixPath

from pydantic import BaseModel, ValidationError

import db
from services import llm

# The rules every code-writing agent must follow, so traceability works.
TRACE_RULES = (
    "Traceability rules:\n"
    "- Above every function or class that implements something, write a comment line like\n"
    "  '# Implements: AC-01, AC-02' using the acceptance-criteria IDs.\n"
    "- Test function names must contain the AC id, e.g. test_ac_01_valid_update_returns_200.\n"
)

FILE_FORMAT_RULES = (
    "Answer ONLY with file blocks in exactly this format (no other text, no markdown fences):\n"
    "### FILE: relative/path.py\n"
    "<full file content>\n"
    "### END FILE\n"
)


# ---------------------------------------------------------------------------
# JSON answers
# ---------------------------------------------------------------------------
def ask_json(run_id: int, agent: str, system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Ask the AI for JSON and return it as a checked Pydantic object (one retry)."""
    answer = llm.chat(run_id, agent, system_prompt, user_prompt, json_mode=True)
    try:
        return schema.model_validate(extract_json(answer))
    except (ValueError, ValidationError) as first_error:
        db.log_event(run_id, agent, agent, f"Answer was not valid JSON for {schema.__name__}; asking again.")
        retry_prompt = (
            f"{user_prompt}\n\nYour previous answer could not be used because: {str(first_error)[:800]}\n"
            "Reply again with ONLY the JSON object, matching the requested format exactly."
        )
        answer = llm.chat(run_id, agent, system_prompt, retry_prompt, json_mode=True)
        return schema.model_validate(extract_json(answer))


def extract_json(text: str) -> dict:
    """Pull the JSON object out of an AI answer, even if wrapped in ```json fences or chatter."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in the answer")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------------------
# File-block answers
# ---------------------------------------------------------------------------
def ask_files(run_id: int, agent: str, system_prompt: str, user_prompt: str) -> list[dict]:
    """Ask the AI for files; return [{'path', 'content', 'reason'}] (one retry if none found)."""
    answer = llm.chat(run_id, agent, system_prompt, user_prompt)
    files = parse_file_blocks(answer)
    if not files:
        db.log_event(run_id, agent, agent, "No files found in the answer; asking again.")
        answer = llm.chat(run_id, agent, system_prompt,
                          f"{user_prompt}\n\nYour previous answer had no usable file blocks.\n{FILE_FORMAT_RULES}")
        files = parse_file_blocks(answer)
    if not files:
        raise ValueError(f"{agent}: the AI did not return any files")
    return files


# Files the AI may NOT change: they define how the checks run, so changing them could hide failures.
PROTECTED_FILES = {"pytest.ini", "ruff.toml", "pyproject.toml", "setup.cfg", "tox.ini", ".ruff.toml"}

FILE_BLOCK = re.compile(r"^###\s*FILE:\s*(?P<path>[^\n]+)\n(?P<body>.*?)^###\s*END FILE\s*$",
                        re.DOTALL | re.MULTILINE)


def parse_file_blocks(text: str) -> list[dict]:
    """Read '### FILE: path ... ### END FILE' blocks. Unsafe paths are skipped."""
    files = []
    for match in FILE_BLOCK.finditer(text or ""):
        path = safe_path(match.group("path"))
        if not path or path in PROTECTED_FILES:
            continue
        body = match.group("body")
        reason = ""
        reason_match = re.match(r"###\s*REASON:\s*([^\n]*)\n", body)
        if reason_match:
            reason = reason_match.group(1).strip()
            body = body[reason_match.end():]
        files.append({"path": path, "content": strip_fences(body).rstrip() + "\n", "reason": reason})
    return files


def strip_fences(body: str) -> str:
    """Remove ```python fences if the AI wrapped the file content in them."""
    stripped = body.strip("\n")
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
    return body


def safe_path(raw: str) -> str | None:
    """
    Only allow simple relative paths inside the generated project
    (no absolute paths, no '..'), so the AI can never write outside its folder.
    """
    path = raw.strip().strip("`").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return None
    parts = PurePosixPath(path).parts
    if ".." in parts or any(part.startswith(".") for part in parts):
        return None
    if not re.match(r"^[\w\-./]+$", path):
        return None
    return path


# ---------------------------------------------------------------------------
# Small helpers for building prompts
# ---------------------------------------------------------------------------
def files_as_text(files: dict[str, str]) -> str:
    """Show files to the AI in the same block format it must answer in."""
    return "\n".join(f"### FILE: {path}\n{content.rstrip()}\n### END FILE" for path, content in files.items())


def as_json(data) -> str:
    """Pretty JSON for prompts."""
    return json.dumps(data, indent=2)
