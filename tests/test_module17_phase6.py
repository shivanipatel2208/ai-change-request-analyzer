"""Verifies Module 17 Phase 6 (Test Cases & Implementation Plan 2.0 -
Human Editing):

  * PATCH .../test-cases/{id} and PATCH .../implementation-tasks/{id} let
    an authorized human correct one AI-generated row in place - only the
    fields actually sent are changed, edited_by/edited_at/edit_reason are
    set, and a TEST_CASE_EDITED/IMPLEMENTATION_TASK_EDITED history event is
    recorded (same permission gate - workflow_rules.can_review_analysis_
    findings - Module 14 Phase 6 already established for Requirements/
    Security findings; same 403 for an unrelated user).
  * The AI's own original wording is never lost: it's preserved as the
    old_value on that edit's own history row, never overwritten or
    duplicated onto a second column on the row itself.
  * A no-op submission (nothing actually different from what's already
    stored) never records a history event and never sets edited_by/
    edited_at - editing is a real, audited action, not a no-op timestamp
    bump.
  * The response after an edit still carries every computed field
    (analysis_version, is_outdated, requirement_references/
    risk_references, related_files) fully populated - not the schema's
    bare defaults an edit-only code path could otherwise leave them at
    (see app/api/change_requests.py::_full_analysis_read).
  * steps round-trips correctly through an edit (sent as a real list,
    read back as the same real list).
  * owner_suggestion can be explicitly cleared back to null by a human,
    unlike the AI which can only ever suggest one or leave it null.
  * A test case/task id that doesn't belong to the given change request
    404s rather than ever operating on the wrong CR's row.

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) - no real network call, matching this app's established
testing pattern.

Run with (from backend/):  python -m pytest ../tests
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

import app.services.analysis_engine as analysis_engine
from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"m17p6-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase6 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


_ANALYSIS_JSON = {
    "summary": "Adds OTP-based verification to checkout.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
    "requirements": [
        {
            "category": "functional",
            "description": "Customers must receive a one-time password by SMS to verify their identity during checkout.",
            "priority": "high",
        }
    ],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_findings": [],
    "security_analysis": {"concerns": [], "summary": ""},
    "impact_assessments": [],
    "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
    "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
    "missing_information": [],
    "test_cases": [
        {
            "id": "TC-001",
            "title": "OTP code expires after 5 minutes",
            "type": "security",
            "priority": "high",
            "description": "Verify one-time password sent by SMS during checkout expires correctly.",
            "preconditions": "A one-time password has been sent by SMS during checkout.",
            "steps": ["Wait 5 minutes", "Submit the one-time password"],
            "expected_result": "The expired code is rejected with a clear error.",
        }
    ],
    "implementation_plan": [
        {
            "task": "Add OTP generation endpoint",
            "description": "Backend endpoint that generates and stores a one-time password.",
            "component": "Backend",
            "priority": "high",
            "estimated_effort": "2 days",
            "dependencies": None,
            "owner_suggestion": "technical_lead",
        }
    ],
    "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
}


class _FixedProvider:
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(_ANALYSIS_JSON)


def _analyze(monkeypatch, headers) -> dict:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider())
    created = _create_change_request(headers)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    return created, response.json()


def test_update_test_case_edits_fields_and_records_history(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    test_case = body["test_cases"][0]

    response = client.patch(
        f"/api/change-requests/{created['id']}/test-cases/{test_case['id']}",
        json={
            "title": "OTP code is rejected once expired",
            "steps": ["Wait 5 minutes", "Submit the same one-time password again"],
            "reason": "Clarified the exact steps.",
        },
        headers=headers,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "OTP code is rejected once expired"
    assert updated["steps"] == ["Wait 5 minutes", "Submit the same one-time password again"]
    # Untouched fields keep their original AI-written values.
    assert updated["description"] == test_case["description"]
    assert updated["edited_by"] is not None
    assert updated["edited_at"] is not None
    assert updated["edit_reason"] == "Clarified the exact steps."

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers)
    assert history.status_code == 200
    edited_events = [h for h in history.json() if h["action"] == "test_case_edited"]
    assert len(edited_events) == 1
    # The AI's original title is preserved as this event's old_value -
    # never lost, never silently overwritten.
    assert test_case["title"] in edited_events[0]["old_value"]
    assert "OTP code is rejected once expired" in edited_events[0]["new_value"]


def test_update_test_case_response_includes_computed_fields(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    test_case = body["test_cases"][0]
    requirement_id = body["requirements"][0]["id"]

    response = client.patch(
        f"/api/change-requests/{created['id']}/test-cases/{test_case['id']}",
        json={"priority": "critical"},
        headers=headers,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["priority"] == "critical"
    # Still fully computed, not left at bare schema defaults - same
    # requirement this test case traced to before the edit.
    assert updated["analysis_version"] == 1
    assert updated["is_outdated"] is False
    assert updated["requirement_references"] == [f"REQ-{requirement_id}"]


def test_update_test_case_no_op_edit_does_not_record_history_or_set_edited_by(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    test_case = body["test_cases"][0]

    response = client.patch(
        f"/api/change-requests/{created['id']}/test-cases/{test_case['id']}",
        json={"title": test_case["title"]},
        headers=headers,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["edited_by"] is None
    assert updated["edited_at"] is None

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers)
    edited_events = [h for h in history.json() if h["action"] == "test_case_edited"]
    assert len(edited_events) == 0


def test_update_test_case_forbidden_for_unrelated_user(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    test_case = body["test_cases"][0]

    outsider_headers = _auth()
    response = client.patch(
        f"/api/change-requests/{created['id']}/test-cases/{test_case['id']}",
        json={"title": "Hijacked title"},
        headers=outsider_headers,
    )
    assert response.status_code == 403


def test_update_test_case_404_for_wrong_change_request(monkeypatch):
    headers = _auth()
    created_a, body_a = _analyze(monkeypatch, headers)
    created_b, _body_b = _analyze(monkeypatch, headers)
    test_case_a = body_a["test_cases"][0]

    response = client.patch(
        f"/api/change-requests/{created_b['id']}/test-cases/{test_case_a['id']}",
        json={"title": "Should not apply"},
        headers=headers,
    )
    assert response.status_code == 404


def test_update_implementation_task_edits_fields_and_can_clear_owner_suggestion(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    task = body["implementation_tasks"][0]
    assert task["owner_suggestion"] == "technical_lead"

    response = client.patch(
        f"/api/change-requests/{created['id']}/implementation-tasks/{task['id']}",
        json={"estimated_effort": "3 days", "owner_suggestion": None, "reason": "Re-estimated after review."},
        headers=headers,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["estimated_effort"] == "3 days"
    assert updated["owner_suggestion"] is None
    assert updated["edited_by"] is not None
    assert updated["edit_reason"] == "Re-estimated after review."

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers)
    edited_events = [h for h in history.json() if h["action"] == "implementation_task_edited"]
    assert len(edited_events) == 1


def test_update_implementation_task_forbidden_for_unrelated_user(monkeypatch):
    headers = _auth()
    created, body = _analyze(monkeypatch, headers)
    task = body["implementation_tasks"][0]

    outsider_headers = _auth()
    response = client.patch(
        f"/api/change-requests/{created['id']}/implementation-tasks/{task['id']}",
        json={"task": "Hijacked task"},
        headers=outsider_headers,
    )
    assert response.status_code == 403
