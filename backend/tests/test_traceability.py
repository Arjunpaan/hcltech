"""Tests for finding '# Implements:' links in code."""

from services.traceability import implementation_map


def test_implements_comment_links_to_next_function():
    files = {"app/main.py": "# Implements: AC-01, AC-2\ndef update_contact():\n    pass\n",
             "tests/test_a.py": "# Implements: AC-09\ndef test_x():\n    pass\n"}
    found = implementation_map(files)
    assert found["AC-01"] == ["app/main.py -> update_contact()"]
    assert found["AC-02"] == ["app/main.py -> update_contact()"]
    assert "AC-09" not in found  # tests are not implementation
