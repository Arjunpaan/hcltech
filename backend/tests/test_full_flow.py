"""
End-to-end test of the whole workflow with the mock AI:
analyse -> design -> approve -> code -> tests -> REAL checks (fail) -> fix -> approve
-> REAL checks again (pass) -> release decision -> final approval.
"""

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

REQUEST = ("Develop an API allowing customers to update their contact information. Validate mandatory "
           "fields, prevent unauthorized modification, maintain an audit record and return appropriate "
           "API error responses.")


def test_complete_workflow_with_fix_loop():
    run = client.post("/api/runs", json={"requirement": REQUEST}).json()
    run_id = run["id"]
    assert client.get(f"/api/runs/{run_id}").json()["current_stage"] == "AWAITING_DESIGN_APPROVAL"

    # Rejecting without a comment is not allowed.
    assert client.post(f"/api/runs/{run_id}/approve", json={"decision": "reject"}).status_code == 400

    # Approve the design -> code, tests and the first check round run.
    run = client.post(f"/api/runs/{run_id}/approve", json={"decision": "approve", "approver": "tester"}).json()
    assert run["current_stage"] == "AWAITING_FIX_APPROVAL", run

    checks = client.get(f"/api/runs/{run_id}/checks").json()
    round0 = {c["name"]: c for c in checks if c["round"] == 0}
    assert round0["pytest"]["status"] == "failed"          # invalid phone test fails
    assert round0["secret_scan"]["status"] == "failed"     # hard-coded token found
    assert round0["pip_audit"]["status"] == "not_executed"  # disabled -> never shown as passed

    changes = client.get(f"/api/runs/{run_id}/changes").json()
    assert {c["file"] for c in changes} == {"app/main.py", "app/models.py"}

    # Approve the fix -> checks run again (round 1) and pass -> release assessment.
    run = client.post(f"/api/runs/{run_id}/approve", json={"decision": "approve"}).json()
    assert run["current_stage"] == "AWAITING_RELEASE_APPROVAL", run
    round1 = {c["name"]: c for c in client.get(f"/api/runs/{run_id}/checks").json() if c["round"] == 1}
    assert round1["pytest"]["status"] == "passed"
    assert round1["secret_scan"]["status"] == "passed"

    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["live_decision"] == "READY", report["reasons"]
    assert all(row["result"] == "PASSED" for row in report["traceability"])

    run = client.post(f"/api/runs/{run_id}/approve", json={"decision": "approve"}).json()
    assert run["status"] == "completed"
    assert client.get(f"/api/runs/{run_id}/download").status_code == 200
