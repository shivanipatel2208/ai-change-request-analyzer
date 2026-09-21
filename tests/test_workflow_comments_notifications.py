"""Verifies Module 12 Phase 5 (Enterprise Workflow - Comments, Mentions,
Notifications):

  * GET/POST .../comments - a flat two-level discussion thread (one level
    of replies only), open to any authenticated user (unlike editing/
    status/approvals, which stay Owner/Technical Lead/Admin-gated)
  * PUT .../comments/{id}/resolve - the comment's author or whoever manages
    the CR can mark it resolved/reopened; DELETE - author or admin only
  * @mentions parsed from the comment body (app/services/mentions.py)
    notify the mentioned user and record a MENTIONED history event;
    everyone else with a stake in the CR (its creator + assignees) gets a
    plain COMMENT_ADDED notification instead - never both for the same
    comment
  * GET/PUT /api/notifications - a user's own inbox, scoped so nobody can
    read or mark another user's notifications
  * every other Module 12 Phase 3/4 action that should tell someone
    something (assigned, approval requested/responded/reminded, status
    changed, analysis/approval invalidated by an edit) actually creates a
    Notification row

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
    return f"wfcn-{uuid.uuid4().hex[:10]}@example.com"


def _register(name: str) -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _auth() -> tuple[dict, int]:
    return _register("Notif Tester")


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


def _comment(cr_id: int, headers: dict, body: str, parent_id=None):
    payload = {"body": body}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post(f"/api/change-requests/{cr_id}/comments", json=payload, headers=headers)


def _notifications(headers: dict, **params):
    return client.get("/api/notifications", params=params, headers=headers).json()


class _FakeProvider:
    """Same stand-in used in tests/test_change_request_editing.py."""

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


# --- Comments: basic CRUD ---------------------------------------------------


def test_create_comment_requires_authentication():
    response = client.post("/api/change-requests/1/comments", json={"body": "Looks good."})
    assert response.status_code == 401


def test_create_comment_404_for_unknown_change_request():
    headers, _ = _auth()
    response = _comment(999999999, headers, "Looks good.")
    assert response.status_code == 404


def test_any_authenticated_user_can_comment_and_it_appears_in_list_and_history():
    headers, _ = _auth()
    created = _create_change_request(headers)
    outsider_headers, _ = _auth()  # not the creator, not assigned - comments aren't owner-gated

    response = _comment(created["id"], outsider_headers, "Has anyone checked the rate limiting?")
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "Has anyone checked the rate limiting?"
    assert body["resolved"] is False
    assert body["parent_id"] is None

    listing = client.get(f"/api/change-requests/{created['id']}/comments", headers=headers).json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    comment_events = [h for h in history if h["action"] == "comment_added"]
    assert len(comment_events) == 1
    assert comment_events[0]["new_value"] == "Has anyone checked the rate limiting?"


def test_reply_to_comment_works():
    headers, _ = _auth()
    created = _create_change_request(headers)
    top = _comment(created["id"], headers, "Has anyone checked the rate limiting?").json()

    reply = _comment(created["id"], headers, "Yes, it's in the design doc.", parent_id=top["id"])
    assert reply.status_code == 201
    assert reply.json()["parent_id"] == top["id"]

    listing = client.get(f"/api/change-requests/{created['id']}/comments", headers=headers).json()
    assert len(listing) == 2


def test_reply_to_a_reply_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    top = _comment(created["id"], headers, "Question one.").json()
    reply = _comment(created["id"], headers, "Answer.", parent_id=top["id"]).json()

    second_reply = _comment(created["id"], headers, "Follow-up.", parent_id=reply["id"])
    assert second_reply.status_code == 422


def test_reply_to_unknown_comment_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = _comment(created["id"], headers, "Reply to nothing.", parent_id=999999999)
    assert response.status_code == 404


def test_resolve_comment_by_author():
    headers, _ = _auth()
    created = _create_change_request(headers)
    outsider_headers, _ = _auth()
    comment = _comment(created["id"], outsider_headers, "Needs clarification.").json()

    response = client.put(
        f"/api/change-requests/{created['id']}/comments/{comment['id']}/resolve",
        json={"resolved": True},
        headers=outsider_headers,
    )
    assert response.status_code == 200
    assert response.json()["resolved"] is True


def test_resolve_comment_by_cr_owner():
    headers, _ = _auth()
    created = _create_change_request(headers)
    outsider_headers, _ = _auth()
    comment = _comment(created["id"], outsider_headers, "Needs clarification.").json()

    # The CR's own creator (who didn't write the comment) can still resolve it.
    response = client.put(
        f"/api/change-requests/{created['id']}/comments/{comment['id']}/resolve",
        json={"resolved": True},
        headers=headers,
    )
    assert response.status_code == 200


def test_resolve_comment_unrelated_user_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    author_headers, _ = _auth()
    comment = _comment(created["id"], author_headers, "Needs clarification.").json()
    unrelated_headers, _ = _auth()

    response = client.put(
        f"/api/change-requests/{created['id']}/comments/{comment['id']}/resolve",
        json={"resolved": True},
        headers=unrelated_headers,
    )
    assert response.status_code == 403


def test_delete_own_comment():
    headers, _ = _auth()
    created = _create_change_request(headers)
    comment = _comment(created["id"], headers, "Oops, wrong thread.").json()

    response = client.delete(f"/api/change-requests/{created['id']}/comments/{comment['id']}", headers=headers)
    assert response.status_code == 204

    listing = client.get(f"/api/change-requests/{created['id']}/comments", headers=headers).json()
    assert listing == []


def test_delete_someone_elses_comment_is_rejected():
    headers, _ = _auth()
    created = _create_change_request(headers)
    author_headers, _ = _auth()
    comment = _comment(created["id"], author_headers, "My comment.").json()

    response = client.delete(f"/api/change-requests/{created['id']}/comments/{comment['id']}", headers=headers)
    assert response.status_code == 403


def test_delete_unknown_comment_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.delete(f"/api/change-requests/{created['id']}/comments/999999999", headers=headers)
    assert response.status_code == 404


# --- Mentions & notification dedup ------------------------------------------


def test_mentioning_a_user_creates_mentioned_notification_and_history_event():
    headers, _ = _auth()
    created = _create_change_request(headers)
    mentioned_headers, mentioned_id = _register("Priya Shah")

    response = _comment(created["id"], headers, "@Priya Shah can you take a look at this?")
    assert response.status_code == 201
    assert response.json()["mentioned_user_ids"] == [mentioned_id]

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    mentioned_events = [h for h in history if h["action"] == "mentioned"]
    assert len(mentioned_events) == 1
    assert "Priya Shah" in mentioned_events[0]["new_value"]

    notifications = _notifications(mentioned_headers)
    mention_notifs = [n for n in notifications if n["type"] == "mentioned"]
    assert len(mention_notifs) == 1
    assert mention_notifs[0]["change_request_id"] == created["id"]
    assert mention_notifs[0]["is_read"] is False


def test_commenting_notifies_creator_but_not_the_comments_own_author():
    headers, creator_id = _auth()
    created = _create_change_request(headers)
    commenter_headers, _ = _auth()

    _comment(created["id"], commenter_headers, "Just a general comment, no mentions.")

    creator_notifs = _notifications(headers)
    assert any(n["type"] == "comment_added" for n in creator_notifs)

    # The commenter themselves never gets notified about their own comment.
    commenter_notifs = _notifications(commenter_headers)
    assert commenter_notifs == []


def test_mentioned_user_does_not_also_get_a_plain_comment_notification():
    headers, _ = _auth()
    created = _create_change_request(headers)
    mentioned_headers, mentioned_id = _register("Devon Cole")
    # Also assign this same person, so without the dedup rule they'd
    # qualify for both a COMMENT_ADDED (as an assignee) and a MENTIONED
    # notification for the same comment.
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": mentioned_id, "role": "reviewer"},
        headers=headers,
    )

    _comment(created["id"], headers, "@Devon Cole please review this.")

    notifications = _notifications(mentioned_headers)
    types = [n["type"] for n in notifications if n["change_request_id"] == created["id"]]
    # The ASSIGNED notification from being assigned above is expected, plus
    # exactly one MENTIONED for the comment - never a COMMENT_ADDED too.
    assert types.count("mentioned") == 1
    assert types.count("comment_added") == 0


# --- Notifications API ------------------------------------------------------


def test_list_notifications_requires_authentication():
    response = client.get("/api/notifications")
    assert response.status_code == 401


def test_notifications_are_scoped_to_the_current_user():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _comment(created["id"], other_headers, "A comment from someone else.")

    # The creator got a notification; the commenter (who has none of their
    # own) must not see the creator's.
    assert len(_notifications(headers)) >= 1
    assert _notifications(other_headers) == []


def test_mark_notification_read():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _comment(created["id"], other_headers, "Ping.")

    notif = _notifications(headers)[0]
    assert notif["is_read"] is False

    response = client.put(f"/api/notifications/{notif['id']}/read", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_read"] is True

    unread = _notifications(headers, unread_only=True)
    assert unread == []


def test_mark_all_read():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _comment(created["id"], other_headers, "One.")
    _comment(created["id"], other_headers, "Two.")

    response = client.put("/api/notifications/read-all", headers=headers)
    assert response.status_code == 200
    assert response.json()["updated"] >= 2

    assert _notifications(headers, unread_only=True) == []


def test_unread_count():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _comment(created["id"], other_headers, "Ping.")

    response = client.get("/api/notifications/unread-count", headers=headers)
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_cannot_mark_someone_elses_notification_read():
    headers, _ = _auth()
    created = _create_change_request(headers)
    other_headers, _ = _auth()
    _comment(created["id"], other_headers, "Ping.")

    notif = _notifications(headers)[0]
    response = client.put(f"/api/notifications/{notif['id']}/read", headers=other_headers)
    assert response.status_code == 404


# --- Notification wiring into Phase 3/4 actions -----------------------------


def test_assigning_a_user_creates_assigned_notification():
    headers, _ = _auth()
    created = _create_change_request(headers)
    assignee_headers, assignee_id = _auth()

    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "technical_lead"},
        headers=headers,
    )

    notifs = _notifications(assignee_headers)
    assert any(n["type"] == "assigned" for n in notifs)


def test_requesting_approval_creates_notification_for_approver():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "security", "approver_user_id": approver_id},
        headers=headers,
    )

    notifs = _notifications(approver_headers)
    assert any(n["type"] == "approval_requested" for n in notifs)


def test_responding_to_approval_notifies_requester():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()

    requested = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "security", "approver_user_id": approver_id},
        headers=headers,
    ).json()

    client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )

    notifs = _notifications(headers)
    assert any(n["type"] == "approved" for n in notifs)


def test_changing_status_notifies_assignees_and_creator():
    headers, _ = _auth()
    created = _create_change_request(headers)
    assignee_headers, assignee_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=headers,
    )

    client.put(f"/api/change-requests/{created['id']}/status", json={"status": "analyzed"}, headers=headers)

    notifs = _notifications(assignee_headers)
    assert any(n["type"] == "status_changed" for n in notifs)
    # The person who made the change doesn't notify themselves.
    creator_status_notifs = [n for n in _notifications(headers) if n["type"] == "status_changed"]
    assert creator_status_notifs == []


def test_reminder_creates_notification_and_history_event():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()
    requested = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "qa", "approver_user_id": approver_id},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/remind", headers=headers
    )
    assert response.status_code == 204

    notifs = _notifications(approver_headers)
    assert any(n["type"] == "reminder" for n in notifs)

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert any(h["action"] == "reminder_sent" for h in history)


def test_reminder_requires_permission():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()
    requested = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "qa", "approver_user_id": approver_id},
        headers=headers,
    ).json()
    outsider_headers, _ = _auth()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/remind", headers=outsider_headers
    )
    assert response.status_code == 403


def test_reminder_only_for_pending_approval():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()
    requested = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "qa", "approver_user_id": approver_id},
        headers=headers,
    ).json()
    client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/remind", headers=headers
    )
    assert response.status_code == 409


def test_editing_after_analysis_notifies_creator_of_outdated_analysis(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)

    # Reviewer is deliberately NOT enough to edit a CR (workflow_rules.
    # can_edit_change_request: creator + Owner/Technical Lead + Admin only,
    # same rule already exercised in test_workflow_status_assignments.py) -
    # this test is about the outdated-analysis notification, so the editor
    # needs a role that can actually get the PUT past permission checks.
    other_headers, other_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": other_id, "role": "technical_lead"},
        headers=headers,
    )

    edit_response = client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=other_headers,
    )
    assert edit_response.status_code == 200

    notifs = _notifications(headers)
    assert any(n["type"] == "analysis_outdated" for n in notifs)


def test_editing_after_approval_requested_notifies_approver_of_reapproval_needed():
    headers, _ = _auth()
    created = _create_change_request(headers)
    approver_headers, approver_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "dba", "approver_user_id": approver_id},
        headers=headers,
    )

    client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )

    notifs = _notifications(approver_headers)
    assert any(n["type"] == "reapproval_required" for n in notifs)
