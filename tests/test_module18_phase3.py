"""Verifies Module 18 Phase 3 (Notifications, My Work & Personal
Engineering Queue - "My Work" backend):

  * GET /api/my-work/change-requests - only change requests the CURRENT
    user personally created, never anyone else's.
  * GET /api/my-work/approvals - only approvals tagged to the current
    user; defaults to PENDING only (the real queue), ?status=all returns
    every status including already-decided ones.
  * GET /api/my-work/reviews - only change requests where the current user
    holds one of Reviewer/Technical Lead/Security Reviewer/Owner - a
    QA Owner or Implementation Owner assignment (real roles that exist,
    just not "review" roles) must NOT show up here...
  * GET /api/my-work/assignments - ...but MUST show up here, since this
    endpoint is "any assignment role at all", broader than /reviews.
  * GET /api/my-work/changes-requested - only change requests the current
    user OWNS where an approver responded Changes Requested - confirmed
    interpretation: this is "someone is waiting on ME", not "I asked
    someone else to make changes" (the approver who requested changes
    must never see it on their OWN changes-requested list).
  * GET /api/my-work/mentions - reuses the existing MENTIONED notification
    row, never a second mentions table.
  * GET /api/my-work/overdue - only PENDING approvals whose due_date has
    already passed - a due-soon-but-not-yet-overdue approval must NOT
    appear here.
  * GET /api/my-work/summary - counts agree with what each section
    endpoint actually returns.
  * Every one of the above is scoped to `current_user` - a second,
    unrelated user's own My Work never shows the first user's items.

Every test here uses a fake, monkeypatched AI provider where analysis is
needed - no real network call, matching this app's established testing
pattern. No test data ever uses grubbrr.com - alight.com throughout.

Run with (from backend/):  python -m pytest ../tests
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
    return f"m18p3-{uuid.uuid4().hex[:10]}@example.com"


def _auth(name: str = "Module18 Phase3 Tester") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict, title: str = "Add OTP authentication for customers") -> dict:
    payload = {
        "title": title,
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _assign(cr_id: int, headers: dict, user_id: int, role: str) -> dict:
    response = client.post(
        f"/api/change-requests/{cr_id}/assignments", json={"user_id": user_id, "role": role}, headers=headers
    )
    assert response.status_code == 201
    return response.json()


def _request_approval(cr_id: int, headers: dict, approver_id: int, due_date: str = None, approval_type: str = "security"):
    body = {"approval_type": approval_type, "approver_user_id": approver_id}
    if due_date is not None:
        body["due_date"] = due_date
    response = client.post(f"/api/change-requests/{cr_id}/approvals", json=body, headers=headers)
    assert response.status_code == 201
    return response.json()


def _respond(cr_id: int, approval_id: int, headers: dict, status_value: str, comment: str = None):
    body = {"status": status_value}
    if comment is not None:
        body["comment"] = comment
    response = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond", json=body, headers=headers
    )
    assert response.status_code == 200
    return response.json()


def test_my_change_requests_only_shows_my_own(monkeypatch):
    mine_headers, _mine_id = _auth("Owner Of My CRs")
    other_headers, _other_id = _auth("Someone Else Entirely")
    mine = _create_change_request(mine_headers, title="Add OTP authentication for customers")
    _create_change_request(other_headers, title="Add SSO login for Alight.com admins")

    response = client.get("/api/my-work/change-requests", headers=mine_headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert mine["id"] in ids
    assert len(ids) == 1


def test_my_approvals_defaults_to_pending_and_all_shows_everything(monkeypatch):
    owner_headers, _owner_id = _auth("Approvals Owner")
    approver_headers, approver_id = _auth("Approvals Approver")
    cr_a = _create_change_request(owner_headers, title="Add OTP authentication for customers")
    cr_b = _create_change_request(owner_headers, title="Add loyalty points to Alight.com checkout")

    pending_approval = _request_approval(cr_a["id"], owner_headers, approver_id, approval_type="security")
    resolved_approval = _request_approval(cr_b["id"], owner_headers, approver_id, approval_type="technical")
    _respond(cr_b["id"], resolved_approval["id"], approver_headers, "approved")

    pending_only = client.get("/api/my-work/approvals", headers=approver_headers)
    assert pending_only.status_code == 200
    pending_ids = {a["id"] for a in pending_only.json()}
    assert pending_ids == {pending_approval["id"]}

    everything = client.get("/api/my-work/approvals?status=all", headers=approver_headers)
    assert everything.status_code == 200
    all_ids = {a["id"] for a in everything.json()}
    assert all_ids == {pending_approval["id"], resolved_approval["id"]}


def test_my_reviews_excludes_non_review_roles_but_my_assignments_includes_them(monkeypatch):
    owner_headers, _owner_id = _auth("Roles Owner")
    person_headers, person_id = _auth("QA Owner Person")
    cr = _create_change_request(owner_headers)

    # qa_owner is a real AssignmentRole, but not one of the four "review"
    # roles (Reviewer/Technical Lead/Security Reviewer/Owner).
    _assign(cr["id"], owner_headers, person_id, "qa_owner")

    reviews = client.get("/api/my-work/reviews", headers=person_headers)
    assert reviews.status_code == 200
    assert cr["id"] not in {item["change_request_id"] for item in reviews.json()}

    assignments = client.get("/api/my-work/assignments", headers=person_headers)
    assert assignments.status_code == 200
    assignment_ids = {item["change_request_id"] for item in assignments.json()}
    assert cr["id"] in assignment_ids
    matching = next(item for item in assignments.json() if item["change_request_id"] == cr["id"])
    assert matching["roles"] == ["qa_owner"]


def test_my_reviews_includes_the_four_review_roles(monkeypatch):
    owner_headers, _owner_id = _auth("Review Roles Owner")
    reviewer_headers, reviewer_id = _auth("Security Reviewer Person")
    cr = _create_change_request(owner_headers)
    _assign(cr["id"], owner_headers, reviewer_id, "security_reviewer")

    reviews = client.get("/api/my-work/reviews", headers=reviewer_headers)
    assert reviews.status_code == 200
    ids = {item["change_request_id"] for item in reviews.json()}
    assert cr["id"] in ids


def test_changes_requested_from_me_shows_for_owner_not_for_the_approver(monkeypatch):
    owner_headers, _owner_id = _auth("Changes Requested Owner")
    approver_headers, approver_id = _auth("Changes Requesting Approver")
    cr = _create_change_request(owner_headers)
    approval = _request_approval(cr["id"], owner_headers, approver_id, approval_type="security")
    _respond(cr["id"], approval["id"], approver_headers, "changes_requested", comment="Please add rate limiting.")

    owner_view = client.get("/api/my-work/changes-requested", headers=owner_headers)
    assert owner_view.status_code == 200
    owner_ids = {item["change_request_id"] for item in owner_view.json()}
    assert cr["id"] in owner_ids
    matching = next(item for item in owner_view.json() if item["change_request_id"] == cr["id"])
    assert matching["comment"] == "Please add rate limiting."

    # The approver who personally requested the changes is NOT the CR's
    # owner - this must never show up on THEIR own changes-requested list.
    approver_view = client.get("/api/my-work/changes-requested", headers=approver_headers)
    assert approver_view.status_code == 200
    assert cr["id"] not in {item["change_request_id"] for item in approver_view.json()}


def test_mentions_reuses_the_mentioned_notification(monkeypatch):
    author_headers, _author_id = _auth("Comment Author")
    mentioned_headers, mentioned_id = _auth("Mentioned Person")
    cr = _create_change_request(author_headers)

    # Register the mentioned user's exact display name into the comment.
    mentioned_name = "Mentioned Person"
    comment = client.post(
        f"/api/change-requests/{cr['id']}/comments",
        json={"body": f"@{mentioned_name} can you take a look at this OTP flow?"},
        headers=author_headers,
    )
    assert comment.status_code == 201

    mentions = client.get("/api/my-work/mentions", headers=mentioned_headers)
    assert mentions.status_code == 200
    assert len(mentions.json()) == 1
    assert mentions.json()[0]["type"] == "mentioned"
    assert mentions.json()[0]["change_request_id"] == cr["id"]

    # The comment's own author never mentions themselves.
    author_mentions = client.get("/api/my-work/mentions", headers=author_headers)
    assert author_mentions.status_code == 200
    assert len(author_mentions.json()) == 0


def test_overdue_items_excludes_due_soon_and_resolved(monkeypatch):
    from datetime import datetime, timedelta

    owner_headers, _owner_id = _auth("Overdue Owner")
    approver_headers, approver_id = _auth("Overdue Approver")
    cr = _create_change_request(owner_headers)

    overdue = _request_approval(
        cr["id"], owner_headers, approver_id,
        due_date=(datetime.utcnow() - timedelta(days=2)).isoformat(),
        approval_type="security",
    )
    due_soon = _request_approval(
        cr["id"], owner_headers, approver_id,
        due_date=(datetime.utcnow() + timedelta(hours=6)).isoformat(),
        approval_type="technical",
    )
    resolved_but_overdue = _request_approval(
        cr["id"], owner_headers, approver_id,
        due_date=(datetime.utcnow() - timedelta(days=5)).isoformat(),
        approval_type="product",
    )
    _respond(cr["id"], resolved_but_overdue["id"], approver_headers, "approved")

    response = client.get("/api/my-work/overdue", headers=approver_headers)
    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert ids == {overdue["id"]}
    assert due_soon["id"] not in ids
    assert resolved_but_overdue["id"] not in ids


def test_summary_counts_match_section_endpoints(monkeypatch):
    owner_headers, _owner_id = _auth("Summary Owner")
    person_headers, person_id = _auth("Summary Person")
    cr = _create_change_request(owner_headers)
    _assign(cr["id"], owner_headers, person_id, "reviewer")
    approval = _request_approval(cr["id"], owner_headers, person_id, approval_type="security")

    summary = client.get("/api/my-work/summary", headers=person_headers)
    assert summary.status_code == 200
    body = summary.json()

    reviews = client.get("/api/my-work/reviews", headers=person_headers).json()
    assignments = client.get("/api/my-work/assignments", headers=person_headers).json()
    approvals_pending = client.get("/api/my-work/approvals", headers=person_headers).json()

    assert body["my_reviews"] == len(reviews)
    assert body["my_assignments"] == len(assignments)
    assert body["my_approvals_pending"] == len(approvals_pending)
    assert approval["id"] in {a["id"] for a in approvals_pending}


def test_scoping_never_leaks_between_users(monkeypatch):
    a_headers, a_id = _auth("Scoping User A")
    b_headers, b_id = _auth("Scoping User B")
    cr_a = _create_change_request(a_headers, title="Add OTP authentication for customers")

    # User B has nothing at all on cr_a - none of B's My Work endpoints
    # should show any trace of it.
    for path in ("/api/my-work/change-requests", "/api/my-work/reviews", "/api/my-work/assignments"):
        response = client.get(path, headers=b_headers)
        assert response.status_code == 200
        ids = {item.get("id") or item.get("change_request_id") for item in response.json()}
        assert cr_a["id"] not in ids
