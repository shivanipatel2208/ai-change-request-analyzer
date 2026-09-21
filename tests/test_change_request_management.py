"""Verifies Module 5 (Change Request Management): the list endpoint's
search/filter/sort/pagination, the computed "effective status" values, and
the enriched detail endpoint (latest analysis + clarification questions).

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models import Analysis, ChangeRequest, ClarificationQuestion
from app.models.enums import ChangeRequestStatus, ComplexityLevel, Priority

client = TestClient(app)


def _unique_email() -> str:
    return f"crm-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "CRM Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_via_api(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add loyalty points to checkout",
        "description": "Award loyalty points automatically when a customer checks out.",
        "priority": "medium",
        "requested_by": "Morgan Lee",
        "target_system": "POS Backend",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_list_response_has_items_total_limit_offset():
    headers, _ = _auth()
    response = client.get("/api/change-requests", headers=headers)
    assert response.status_code == 200
    body = response.json()
    for key in ("items", "total", "limit", "offset"):
        assert key in body


def test_search_matches_title():
    headers, _ = _auth()
    unique_word = f"Zephyr{uuid.uuid4().hex[:6]}"
    _create_via_api(headers, title=f"{unique_word} sync improvements")

    response = client.get("/api/change-requests", params={"search": unique_word}, headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert all(unique_word.lower() in item["title"].lower() for item in items)


def test_search_matches_ticket_number():
    headers, _ = _auth()
    created = _create_via_api(headers, title=f"Ticket search target {uuid.uuid4().hex[:6]}")
    ticket_id = created["id"]

    # Searching with the "#" prefix the UI displays should find it by id,
    # even though the id doesn't appear in the title/description/etc.
    response = client.get("/api/change-requests", params={"search": f"#{ticket_id}"}, headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["id"] == ticket_id for item in items)

    # Also works without the "#".
    response = client.get("/api/change-requests", params={"search": str(ticket_id)}, headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["id"] == ticket_id for item in items)


def test_filter_by_priority():
    headers, _ = _auth()
    _create_via_api(headers, title="Critical priority filter check", priority="critical")

    response = client.get("/api/change-requests", params={"priority": "critical"}, headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert all(item["priority"] == "critical" for item in items)


def test_filter_by_assigned_to_me():
    """Module 12 Phase 6: GET /api/change-requests?assigned_to_me=true -
    only change requests the CURRENT user is assigned to, in any role."""
    creator_headers, _ = _auth()
    assignee_headers, assignee_id = _auth()
    bystander_headers, _ = _auth()

    created = _create_via_api(creator_headers, title=f"Assigned-to-me filter check {uuid.uuid4().hex[:6]}")
    response = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    assert response.status_code == 201

    # The assignee sees it when filtering to their own assignments.
    response = client.get("/api/change-requests", params={"assigned_to_me": "true"}, headers=assignee_headers)
    assert response.status_code == 200
    assert any(item["id"] == created["id"] for item in response.json()["items"])

    # Someone never assigned to anything does not see it.
    response = client.get("/api/change-requests", params={"assigned_to_me": "true"}, headers=bystander_headers)
    assert response.status_code == 200
    assert all(item["id"] != created["id"] for item in response.json()["items"])

    # Without the filter, everyone can still see it (it's a real, visible
    # change request - assigned_to_me only narrows, it never hides).
    response = client.get("/api/change-requests", headers=bystander_headers)
    assert response.status_code == 200
    assert any(item["id"] == created["id"] for item in response.json()["items"])


def test_new_request_has_pending_analysis_effective_status():
    headers, _ = _auth()
    created = _create_via_api(headers, title="Freshly created, not analyzed yet")

    response = client.get("/api/change-requests", params={"status": "pending_analysis"}, headers=headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert created["id"] in ids


def test_invalid_status_filter_returns_422():
    headers, _ = _auth()
    response = client.get("/api/change-requests", params={"status": "not_a_real_status"}, headers=headers)
    assert response.status_code == 422


def test_effective_status_transitions_with_analysis_and_clarifications():
    headers, user_id = _auth()
    created = _create_via_api(headers, title="Needs clarification before approval")

    db = SessionLocal()
    try:
        analysis = Analysis(
            change_request_id=created["id"],
            summary="Touches customer data - needs a rollback plan confirmed.",
            category="security",
            complexity=ComplexityLevel.HIGH,
            risk_score=70.0,
            confidence_score=65.0,
        )
        db.add(analysis)
        db.flush()
        db.add(
            ClarificationQuestion(
                analysis_id=analysis.id,
                question="What's the rollback plan?",
                priority=Priority.HIGH,
                reason="Needed before approval.",
                resolved=False,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/change-requests", params={"status": "requires_clarification"}, headers=headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert created["id"] in ids

    # Resolve the question - it should move to "completed".
    db = SessionLocal()
    try:
        analysis_row = db.query(Analysis).filter(Analysis.change_request_id == created["id"]).first()
        question = (
            db.query(ClarificationQuestion)
            .filter(ClarificationQuestion.analysis_id == analysis_row.id)
            .first()
        )
        question.resolved = True
        db.commit()
    finally:
        db.close()

    response = client.get("/api/change-requests", params={"status": "completed"}, headers=headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert created["id"] in ids


def test_approved_status_overrides_analysis_state():
    headers, user_id = _auth()
    created = _create_via_api(headers, title="Already approved by a reviewer")

    db = SessionLocal()
    try:
        cr = db.get(ChangeRequest, created["id"])
        cr.status = ChangeRequestStatus.APPROVED
        db.commit()
    finally:
        db.close()

    response = client.get("/api/change-requests", params={"status": "approved"}, headers=headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert created["id"] in ids


def test_sort_newest_orders_most_recent_first():
    headers, _ = _auth()
    _create_via_api(headers, title="Sort check A")
    second = _create_via_api(headers, title="Sort check B")

    response = client.get("/api/change-requests", params={"sort": "newest", "limit": 1}, headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["id"] == second["id"]


def test_detail_endpoint_includes_latest_analysis_and_questions():
    headers, _ = _auth()
    created = _create_via_api(headers, title="Detail view with an analysis")

    db = SessionLocal()
    try:
        analysis = Analysis(
            change_request_id=created["id"],
            summary="Small, contained change.",
            category="Bug Fix",
            complexity=ComplexityLevel.LOW,
            risk_score=15.0,
            confidence_score=90.0,
        )
        db.add(analysis)
        db.flush()
        db.add(
            ClarificationQuestion(
                analysis_id=analysis.id,
                question="Any edge cases with refunds?",
                priority=Priority.MEDIUM,
                reason="Worth confirming before shipping.",
                resolved=True,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/change-requests/{created['id']}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["effective_status"] == "completed"
    assert body["latest_analysis"] is not None
    assert body["latest_analysis"]["category"] == "Bug Fix"
    assert len(body["latest_analysis"]["clarification_questions"]) == 1


def test_detail_endpoint_without_analysis_has_null_latest_analysis():
    headers, _ = _auth()
    created = _create_via_api(headers, title="Detail view without an analysis yet")

    response = client.get(f"/api/change-requests/{created['id']}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["effective_status"] == "pending_analysis"
    assert body["latest_analysis"] is None
