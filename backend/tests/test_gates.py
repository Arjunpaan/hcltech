"""Tests for the release decision rules (no AI involved)."""

import config
from services.gates import _decide

RULES = dict(config.DEFAULT_GATES)


def gate(name, status, blocking=True):
    return {"gate": name, "status": status, "reason": "", "blocking": blocking}


ALL_PASSED = [gate(n, "passed") for n in ("Requirement", "Code", "Test", "Security", "Traceability", "Approval")]


def test_all_passed_is_ready():
    decision, _ = _decide(ALL_PASSED, [], RULES)
    assert decision == "READY"


def test_failed_tests_is_not_ready():
    gates = [g if g["gate"] != "Test" else gate("Test", "failed") for g in ALL_PASSED]
    assert _decide(gates, [], RULES)[0] == "NOT READY"


def test_blocking_security_finding_is_not_ready():
    finding = {"blocking": 1, "title": "secret", "source": "secret_scan", "severity": "high"}
    assert _decide(ALL_PASSED, [finding], RULES)[0] == "NOT READY"


def test_check_not_executed_is_manual_review():
    gates = [g if g["gate"] != "Security" else gate("Security", "not_executed") for g in ALL_PASSED]
    assert _decide(gates, [], RULES)[0] == "MANUAL REVIEW"


def test_missing_approval_is_manual_review():
    gates = [g if g["gate"] != "Approval" else gate("Approval", "failed", blocking=False) for g in ALL_PASSED]
    assert _decide(gates, [], RULES)[0] == "MANUAL REVIEW"


def test_open_medium_finding_is_conditional_and_threshold_is_configurable():
    finding = {"blocking": 0, "title": "style", "source": "reviewer_agent", "severity": "medium"}
    assert _decide(ALL_PASSED, [finding], RULES)[0] == "CONDITIONAL"
    relaxed = dict(RULES, conditional_min_severity="high")
    assert _decide(ALL_PASSED, [finding], relaxed)[0] == "READY"
