"""Verifies Module 18 Phase 1 (Notifications, My Work & Personal
Engineering Queue - Data Foundation):

  * POST .../approvals accepts an optional due_date, persisted on the
    Approval row and returned on ApprovalRead - entirely optional, never
    defaulted or required (existing approval-request behavior with no
    due_date is completely unchanged).
  * due_status (app/services/approvals.py::approval_due_status) is
    computed fresh at read time, never stored: None for a due_date far in
    the future, "due_soon" inside the 2-day window, "overdue" once past
    due_date - and always None again the moment the approval is actually
    responded to (Approved/Rejected/Changes Requested), no matter how far
    in the past its due_date now sits.
  * The lazy deadline check (app/services/deadlines.py) fires a
    DEADLINE_APPROACHING notification, tied to that exact approval via
    Notification.approval_id, the first time its own approver reads their
    notification inbox (GET /api/notifications or /unread-count) - and
    never fires a second one for the same approval on a later read.
  * Scoping: checking your own notifications never creates or surfaces a
    deadline notification for someone ELSE's pending approval, even one
    that's badly overdue - the check only ever looks at the reading
    user's own approvals.

Every test here uses a fake, monkeypatched AI provider where analysis is
needed - no real network call, matching this app's established testing
pattern. No test data ever uses grubbrr.com - alight.com throughout, per
this project's own standing rule.

Run with (from backend/):  python -m pytest ../tests
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"m18p1-{uuid.uuid4().hex[:10]}@example.com"


def _auth(name: str = "Module18 Phase1 Tester") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _request_approval(cr_id: int, headers: dict, approver_id: int, due_date: str = None, approval_type: str = "security"):
    body = {"approval_type": approval_type, "approver_user_id": approver_id}
    if due_date is not None:
        body["due_date"] = due_date
    response = client.post(f"/api/change-requests/{cr_id}/approvals", json=body, headers=headers)
    assert response.status_code == 201
    return response.json()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_due_date_is_optional_and_round_trips(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver With No Due Date")
    created = _create_change_request(owner_headers)

    approval = _request_approval(created["id"], owner_headers, approver_id)
    assert approval["due_date"] is None
    assert approval["due_status"] is None


def test_due_date_far_in_future_is_not_due_soon(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver Far Future")
    created = _create_change_request(owner_headers)

    far_future = _iso(datetime.utcnow() + timedelta(days=30))
    approval = _request_approval(created["id"], owner_headers, approver_id, due_date=far_future)
    assert approval["due_date"] is not None
    assert approval["due_status"] is None


def test_due_date_inside_window_is_due_soon_and_past_is_overdue(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver Due Soon And Overdue")
    created = _create_change_request(owner_headers)

    due_soon_date = _iso(datetime.utcnow() + timedelta(days=1))
    overdue_date = _iso(datetime.utcnow() - timedelta(days=1))

    due_soon_approval = _request_approval(
        created["id"], owner_headers, approver_id, due_date=due_soon_date, approval_type="security"
    )
    overdue_approval = _request_approval(
        created["id"], owner_headers, approver_id, due_date=overdue_date, approval_type="technical"
    )

    listing = client.get(f"/api/change-requests/{created['id']}/approvals", headers=owner_headers)
    assert listing.status_code == 200
    by_id = {a["id"]: a for a in listing.json()}
    assert by_id[due_soon_approval["id"]]["due_status"] == "due_soon"
    assert by_id[overdue_approval["id"]]["due_status"] == "overdue"


def test_due_status_clears_once_approval_is_responded_to(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver Who Responds")
    created = _create_change_request(owner_headers)

    overdue_date = _iso(datetime.utcnow() - timedelta(days=3))
    approval = _request_approval(created["id"], owner_headers, approver_id, due_date=overdue_date)

    respond = client.post(
        f"/api/change-requests/{created['id']}/approvals/{approval['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert respond.status_code == 200
    responded = respond.json()
    # Still badly overdue by the clock, but a decision has already been
    # made - due_status is never meaningful for a resolved approval.
    assert responded["due_status"] is None
    assert responded["due_date"] is not None


def test_deadline_approaching_notification_fires_once_via_notification_list(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver Getting Notified")
    created = _create_change_request(owner_headers)

    overdue_date = _iso(datetime.utcnow() - timedelta(hours=6))
    approval = _request_approval(created["id"], owner_headers, approver_id, due_date=overdue_date)

    first_read = client.get("/api/notifications", headers=approver_headers)
    assert first_read.status_code == 200
    deadline_notifications = [n for n in first_read.json() if n["type"] == "deadline_approaching"]
    assert len(deadline_notifications) == 1
    assert deadline_notifications[0]["approval_id"] == approval["id"]
    assert deadline_notifications[0]["change_request_id"] == created["id"]

    # Reading again must never create a second one for the same approval.
    second_read = client.get("/api/notifications", headers=approver_headers)
    assert second_read.status_code == 200
    deadline_notifications_again = [n for n in second_read.json() if n["type"] == "deadline_approaching"]
    assert len(deadline_notifications_again) == 1
    assert deadline_notifications_again[0]["id"] == deadline_notifications[0]["id"]


def test_deadline_approaching_notification_fires_via_unread_count_too(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver Checking Count")
    created = _create_change_request(owner_headers)

    due_soon_date = _iso(datetime.utcnow() + timedelta(hours=6))
    _request_approval(created["id"], owner_headers, approver_id, due_date=due_soon_date)

    count_response = client.get("/api/notifications/unread-count", headers=approver_headers)
    assert count_response.status_code == 200
    assert count_response.json()["count"] >= 1

    listing = client.get("/api/notifications", headers=approver_headers)
    deadline_notifications = [n for n in listing.json() if n["type"] == "deadline_approaching"]
    assert len(deadline_notifications) == 1


def test_deadline_notification_never_leaks_to_a_different_user(monkeypatch):
    owner_headers, _owner_id = _auth()
    approver_headers, approver_id = _auth("Approver With Overdue Item")
    bystander_headers, _bystander_id = _auth("Unrelated Bystander")
    created = _create_change_request(owner_headers)

    overdue_date = _iso(datetime.utcnow() - timedelta(days=2))
    _request_approval(created["id"], owner_headers, approver_id, due_date=overdue_date)

    # An unrelated user (not the tagged approver) reading their own
    # notifications must never see - or trigger - a deadline notification
    # for someone else's pending approval.
    bystander_read = client.get("/api/notifications", headers=bystander_headers)
    assert bystander_read.status_code == 200
    assert all(n["type"] != "deadline_approaching" for n in bystander_read.json())

    # The CR owner (who requested the approval, but isn't the approver)
    # must not get it either.
    owner_read = client.get("/api/notifications", headers=owner_headers)
    assert owner_read.status_code == 200
    assert all(n["type"] != "deadline_approaching" for n in owner_read.json())
