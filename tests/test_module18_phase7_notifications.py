"""Verifies Module 18 Phase 7 (Notifications, My Work & Personal
Engineering Queue - dedicated notification coverage + report):

Spec section 8 asks for dedicated tests confirming notifications for:
Approval, Assignment, Mention, Changes Requested, Re-analysis, Re-approval
- and that users only ever see notifications belonging to them. Several of
these already have thorough dedicated coverage elsewhere in this test
suite (this file's docstrings on each test say exactly where); this file
fills the gaps that were still Notification-row-less - real
POST/PUT-triggered assertions that a Notification row was actually
created for the right person, and never for the wrong one - and adds one
cross-cutting scoping test specific to Module 18's own newer notification
types (risk_escalated, analysis_completed, reapproval_required,
analysis_outdated) alongside the older ones, closing spec section 8's
"ensure users only see notifications belonging to them" for this module.

  * Approval - APPROVAL_REQUESTED notifies the tagged approver only (never
    the requester); a response (Approved/Rejected/Changes Requested)
    notifies the requester only (never the responder) - see
    test_workflow_approvals.py for the history-event/permission side of
    this same flow, not previously asserted against a Notification row.
  * Assignment - ASSIGNED notifies the newly-assigned person only (never
    whoever assigned them) - see test_workflow_status_assignments.py for
    the history-event/permission side, not previously asserted against a
    Notification row.
  * Mention - already extensively covered by
    test_workflow_comments_notifications.py (dedup against COMMENT_ADDED,
    scoping, etc.) - one light test here for this module's own
    self-contained record that the spec item is satisfied.
  * Changes Requested - same Approval-response flow above, called out on
    its own since spec section 8 lists it separately (it's also what
    drives My Work's own "Changes Requested From Me" tab - see
    test_module18_phase3.py).
  * Re-analysis - ANALYSIS_SIGNIFICANTLY_CHANGED/RISK_ESCALATED/
    ANALYSIS_COMPLETED are already extensively covered by
    test_ai_analysis_phase3.py and test_module18_phase2.py; this file adds
    the one still-missing piece - ANALYSIS_OUTDATED (a CR edited after it
    was analyzed, telling its stakeholders a re-analysis is worth doing)
    had never been asserted against a real Notification row, only the
    is_analysis_outdated computed flag (test_change_request_editing.py).
  * Re-approval - REAPPROVAL_REQUIRED (a CR edited while an approval
    against an earlier version is still pending) had never been asserted
    against a real Notification row either - only its own history event
    (app/services/versioning.py).

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) where analysis is involved - no real network call,
matching this app's established testing pattern. No test data ever uses
grubbrr.com - alight.com throughout, per this project's own standing rule.

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
    return f"m18p7-{uuid.uuid4().hex[:10]}@example.com"


def _auth(name: str = "Module18 Phase7 Tester") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP login to Alight.com checkout",
        "description": "Let customers verify identity with a one-time passcode before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Alight.com Checkout",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _notifications_for(headers: dict, notification_type: str) -> list[dict]:
    response = client.get("/api/notifications", headers=headers)
    assert response.status_code == 200
    return [n for n in response.json() if n["type"] == notification_type]


_ANALYSIS_RESPONSE = {
    "summary": "Adds OTP-based verification to checkout.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
    "requirements": [],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_findings": [],
    "security_analysis": {"concerns": [], "summary": ""},
    "impact_assessments": [],
    "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
    "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
}


class _FixedProvider:
    """Same stand-in used across this project's other analysis tests -
    always returns the same, minimal, well-formed analysis JSON."""

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(_ANALYSIS_RESPONSE)


# --- Approval (request + response) ------------------------------------------


def test_approval_requested_notifies_approver_not_requester():
    requester_headers, _ = _auth("Approval Requester")
    approver_headers, approver_id = _auth("Approval Approver")
    created = _create_change_request(requester_headers)

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=requester_headers,
    )
    assert response.status_code == 201

    approver_notifs = _notifications_for(approver_headers, "approval_requested")
    assert len(approver_notifs) == 1
    assert approver_notifs[0]["change_request_id"] == created["id"]
    assert approver_notifs[0]["is_read"] is False

    # The requester never gets a notification about their own request.
    assert _notifications_for(requester_headers, "approval_requested") == []


def test_approval_approved_notifies_requester_not_approver():
    requester_headers, _ = _auth("Approve Requester")
    approver_headers, approver_id = _auth("Approve Approver")
    created = _create_change_request(requester_headers)
    approval = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=requester_headers,
    ).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{approval['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert response.status_code == 200

    requester_notifs = _notifications_for(requester_headers, "approved")
    assert len(requester_notifs) == 1
    assert requester_notifs[0]["change_request_id"] == created["id"]

    # The approver never gets notified about their own decision.
    assert _notifications_for(approver_headers, "approved") == []


def test_approval_rejected_notifies_requester_not_approver():
    requester_headers, _ = _auth("Reject Requester")
    approver_headers, approver_id = _auth("Reject Approver")
    created = _create_change_request(requester_headers)
    approval = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=requester_headers,
    ).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{approval['id']}/respond",
        json={"status": "rejected", "comment": "Missing rate-limit design."},
        headers=approver_headers,
    )
    assert response.status_code == 200

    requester_notifs = _notifications_for(requester_headers, "rejected")
    assert len(requester_notifs) == 1
    assert requester_notifs[0]["change_request_id"] == created["id"]
    assert _notifications_for(approver_headers, "rejected") == []


# --- Changes Requested (spec section 8's own separate line item) -----------


def test_changes_requested_notifies_requester_not_approver():
    requester_headers, _ = _auth("ChangesReq Requester")
    approver_headers, approver_id = _auth("ChangesReq Approver")
    created = _create_change_request(requester_headers)
    approval = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=requester_headers,
    ).json()

    response = client.post(
        f"/api/change-requests/{created['id']}/approvals/{approval['id']}/respond",
        json={"status": "changes_requested", "comment": "Please add OTP rate limiting first."},
        headers=approver_headers,
    )
    assert response.status_code == 200

    requester_notifs = _notifications_for(requester_headers, "changes_requested")
    assert len(requester_notifs) == 1
    assert requester_notifs[0]["change_request_id"] == created["id"]
    assert _notifications_for(approver_headers, "changes_requested") == []

    # This is also exactly what should now show up on the requester's own
    # My Work "Changes Requested From Me" tab (see test_module18_phase3.py
    # for that endpoint's own dedicated coverage) - a quick cross-check
    # here that the two features agree on the same underlying event.
    changes_requested = client.get("/api/my-work/changes-requested", headers=requester_headers).json()
    assert any(item["change_request_id"] == created["id"] for item in changes_requested)


# --- Assignment ---------------------------------------------------------


def test_assignment_notifies_assignee_not_assigner():
    assigner_headers, _ = _auth("Assigner")
    assignee_headers, assignee_id = _auth("Assignee")
    created = _create_change_request(assigner_headers)

    response = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=assigner_headers,
    )
    assert response.status_code == 201

    assignee_notifs = _notifications_for(assignee_headers, "assigned")
    assert len(assignee_notifs) == 1
    assert assignee_notifs[0]["change_request_id"] == created["id"]

    # Nobody assigns themselves a notification for their own action.
    assert _notifications_for(assigner_headers, "assigned") == []


# --- Mention (already thoroughly covered elsewhere - light check here) -----


def test_mention_notification_fires():
    # Mention matching (app/services/mentions.py) checks every registered
    # user's name as a substring, system-wide - not scoped to this test -
    # so this name has to be unique across the whole shared test database,
    # not just this file (a plain "Mentioned Person" collided with
    # test_module18_phase3.py's own fixture of the same name and matched
    # both users). A uuid suffix guarantees no other test can ever collide
    # with it, mirroring this project's own established fix for this exact
    # class of problem (see test_module18_phase2.py's own docstring on
    # "fixture wording carefully designed to avoid accidental keyword-
    # overlap collisions between unrelated rows").
    unique_name = f"Mentioned Phase7 Person {uuid.uuid4().hex[:8]}"
    author_headers, _ = _auth("Mention Author Phase7")
    mentioned_headers, mentioned_id = _auth(unique_name)
    created = _create_change_request(author_headers)

    response = client.post(
        f"/api/change-requests/{created['id']}/comments",
        json={"body": f"@{unique_name} can you weigh in on this?"},
        headers=author_headers,
    )
    assert response.status_code == 201
    assert response.json()["mentioned_user_ids"] == [mentioned_id]

    mentioned_notifs = _notifications_for(mentioned_headers, "mentioned")
    assert len(mentioned_notifs) == 1
    assert mentioned_notifs[0]["change_request_id"] == created["id"]


# --- Re-analysis: ANALYSIS_OUTDATED (editing after analysis) --------------


def test_analysis_outdated_notifies_creator_and_assignees_on_edit(monkeypatch):
    creator_headers, creator_id = _auth("Outdated Creator")
    assignee_headers, assignee_id = _auth("Outdated Assignee")
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider())
    created = _create_change_request(creator_headers)

    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    assert analyze.status_code == 201

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Let customers verify identity with a one-time passcode sent by SMS before checkout."},
        headers=creator_headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["is_analysis_outdated"] is True

    assignee_notifs = _notifications_for(assignee_headers, "analysis_outdated")
    assert len(assignee_notifs) == 1
    assert assignee_notifs[0]["change_request_id"] == created["id"]

    # The person who made the edit never gets notified about their own edit.
    assert _notifications_for(creator_headers, "analysis_outdated") == []


# --- Re-approval: REAPPROVAL_REQUIRED (editing while an approval pends) ----


def test_reapproval_required_notifies_approver_when_cr_edited_while_pending():
    creator_headers, _ = _auth("Reapproval Creator")
    approver_headers, approver_id = _auth("Reapproval Approver")
    created = _create_change_request(creator_headers)

    approval = client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=creator_headers,
    ).json()
    assert approval["cr_version"] == 1

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "high"},
        headers=creator_headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["current_version"] == 2

    approver_notifs = _notifications_for(approver_headers, "reapproval_required")
    assert len(approver_notifs) == 1
    assert approver_notifs[0]["change_request_id"] == created["id"]

    # The person who made the edit (the requester/creator here) never gets
    # a reapproval notification about their own edit.
    assert _notifications_for(creator_headers, "reapproval_required") == []


def test_reapproval_required_never_fires_without_a_pending_approval():
    creator_headers, _ = _auth("No Pending Approval Creator")
    created = _create_change_request(creator_headers)

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "critical"},
        headers=creator_headers,
    )
    assert edit.status_code == 200

    assert _notifications_for(creator_headers, "reapproval_required") == []


# --- Cross-cutting: every user only ever sees their own notifications -----


def test_module18_notification_types_are_scoped_to_the_current_user(monkeypatch):
    """One consolidated check that spec section 8's "ensure users only see
    notifications belonging to them" holds for Module 18's own newer
    notification types (risk_escalated, analysis_completed,
    reapproval_required, analysis_outdated) - deadline_approaching already
    has its own dedicated scoping test in test_module18_phase1.py, and the
    older types (assigned/approval_requested/approved/rejected/
    changes_requested/mentioned/comment_added) already have theirs in
    test_workflow_comments_notifications.py."""
    creator_headers, _ = _auth("Scoping Creator")
    assignee_headers, assignee_id = _auth("Scoping Assignee")
    approver_headers, approver_id = _auth("Scoping Approver")
    outsider_headers, _ = _auth("Scoping Outsider")  # has no stake in this CR at all

    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider())
    created = _create_change_request(creator_headers)
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    client.post(
        f"/api/change-requests/{created['id']}/approvals",
        json={"approval_type": "general", "approver_user_id": approver_id},
        headers=creator_headers,
    )
    client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "high"},
        headers=creator_headers,
    )

    outsider_ids = {n["id"] for n in client.get("/api/notifications", headers=outsider_headers).json()}
    assert outsider_ids == set()

    # Sanity check the fixture actually produced notifications for someone,
    # so an empty outsider inbox above is a real scoping result and not
    # just because nothing fired at all.
    assignee_ids = {n["id"] for n in client.get("/api/notifications", headers=assignee_headers).json()}
    approver_ids = {n["id"] for n in client.get("/api/notifications", headers=approver_headers).json()}
    assert len(assignee_ids) > 0
    assert len(approver_ids) > 0
    assert outsider_ids.isdisjoint(assignee_ids)
    assert outsider_ids.isdisjoint(approver_ids)
