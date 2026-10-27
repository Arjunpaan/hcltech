"""
check_setup.py - Checks and installs everything, then tests your AI key.

Run it from the project folder (sdlc-copilot/) in the VS Code terminal:

    python check_setup.py            (Windows: py check_setup.py also works)

What it does, step by step:
  1. Python version is 3.10 or newer
  2. Node.js and npm are installed (needed for the React dashboard)
  3. .env exists (copies .env.example) and has an API key (asks you to paste it)
  4. backend/.venv exists (creates it) and has all Python packages (installs them)
  5. frontend/node_modules exists (runs npm install)
  6. The platform's own tests pass
  7. The AI model really answers with your key (and fixes .env settings if needed)
Then it prints the exact commands to start the backend and the dashboard.

Only the Python standard library is used here, so it runs before anything is installed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
WINDOWS = os.name == "nt"
VENV = BACKEND / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
REQUIRED_IMPORTS = "fastapi, uvicorn, pydantic, httpx, dotenv, yaml, pytest, ruff, bandit"
problems: list[str] = []


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def ok(message: str) -> None:
    print(f"  [OK]   {message}")


def bad(message: str) -> None:
    print(f"  [FAIL] {message}")
    problems.append(message)


def run(args: list[str], cwd: Path, quiet: bool = False) -> int:
    """Run a command, show its output (unless quiet), return the exit code."""
    print(f"  > {' '.join(str(a) for a in args)}")
    result = subprocess.run([str(a) for a in args], cwd=cwd,
                            stdout=subprocess.DEVNULL if quiet else None,
                            stderr=subprocess.STDOUT if quiet else None)
    return result.returncode


def read_env() -> dict:
    """Read KEY=VALUE lines from .env."""
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def set_env(key: str, value: str) -> None:
    """Write one KEY=VALUE into .env (replace or add)."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    skip_tests = "--skip-tests" in sys.argv

    step("1. Python")
    if sys.version_info >= (3, 10):
        ok(f"Python {sys.version.split()[0]}")
    else:
        bad(f"Python {sys.version.split()[0]} is too old. Install Python 3.11 from python.org and re-run.")
        return 1

    step("2. Node.js and npm")
    node, npm = shutil.which("node"), shutil.which("npm")
    if node and npm:
        version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        ok(f"Node {version}, npm found")
    else:
        bad("Node.js/npm not found. Install Node 20 LTS from nodejs.org, reopen VS Code, re-run.")

    step("3. .env settings")
    if not ENV_FILE.exists():
        shutil.copy(ROOT / ".env.example", ENV_FILE)
        ok("Created .env from .env.example")
    env = read_env()
    if env.get("LLM_MODE", "mock") == "hosted" and not env.get("LLM_API_KEY"):
        key = input("  Paste your AI API key (OpenAI sk-... or Gemini) and press Enter (or just Enter for mock mode): ").strip()
        if key:
            set_env("LLM_API_KEY", key)
            if key.startswith("sk-"):
                set_env("LLM_PROVIDER", "openai")
                set_env("LLM_BASE_URL", "https://api.openai.com/v1")
                set_env("LLM_MODEL", "gpt-4.1-mini")
            else:
                set_env("LLM_PROVIDER", "gemini")
                set_env("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
                set_env("LLM_MODEL", "gemini-flash-latest")
            ok("API key saved in .env (this file is in .gitignore - never commit it)")
        else:
            set_env("LLM_MODE", "mock")
            ok("No key given: switched to LLM_MODE=mock (offline demo answers)")
    env = read_env()
    ok(f"LLM_MODE={env.get('LLM_MODE')} LLM_PROVIDER={env.get('LLM_PROVIDER', 'openai')} LLM_MODEL={env.get('LLM_MODEL')}")

    step("4. Python virtual environment + packages")
    if not VENV_PY.exists():
        if run([sys.executable, "-m", "venv", VENV], BACKEND) != 0:
            bad("Could not create backend/.venv")
            return 1
        ok("Created backend/.venv")
    else:
        ok("backend/.venv exists")
    has_packages = subprocess.run([str(VENV_PY), "-c", f"import {REQUIRED_IMPORTS}"],
                                  capture_output=True).returncode == 0
    if has_packages:
        ok("All Python packages are installed")
    else:
        print("  Installing Python packages (first time takes 1-2 minutes)...")
        run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip"], BACKEND, quiet=True)
        if run([VENV_PY, "-m", "pip", "install", "-r", "requirements.txt"], BACKEND) == 0:
            ok("Python packages installed")
        else:
            bad("pip install failed - read the error above (internet? proxy?)")

    step("5. Dashboard packages")
    if not npm:
        bad("Skipped: npm missing")
    elif (FRONTEND / "node_modules").exists():
        ok("frontend/node_modules exists")
    elif run([npm, "install", "--no-audit", "--no-fund"], FRONTEND) == 0:
        ok("npm install finished")
    else:
        bad("npm install failed - read the error above")

    step("6. Platform self-tests (mock AI, real tools)")
    if skip_tests:
        ok("Skipped (--skip-tests)")
    elif run([VENV_PY, "-m", "pytest", "tests", "-q", "-p", "no:warnings"], BACKEND) == 0:
        ok("All platform tests passed")
    else:
        bad("Some platform tests failed - see above")

    step("7. AI model connection")
    if read_env().get("LLM_MODE") == "hosted":
        if run([VENV_PY, "scripts/test_llm.py", "--fix"], BACKEND) == 0:
            ok("The AI model answered")
        else:
            bad("The AI model did not answer - see the message above. You can still demo with LLM_MODE=mock.")
    else:
        ok("Mock mode - no AI call needed")

    step("Result")
    if problems:
        print("  Fix these, then run check_setup.py again:")
        for item in problems:
            print(f"   - {item}")
    else:
        print("  Everything is ready.")
    venv_python = r".venv\Scripts\python" if WINDOWS else ".venv/bin/python"
    print(f"""
  Start the app in TWO VS Code terminals (Terminal > New Terminal):

  Terminal 1 - backend (API on http://localhost:8000, docs at /docs):
      cd backend
      {venv_python} -m uvicorn main:app --port 8000

  Terminal 2 - dashboard (open http://localhost:5173):
      cd frontend
      npm run dev
""")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
