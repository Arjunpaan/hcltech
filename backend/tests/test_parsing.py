"""Tests for reading AI answers safely (JSON and file blocks)."""

from agents.base import extract_json, parse_file_blocks, safe_path


def test_extract_json_from_fenced_answer():
    text = 'Here you go:\n```json\n{"a": 1}\n```\nThanks'
    assert extract_json(text) == {"a": 1}


def test_parse_file_blocks_with_reason_and_fences():
    text = ("### FILE: app/main.py\n### REASON: fixed bug\n```python\nprint('hi')\n```\n### END FILE\n"
            "### FILE: tests/test_x.py\nx = 1\n### END FILE\n")
    files = parse_file_blocks(text)
    assert [f["path"] for f in files] == ["app/main.py", "tests/test_x.py"]
    assert files[0]["reason"] == "fixed bug"
    assert files[0]["content"] == "print('hi')\n"


def test_unsafe_paths_are_rejected():
    assert safe_path("../etc/passwd") is None
    assert safe_path("/abs/path.py") is None
    assert safe_path("C:/windows/x.py") is None
    assert safe_path(".env") is None
    assert safe_path("./app/main.py") == "app/main.py"
