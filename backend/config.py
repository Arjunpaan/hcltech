"""
config.py - All settings live here.

Two kinds of settings:
1. Environment settings (.env file): which AI model to use, API key, folders.
2. Quality-gate rules (gates.yaml): what counts as pass / fail.
   gates.yaml is read again every time we need it, so a change made while
   the app is running takes effect on the next check (live parameter change).
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent          # .../sdlc-copilot/backend
PROJECT_ROOT = BACKEND_DIR.parent                      # .../sdlc-copilot

# Load .env from the project root first, then from backend/ (either works).
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")

# ---------------------------------------------------------------------------
# AI model settings
# ---------------------------------------------------------------------------
# LLM_MODE:
#   "hosted" -> call a real API (OpenAI, Gemini, Groq, OpenRouter, Ollama...)
#   "mock"   -> use built-in canned answers (no internet, no tokens)
#   "replay" -> only reuse answers saved earlier from a hosted run (no tokens)
LLM_MODE = os.getenv("LLM_MODE", "mock").strip().lower()

# LLM_PROVIDER:
#   "openai" -> OpenAI (default) or any OpenAI-compatible API: Groq, OpenRouter, Ollama...
#   "gemini" -> Google Gemini's own API (generateContent), for Google AI Studio keys
#   "vertex" -> Google Vertex AI express mode
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
_DEFAULT_URL = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "vertex": "https://aiplatform.googleapis.com/v1/publishers/google",
}.get(LLM_PROVIDER, "https://api.openai.com/v1")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _DEFAULT_URL).rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest" if LLM_PROVIDER in ("gemini", "vertex") else "gpt-4.1-mini")
# If LLM_MODEL is not available to a key, these are tried in order (OpenAI only).
LLM_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "LLM_FALLBACK_MODELS", "gpt-4.1-mini,gpt-4o-mini,gpt-4.1,gpt-4o,gpt-5-mini,gpt-5").split(",") if m.strip()]
# Optional: only needed if your OpenAI key belongs to several organizations/projects.
LLM_ORGANIZATION = os.getenv("LLM_ORGANIZATION", "").strip()
LLM_PROJECT = os.getenv("LLM_PROJECT", "").strip()
# Only for OpenAI "reasoning" models (o-series, gpt-5...): low = faster answers. Leave empty otherwise.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "").strip().lower()
# How the Gemini key is sent: "api_key" (x-goog-api-key header), "query" (?key= in the URL)
# or "bearer" (Authorization: Bearer ...). scripts/test_llm.py --fix finds the one that works.
GEMINI_AUTH = os.getenv("GEMINI_AUTH", "api_key").strip().lower()
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Save every hosted answer so the same question never costs tokens twice.
LLM_CACHE = os.getenv("LLM_CACHE", "true").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Storage and test-engine settings
# ---------------------------------------------------------------------------
DB_PATH = Path(os.getenv("DB_PATH", str(BACKEND_DIR / "data" / "sdlc.db")))
GENERATED_DIR = Path(os.getenv("GENERATED_DIR", str(PROJECT_ROOT / "generated_projects")))
TEMPLATE_DIR = BACKEND_DIR / "templates" / "project"

# RUNNER_MODE:
#   "local"  -> run checks with this computer's Python, in the run's own folder,
#               with a time limit and with secrets removed from the environment.
#   "docker" -> run checks inside a locked-down container (no network, memory cap).
RUNNER_MODE = os.getenv("RUNNER_MODE", "local").strip().lower()
RUNNER_IMAGE = os.getenv("RUNNER_IMAGE", "sdlc-runner:latest")

# When true, the orchestrator runs stages in the same thread (used by tests).
RUN_SYNC = os.getenv("RUN_SYNC", "false").strip().lower() in ("1", "true", "yes")

GATES_FILE = Path(os.getenv("GATES_FILE", str(BACKEND_DIR / "gates.yaml")))

# Default gate rules. gates.yaml overrides any of these.
DEFAULT_GATES = {
    "max_fix_rounds": 2,                 # automatic correction attempts before giving up
    "require_fix_approval": True,        # human must approve each AI fix (FR-17)
    "min_test_pass_rate": 1.0,           # 1.0 = every test must pass
    "block_severity": "high",            # security findings at/above this block release
    "reviewer_block_severity": "high",   # reviewer findings at/above this block release
    "conditional_min_severity": "medium",  # open findings at/above this -> CONDITIONAL
    "max_ruff_issues": 0,                # style/quality issues allowed
    "ruff_blocking": False,              # if true, too many ruff issues block release
    "require_ac_test_mapping": True,     # every acceptance criterion needs a test
    "run_pip_audit": False,              # dependency scan (needs internet)
    "check_timeout_seconds": 60,         # stop any single check after this long
}


def load_gates() -> dict:
    """Read gates.yaml (if present) on top of the defaults and return the result."""
    gates = dict(DEFAULT_GATES)
    if GATES_FILE.exists():
        with open(GATES_FILE, "r", encoding="utf-8") as handle:
            from_file = yaml.safe_load(handle) or {}
        gates.update({k: v for k, v in from_file.items() if k in DEFAULT_GATES})
    return gates


def save_gates(new_values: dict) -> dict:
    """Update gates.yaml with new values (only known keys) and return the full set."""
    gates = load_gates()
    for key, value in new_values.items():
        if key in DEFAULT_GATES:
            gates[key] = value
    with open(GATES_FILE, "w", encoding="utf-8") as handle:
        yaml.safe_dump(gates, handle, sort_keys=False)
    return gates


# Severity ranking used everywhere so "high" > "medium" > "low".
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def severity_at_least(severity: str, threshold: str) -> bool:
    """True if `severity` is as bad as or worse than `threshold`."""
    return SEVERITY_RANK.get(str(severity).lower(), 0) >= SEVERITY_RANK.get(str(threshold).lower(), 3)
