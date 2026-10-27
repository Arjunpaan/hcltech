"""
db.py - The "diary" of the system, stored in one SQLite file.

Every important thing is written here:
- runs:       one row per feature request (and which stage it is in)
- artifacts:  everything the agents produce (requirements, design, code files...)
              Each save creates a new VERSION, so nothing is ever overwritten.
- checks:     every test-engine check (command, exit code, full log, pass/fail)
- findings:   every problem found (by tools or by AI reviewers)
- approvals:  every human decision (approve / reject + comment + time)
- events:     a live activity feed ("Developer agent wrote app/main.py")
- llm_calls:  every AI call (which agent, model, time taken, tokens)
- changes:    every AI code fix (before, after, diff, reason, status)
- llm_cache:  saved AI answers, reused to save tokens

The dashboard reads all of this, so everything the backend does is visible.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

import config

# One lock so two background threads never write at the same moment.
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT,
    requirement   TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    status        TEXT NOT NULL,          -- running | waiting_for_human | completed | failed
    fix_round     INTEGER NOT NULL DEFAULT 0,
    decision      TEXT,                   -- READY | CONDITIONAL | MANUAL REVIEW | NOT READY
    error         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    kind       TEXT NOT NULL,             -- analysis | design | file | test_mapping | review | security | release_report | traceability
    name       TEXT NOT NULL,             -- e.g. file path, or the kind again
    version    INTEGER NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL,
    round       INTEGER NOT NULL,         -- 0 = first check, 1 = after first fix, ...
    name        TEXT NOT NULL,            -- syntax | pytest | ruff | bandit | secret_scan | pip_audit
    command     TEXT,
    exit_code   INTEGER,
    status      TEXT NOT NULL,            -- passed | failed | not_executed
    summary     TEXT,
    output      TEXT,                     -- full log (shown via "view log" link)
    details     TEXT,                     -- JSON: parsed results (e.g. each test case)
    duration_ms INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    source         TEXT NOT NULL,         -- compiler | pytest | ruff | bandit | secret_scan | reviewer_agent | security_agent | human
    severity       TEXT NOT NULL,         -- low | medium | high | critical
    category       TEXT,
    file           TEXT,
    line           INTEGER,
    title          TEXT NOT NULL,
    evidence       TEXT,
    recommendation TEXT,
    blocking       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL,         -- open | superseded
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    stage            TEXT NOT NULL,       -- design | fix | release
    artifact_version INTEGER,
    decision         TEXT NOT NULL,       -- approve | reject
    target           TEXT,                -- where to go back to on reject
    comment          TEXT,
    approver         TEXT,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    stage      TEXT,
    actor      TEXT,                      -- system | <agent name> | test_engine | human
    message    TEXT NOT NULL,
    ref_type   TEXT,                      -- check | artifact | change | llm_call (for "view" links)
    ref_id     INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER,
    agent             TEXT,
    mode              TEXT,
    model             TEXT,
    prompt_chars      INTEGER,
    response_chars    INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    duration_ms       INTEGER,
    from_cache        INTEGER NOT NULL DEFAULT 0,
    ok                INTEGER NOT NULL,
    error             TEXT,
    prompt            TEXT,
    response          TEXT,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    round      INTEGER NOT NULL,          -- the fix round this change belongs to (1, 2, ...)
    file       TEXT NOT NULL,
    before     TEXT,
    after      TEXT NOT NULL,
    diff       TEXT,
    reason     TEXT,
    status     TEXT NOT NULL,             -- proposed | applied | rejected
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    """Current time as a readable ISO string (UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Open a new connection. Rows behave like dictionaries (row['name'])."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Create all tables if they do not exist yet."""
    with _write_lock:
        conn = connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """Run an INSERT / UPDATE / DELETE and return the new row id (for inserts)."""
    with _write_lock:
        conn = connect()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return a list of plain dictionaries."""
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """Run a SELECT and return the first row (or None)."""
    rows = query(sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def create_run(requirement: str, title: str, stage: str) -> int:
    """Insert a new run and return its id."""
    stamp = now()
    return execute(
        "INSERT INTO runs (title, requirement, current_stage, status, created_at, updated_at) "
        "VALUES (?, ?, ?, 'running', ?, ?)",
        (title, requirement, stage, stamp, stamp),
    )


def get_run(run_id: int) -> dict | None:
    """Fetch one run by id."""
    return query_one("SELECT * FROM runs WHERE id = ?", (run_id,))


def update_run(run_id: int, **fields: Any) -> None:
    """Change one or more columns of a run, e.g. update_run(5, status='failed')."""
    if not fields:
        return
    fields["updated_at"] = now()
    columns = ", ".join(f"{name} = ?" for name in fields)
    execute(f"UPDATE runs SET {columns} WHERE id = ?", (*fields.values(), run_id))


# ---------------------------------------------------------------------------
# Events (the live activity feed)
# ---------------------------------------------------------------------------
def log_event(run_id: int, stage: str, actor: str, message: str,
              ref_type: str | None = None, ref_id: int | None = None) -> int:
    """Write one line to the activity feed shown on the dashboard."""
    return execute(
        "INSERT INTO events (run_id, stage, actor, message, ref_type, ref_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, stage, actor, message, ref_type, ref_id, now()),
    )


# ---------------------------------------------------------------------------
# Artifacts (versioned outputs)
# ---------------------------------------------------------------------------
def save_artifact(run_id: int, kind: str, name: str, content: Any) -> tuple[int, int]:
    """
    Save an artifact as a NEW version. Dicts/lists are stored as JSON text.
    Returns (artifact_id, version).
    """
    text = content if isinstance(content, str) else json.dumps(content, indent=2)
    row = query_one(
        "SELECT MAX(version) AS v FROM artifacts WHERE run_id = ? AND kind = ? AND name = ?",
        (run_id, kind, name),
    )
    version = (row["v"] or 0) + 1
    artifact_id = execute(
        "INSERT INTO artifacts (run_id, kind, name, version, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, kind, name, version, text, now()),
    )
    return artifact_id, version


def latest_artifact(run_id: int, kind: str, name: str | None = None) -> dict | None:
    """Return the newest version of an artifact (content parsed from JSON when possible)."""
    name = name or kind
    row = query_one(
        "SELECT * FROM artifacts WHERE run_id = ? AND kind = ? AND name = ? ORDER BY version DESC LIMIT 1",
        (run_id, kind, name),
    )
    if row:
        row["data"] = _maybe_json(row["content"])
    return row


def current_files(run_id: int) -> dict[str, str]:
    """Return {file_path: newest content} for every generated code/test file."""
    rows = query(
        "SELECT a.name, a.content FROM artifacts a "
        "JOIN (SELECT name, MAX(version) AS v FROM artifacts WHERE run_id = ? AND kind = 'file' GROUP BY name) m "
        "ON a.name = m.name AND a.version = m.v "
        "WHERE a.run_id = ? AND a.kind = 'file' ORDER BY a.name",
        (run_id, run_id),
    )
    return {row["name"]: row["content"] for row in rows}


def _maybe_json(text: str) -> Any:
    """Turn JSON text back into Python objects; leave other text as it is."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
