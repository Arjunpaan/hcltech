"""
services/workspace.py - The isolated folder for each run's generated project.

generated_projects/run_<id>/ is rebuilt from SQLite every time we check:
template files first, then the newest version of every generated file.
So the folder always matches exactly what the database says the code is.
"""

import io
import shutil
import zipfile
from pathlib import Path

import config
import db


def run_dir(run_id: int) -> Path:
    """Folder for one run's generated project."""
    return config.GENERATED_DIR / f"run_{run_id}"


def build(run_id: int) -> Path:
    """Recreate the project folder from the template + newest files in SQLite."""
    target = run_dir(run_id)
    # If the generated app is running from this folder, stop it first (Windows locks open folders).
    from services import preview
    preview.stop(run_id)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(config.TEMPLATE_DIR, target)
    for rel_path, content in db.current_files(run_id).items():
        file_path = target / rel_path
        # Extra safety: never write outside the run folder.
        if target.resolve() not in file_path.resolve().parents:
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return target


def zip_project(run_id: int) -> bytes:
    """
    Return the generated project as a .zip (template + newest files from SQLite).
    Built in memory, so it never disturbs a running preview of the app.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in config.TEMPLATE_DIR.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(config.TEMPLATE_DIR))
        for rel_path, content in db.current_files(run_id).items():
            archive.writestr(rel_path, content)   # newer generated files replace template ones
    return buffer.getvalue()
