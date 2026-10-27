"""
Test setup for the PLATFORM's own tests.
Uses a temporary database, a temporary output folder, mock AI and synchronous runs,
so tests are fast, free and never touch your real data.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="sdlc_tests_"))

os.environ["DB_PATH"] = str(TMP / "test.db")
os.environ["GENERATED_DIR"] = str(TMP / "generated")
os.environ["LLM_MODE"] = "mock"
os.environ["RUN_SYNC"] = "true"
os.environ["RUNNER_MODE"] = "local"
os.environ["GATES_FILE"] = str(TMP / "gates.yaml")
shutil.copy(BACKEND / "gates.yaml", TMP / "gates.yaml")

sys.path.insert(0, str(BACKEND))

import db  # noqa: E402

db.init_db()
