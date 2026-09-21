"""Verifies Module 12 Phase 4 (Enterprise Workflow - Approvals):

  * POST /api/change-requests/{id}/approvals - tag a real person for a
    specific kind of sign-off, permission-gated, duplicate-pending
    rejected, recorded on the audit history
  * POST .../approvals/{approval_id}/respond - only the tagged approver
    can respond, a comment is required to reject/request changes, an
    already-resolved approval can't be responded to again
  * DELETE .../approvals/{approval_id} - withdraw a still-pending request
    (soft-cancelled, not deleted), permission-gated
  * GET .../approvals/recommended - the AI-derived recommendation only
    (never auto-creates an Approval row)
  * editing a CR after an approval was requested against it marks that
    approval outdated (is_outdated + an APPROVAL_INVALIDATED history event)

Run with (from backend/):  pytest ../tests
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
    return f"wfap-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Approval Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP login to mobile app",
        "description": "Allow customers to log in using a one-time passcode sent to their registered number.",
        "priority": "medium",
        "requested_by": "Morgan Lee",
        "target_system": "Mobile App",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _request_approval(cr_id: int, headers: dict, approver_id: int, approval_type: str = "security", comment=None):
    body = {"approval_type": approval_type, "approver_user_id": approver_id}
    if comment is not None:
        body["comment"] = comment
    return client.post(f"/api/change-requests/{cr_id}/approvals", json=body, headers=headers)


class _FakeProvider:
    """Same stand-in used in tests/test_change_request_editing.py - returns
    canned text instead of calling the real AI provider."""

    def __init__(self, response_text=None, configured=True, raise_exc=None):
        self._text = response_text
        self._configured = configured
        self._raise = raise_exc

    def is_configured(self) -> bool:
        return self._configured

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        if self._raise is not None:
            raise self._raise
        return self._text


def _patch_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)


# A minimal, valid AIAnalysisResult - only the approvals behavior is under
# test here, not the analysis content itself. No risks -> risk_score falls
# to the 5.0 floor -> the low-risk baseline (Technical) only, plus whatever
# keyword matches the CR's own title/target_system add on top.
_MINIMAL_ANALYSIS_RESPONSE = {
    "summary": "Adds OTP-based login to the mobile app.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.8, "reason": "New auth flow."},
    "requirements": [],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
    "complexity": {"level": "medium", "reasoning": "New auth flow, moderate scope."},
    "effort": {"backend": "2 days", "frontend": "2 days", "testing": "1 day", "total": "5 developer-days"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "approve", "reasoning": "Well-scoped."},
}


# --- Requesting an approval -------------------------------------------------


def test_request_approval_requires_authentication():
    response = client.post("/api/change-requests/1/approvals", json={"approval_type": "security", "approver_user_id": 1})
    assert response.status_code == 401


def test_request_approval_404_for_unknown_change_request():
    headers, _ = _auth()
    _, approver_id = _auth()
    response = _request_approval(999999999, headers, approver_id)
    assert response.status_code == 404


def test_creator_can_request_approval_and_it_appears_in_list_and_history():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()

    response = _request_approval(created["id"], headers, approver_id, approval_type="security", comment="Please check rate limiting.")
    assert response.status_code == 201
    body = response.json()
    assert body["approval_type"] == "security"
    assert body["approval_type_label"] == "Security"
    assert body["status"] == "pending"
    assert body["status_label"] == "Pending"
    assert body["approver_id"] == approver_id
    assert body["cr_version"] == 1
    assert body["is_outdated"] is False

    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=headers).json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    requested_events = [h for h in history if h["action"] == "approval_requested"]
    assert len(requested_events) == 1
    assert "Security approval requested" in requested_events[0]["new_value"]
    assert requested_events[0]["reason"] == "Please check rate limiting."


def test_request_approval_for_unknown_approver_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = _request_approval(created["id"], headers, 999999999)
    assert response.status_code == 404


def test_duplicate_pending_approval_request_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()

    first = _request_approval(created["id"], headers, approver_id, approval_type="qa")
    assert first.status_code == 201

    second = _request_approval(created["id"], headers, approver_id, approval_type="qa")
    assert second.status_code == 409


def test_unrelated_user_cannot_request_approval():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _, approver_id = _auth()

    response = _request_approval(created["id"], other_headers, approver_id)
    assert response.status_code == 403


# --- Responding to an approval ----------------------------------------------


def test_approver_can_approve_and_it_appears_in_history():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id, approval_type="technical").json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["status_label"] == "Approved"
    assert body["responded_at"] is not None

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    approved_events = [h for h in history if h["action"] == "approved"]
    assert len(approved_events) == 1
    assert approved_events[0]["new_value"] == "Technical — Approved"


def test_approver_can_reject_with_reason():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id, approval_type="security").json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "rejected", "comment": "The rate limiting design needs more detail."},
        headers=approver_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["comment"] == "The rate limiting design needs more detail."

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    rejected_events = [h for h in history if h["action"] == "rejected"]
    assert rejected_events[0]["reason"] == "The rate limiting design needs more detail."


def test_rejecting_without_reason_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "rejected"},
        headers=approver_headers,
    )
    assert response.status_code == 422


def test_requesting_changes_without_reason_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "changes_requested"},
        headers=approver_headers,
    )
    assert response.status_code == 422


def test_someone_other_than_the_approver_cannot_respond():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()
    outsider_headers, _ = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()

    # Not even the CR's own creator (who requested the approval) can
    # respond to it on the approver's behalf.
    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=headers,
    )
    assert response.status_code == 403

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=outsider_headers,
    )
    assert response.status_code == 403


def test_responding_to_already_resolved_approval_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()
    first = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "rejected", "comment": "Changed my mind."},
        headers=approver_headers,
    )
    assert second.status_code == 409


# --- Cancelling a pending request -------------------------------------------


def test_creator_can_cancel_pending_approval():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()

    response = client.delete(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}", headers=headers
    )
    assert response.status_code == 204

    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=headers).json()
    assert listing[0]["status"] == "cancelled"

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert any(h["action"] == "approval_cancelled" for h in history)


def test_cancel_already_resolved_approval_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()
    client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )

    response = client.delete(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}", headers=headers
    )
    assert response.status_code == 409


def test_unrelated_user_cannot_cancel_approval():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()
    outsider_headers, _ = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()

    response = client.delete(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}", headers=outsider_headers
    )
    assert response.status_code == 403


def test_cancel_unknown_approval_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.delete(f"/api/change-requests/{created['id']}/approvals/999999999", headers=headers)
    assert response.status_code == 404


# --- Recommended approval types (AI recommends, humans decide) -------------


def test_recommended_approval_types_empty_before_analysis():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.get(f"/api/change-requests/{created['id']}/approvals/recommended", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_recommended_approval_types_reflects_ai_analysis(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))
    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze.status_code == 201

    response = client.get(f"/api/change-requests/{created['id']}/approvals/recommended", headers=headers)
    assert response.status_code == 200
    recommended = {r["approval_type"] for r in response.json()}
    # No risks -> risk_score floors at 5.0 -> low-risk baseline (Technical).
    # Target system/title is "Mobile App", one of the customer-facing
    # keywords -> Product is added on top.
    assert recommended == {"technical", "product"}

    # This is a recommendation only - it never creates an Approval row.
    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=headers).json()
    assert listing == []


# --- Approval invalidation on edit -------------------------------------------


def test_editing_change_request_after_approval_requested_marks_it_outdated():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id, approval_type="dba").json()
    assert requested["cr_version"] == 1
    assert requested["is_outdated"] is False

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["current_version"] == 2

    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=headers).json()
    assert listing[0]["is_outdated"] is True
    assert listing[0]["cr_version"] == 1  # unchanged - it was requested against version 1

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert any(h["action"] == "approval_invalidated" for h in history)


def test_resolved_approval_is_never_reported_as_outdated():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = _request_approval(created["id"], headers, approver_id).json()
    client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )

    client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )

    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=headers).json()
    assert listing[0]["status"] == "approved"
    assert listing[0]["is_outdated"] is False


# --- List endpoint guard -----------------------------------------------------


def test_list_approvals_requires_authentication():
    response = client.get("/api/change-requests/1/approvals")
    assert response.status_code == 401
