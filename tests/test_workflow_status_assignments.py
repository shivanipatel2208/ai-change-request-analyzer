"""Verifies Module 12 Phase 3 (Enterprise Workflow - Status Lifecycle +
Assignments):

  * PUT /api/change-requests/{id}/status - only a legal next step is
    accepted, moving into a "something went wrong" status requires a
    reason, only the CR owner/creator/admin can do it, and every change is
    recorded on the audit history
  * GET .../{id} exposes status_label + available_transitions computed
    fresh from app/services/workflow_rules.py
  * GET/POST/DELETE .../{id}/assignments - assigning/unassigning a team
    member to a role, permission-gated, duplicate-assignment rejected,
    recorded on the audit history
  * GET /api/users - the simple directory the assignment picker uses

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"wfsa-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Status Tester", "email": email, "password": password, "confirm_password": password},
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


def _set_status(cr_id: int, target: str, headers: dict, reason: str | None = None):
    body = {"status": target}
    if reason is not None:
        body["reason"] = reason
    return client.put(f"/api/change-requests/{cr_id}/status", json=body, headers=headers)


# --- Status transitions ----------------------------------------------------


def test_status_change_requires_authentication():
    response = client.put("/api/change-requests/1/status", json={"status": "analyzed"})
    assert response.status_code == 401


def test_status_change_404_for_unknown_change_request():
    headers, _ = _auth()
    response = _set_status(999999999, "analyzed", headers)
    assert response.status_code == 404


def test_creator_can_advance_status_through_valid_path():
    headers, _ = _auth()
    created = _create_change_request(headers)
    assert created["status"] == "pending_analysis"

    response = _set_status(created["id"], "analyzed", headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "analyzed"
    assert body["status_label"] == "Analyzed"

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    status_events = [h for h in history if h["action"] == "status_changed"]
    assert len(status_events) == 1
    assert status_events[0]["old_value"] == "Pending Analysis"
    assert status_events[0]["new_value"] == "Analyzed"


def test_invalid_transition_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    # Pending Analysis can't jump straight to Approved.
    response = _set_status(created["id"], "approved", headers)
    assert response.status_code == 422


def test_transition_into_reason_required_status_without_reason_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    cr_id = created["id"]
    assert _set_status(cr_id, "analyzed", headers).status_code == 200
    assert _set_status(cr_id, "in_review", headers).status_code == 200

    response = _set_status(cr_id, "changes_requested", headers)  # no reason
    assert response.status_code == 422

    response = _set_status(cr_id, "changes_requested", headers, reason="Missing rollback plan.")
    assert response.status_code == 200
    assert response.json()["status"] == "changes_requested"

    history = client.get(f"/api/change-requests/{cr_id}/history", headers=headers).json()
    status_events = [h for h in history if h["action"] == "status_changed"]
    last = status_events[0]  # newest first
    assert last["new_value"] == "Changes Requested"
    assert last["reason"] == "Missing rollback plan."


def test_unrelated_user_cannot_change_status():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()

    response = _set_status(created["id"], "analyzed", other_headers)
    assert response.status_code == 403


def test_available_transitions_reflect_current_status():
    headers, _ = _auth()
    created = _create_change_request(headers)

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    transitions = {t["status"]: t["requires_reason"] for t in detail["available_transitions"]}
    assert transitions == {"analyzed": False, "cancelled": True}


# --- Assignments -------------------------------------------------------


def test_assignments_require_authentication():
    response = client.get("/api/change-requests/1/assignments")
    assert response.status_code == 401
    response = client.post("/api/change-requests/1/assignments", json={"user_id": 1, "role": "owner"})
    assert response.status_code == 401


def test_creator_can_assign_a_user_and_it_appears_in_list_and_history():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, other_id = _auth()

    response = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "technical_lead"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == other_id
    assert body["role"] == "technical_lead"
    assert body["role_label"] == "Technical Lead"

    listing = client.get(f"/api/change-requests/{created['id']}/assignments", headers=headers).json()
    assert len(listing) == 1
    assert listing[0]["user_id"] == other_id

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assigned_events = [h for h in history if h["action"] == "assigned"]
    assert len(assigned_events) == 1
    assert "Technical Lead" in assigned_events[0]["new_value"]

    # The newly-assigned Technical Lead can now also manage this CR (e.g.
    # change its status), even though they didn't create it.
    assert _set_status(created["id"], "analyzed", other_headers).status_code == 200


def test_duplicate_assignment_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, other_id = _auth()

    first = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "reviewer"},
        headers=headers,
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "reviewer"},
        headers=headers,
    )
    assert second.status_code == 409


def test_assigning_unknown_user_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": 999999999, "role": "reviewer"},
        headers=headers,
    )
    assert response.status_code == 404


def test_unrelated_user_cannot_assign():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, other_id = _auth()

    response = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "reviewer"},
        headers=other_headers,
    )
    assert response.status_code == 403


def test_delete_assignment_removes_it_and_records_history():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, other_id = _auth()

    created_assignment = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "reviewer"},
        headers=headers,
    ).json()

    response = client.delete(
        f"/api/change-requests/{created['id']}/assignments/{created_assignment['id']}", headers=headers
    )
    assert response.status_code == 204

    listing = client.get(f"/api/change-requests/{created['id']}/assignments", headers=headers).json()
    assert listing == []

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    unassigned_events = [h for h in history if h["action"] == "unassigned"]
    assert len(unassigned_events) == 1
    assert "Reviewer" in unassigned_events[0]["old_value"]


def test_delete_unknown_assignment_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.delete(f"/api/change-requests/{created['id']}/assignments/999999999", headers=headers)
    assert response.status_code == 404


def test_unrelated_user_cannot_delete_assignment():
    headers, _ = _auth()
    created = _create_change_request(headers)
    _, other_id = _auth()
    assignment = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "reviewer"},
        headers=headers,
    ).json()

    outsider_headers, _ = _auth()
    response = client.delete(
        f"/api/change-requests/{created['id']}/assignments/{assignment['id']}", headers=outsider_headers
    )
    assert response.status_code == 403


# --- User directory ------------------------------------------------------


def test_list_users_requires_authentication():
    response = client.get("/api/users")
    assert response.status_code == 401


def test_list_users_returns_registered_users():
    headers, user_id = _auth()
    response = client.get("/api/users", headers=headers)
    assert response.status_code == 200
    ids = {u["id"] for u in response.json()}
    assert user_id in ids
