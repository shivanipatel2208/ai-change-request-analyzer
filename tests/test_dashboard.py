"""Verifies the dashboard summary endpoint: it requires authentication, and
the metrics/risk distribution/category breakdown/recent list it returns are
computed from real rows written straight into the database - never
hardcoded or faked.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()  # make sure every table exists even if init_db was never run manually

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models import Analysis, ChangeRequest, ClarificationQuestion
from app.models.enums import ApprovalRecommendation, ChangeRequestStatus, ComplexityLevel, Priority

client = TestClient(app)


def _unique_email() -> str:
    return f"dash-{uuid.uuid4().hex[:10]}@example.com"


def _register_user() -> tuple[str, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Dash Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], body["user"]["id"]


def test_dashboard_requires_authentication():
    response = client.get("/dashboard/summary")
    assert response.status_code == 401


def test_dashboard_returns_well_formed_summary():
    token, _ = _register_user()
    response = client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert "metrics" in body
    assert "risk_distribution" in body
    assert "category_breakdown" in body
    assert "recent_change_requests" in body


def test_dashboard_reflects_real_change_request_data():
    token, user_id = _register_user()

    db = SessionLocal()
    try:
        cr_no_analysis = ChangeRequest(
            title="Pending analysis example",
            description="Not analyzed yet.",
            priority=Priority.MEDIUM,
            status=ChangeRequestStatus.DRAFT,
            created_by=user_id,
        )
        cr_high_risk = ChangeRequest(
            title="High risk example",
            description="Touches payments.",
            priority=Priority.HIGH,
            status=ChangeRequestStatus.SUBMITTED,
            created_by=user_id,
        )
        cr_approved = ChangeRequest(
            title="Approved example",
            description="Small safe fix.",
            priority=Priority.LOW,
            status=ChangeRequestStatus.APPROVED,
            created_by=user_id,
        )
        db.add_all([cr_no_analysis, cr_high_risk, cr_approved])
        db.flush()

        high_risk_analysis = Analysis(
            change_request_id=cr_high_risk.id,
            summary="Risky payments change.",
            category="security",
            complexity=ComplexityLevel.HIGH,
            risk_score=90.0,
            confidence_score=70.0,
            recommendation=ApprovalRecommendation.NEEDS_MORE_INFO,
        )
        approved_analysis = Analysis(
            change_request_id=cr_approved.id,
            summary="Safe small fix.",
            category="bug fix",
            complexity=ComplexityLevel.LOW,
            risk_score=10.0,
            confidence_score=95.0,
            recommendation=ApprovalRecommendation.APPROVE,
        )
        db.add_all([high_risk_analysis, approved_analysis])
        db.flush()

        db.add(
            ClarificationQuestion(
                analysis_id=high_risk_analysis.id,
                question="What's the rollback plan?",
                priority=Priority.HIGH,
                reason="Needed before approval.",
                resolved=False,
            )
        )
        db.commit()

        cr_ids = {
            "no_analysis": cr_no_analysis.id,
            "high_risk": cr_high_risk.id,
            "approved": cr_approved.id,
        }
    finally:
        db.close()

    response = client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()

    # These 3 rows were just inserted, so they're the most recent - always
    # within the top-10 recent list regardless of how much other data exists.
    by_id = {item["id"]: item for item in body["recent_change_requests"]}
    assert cr_ids["high_risk"] in by_id
    assert cr_ids["approved"] in by_id
    assert cr_ids["no_analysis"] in by_id

    assert by_id[cr_ids["high_risk"]]["risk"] == "critical"
    assert by_id[cr_ids["high_risk"]]["category"] == "Security"
    assert by_id[cr_ids["approved"]]["risk"] == "low"
    assert by_id[cr_ids["approved"]]["category"] == "Bug Fix"
    assert by_id[cr_ids["no_analysis"]]["risk"] is None
    assert by_id[cr_ids["no_analysis"]]["category"] is None

    metrics = body["metrics"]
    assert metrics["total_change_requests"] >= 3
    assert metrics["approved_changes"] >= 1
    assert metrics["high_risk_changes"] >= 1
    assert metrics["pending_analysis"] >= 1
    assert metrics["requires_clarification"] >= 1

    # --- Clicking a dashboard tile (spec: "make the tiles clickable, show
    # the underlying change requests in table format") must show exactly
    # the change requests that were counted for it - never a different
    # number than the tile itself, since both come from the same
    # classification (see app/api/dashboard.py::_classify_change_request).
    headers = {"Authorization": f"Bearer {token}"}

    def _drill_down(metric):
        response = client.get("/dashboard/drill-down", params={"metric": metric}, headers=headers)
        assert response.status_code == 200
        return response.json()

    total_drill = _drill_down("total")
    assert total_drill["total"] == metrics["total_change_requests"]
    # The popup never shows more than one page (capped at 10 rows) at a
    # time - see the pagination-specific tests below for paging through
    # the rest.
    assert total_drill["page"] == 1
    assert total_drill["page_size"] == 10
    assert len(total_drill["items"]) == min(metrics["total_change_requests"], 10)

    pending_drill = _drill_down("pending_analysis")
    assert pending_drill["total"] == metrics["pending_analysis"]
    assert cr_ids["no_analysis"] in {item["id"] for item in pending_drill["items"]}
    assert cr_ids["approved"] not in {item["id"] for item in pending_drill["items"]}

    high_risk_drill = _drill_down("high_risk")
    assert high_risk_drill["total"] == metrics["high_risk_changes"]
    assert cr_ids["high_risk"] in {item["id"] for item in high_risk_drill["items"]}
    assert cr_ids["approved"] not in {item["id"] for item in high_risk_drill["items"]}

    approved_drill = _drill_down("approved")
    assert approved_drill["total"] == metrics["approved_changes"]
    assert cr_ids["approved"] in {item["id"] for item in approved_drill["items"]}
    assert cr_ids["no_analysis"] not in {item["id"] for item in approved_drill["items"]}

    clarification_drill = _drill_down("requires_clarification")
    assert clarification_drill["total"] == metrics["requires_clarification"]
    assert cr_ids["high_risk"] in {item["id"] for item in clarification_drill["items"]}
    assert cr_ids["approved"] not in {item["id"] for item in clarification_drill["items"]}


def test_drill_down_date_range_filters_by_created_date():
    token, user_id = _register_user()
    headers = {"Authorization": f"Bearer {token}"}

    db = SessionLocal()
    try:
        cr = ChangeRequest(
            title="Date range filter probe CR",
            description="Only used to test date_from/date_to.",
            priority=Priority.MEDIUM,
            status=ChangeRequestStatus.DRAFT,
            created_by=user_id,
        )
        db.add(cr)
        db.commit()
        cr_id = cr.id
    finally:
        db.close()

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # A range that includes today finds it...
    in_range = client.get(
        "/dashboard/drill-down",
        params={"metric": "total", "date_from": today, "date_to": tomorrow},
        headers=headers,
    ).json()
    assert cr_id in {item["id"] for item in in_range["items"]}

    # ...a range entirely before today does not, and the filtered total
    # reflects that - never a mismatch between what's counted and what's
    # shown.
    out_of_range = client.get(
        "/dashboard/drill-down",
        params={"metric": "total", "date_from": yesterday, "date_to": yesterday},
        headers=headers,
    ).json()
    assert cr_id not in {item["id"] for item in out_of_range["items"]}
    assert out_of_range["total"] == len(out_of_range["items"])


def test_drill_down_pagination_pages_through_without_duplicates_or_gaps():
    token, user_id = _register_user()
    headers = {"Authorization": f"Bearer {token}"}

    db = SessionLocal()
    try:
        created_ids = []
        for i in range(12):
            cr = ChangeRequest(
                title=f"Pagination probe CR {i}",
                description="Only used to test drill-down pagination.",
                priority=Priority.MEDIUM,
                status=ChangeRequestStatus.DRAFT,
                created_by=user_id,
            )
            db.add(cr)
            db.flush()
            created_ids.append(cr.id)
        db.commit()
    finally:
        db.close()

    # The dashboard shows every change request in the system, not just this
    # user's own (matches this app's existing "no per-CR visibility
    # restriction" rule - see report_generator.py's own docstring). By the
    # time this test runs, dozens of other test files have already added
    # their own rows to this shared database, so `total` is only ever a
    # meaningless ">= 12" on its own, and page 2 can easily be filled out
    # entirely once our own rows run out - it is NOT safe to assume page 2
    # holds only our leftover 2 rows and nothing else.
    #
    # What's actually provable, and what this test verifies, is pagination
    # itself: ids are assigned in strict insertion order, and the endpoint
    # orders newest-first by (created_at desc, id desc) - see
    # app/api/dashboard.py::_load_classified_change_requests - so these 12
    # freshly-inserted rows are provably the highest ids in the whole table
    # and must occupy exactly the first 12 positions of the "total" list,
    # most-recently-inserted (highest id) first.
    def _page(page_size, page):
        response = client.get(
            "/dashboard/drill-down",
            params={"metric": "total", "page": page, "page_size": page_size},
            headers=headers,
        )
        assert response.status_code == 200
        return response.json()

    newest_first = list(reversed(created_ids))

    first_page = _page(10, 1)
    assert first_page["total"] >= 12
    assert [item["id"] for item in first_page["items"]] == newest_first[:10]

    second_page = _page(10, 2)
    # Positions 11 and 12 overall are our own last two rows, still in the
    # same id-descending order. Whatever else fills out the rest of this
    # page comes from older, pre-existing rows - and must never repeat
    # anything already shown on page 1.
    assert len(second_page["items"]) >= 2
    assert [item["id"] for item in second_page["items"][:2]] == newest_first[10:12]
    first_ids = {item["id"] for item in first_page["items"]}
    second_ids = {item["id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)

    # page_size above 10 is rejected outright - the popup never shows more
    # than 10 rows at once.
    assert client.get(
        "/dashboard/drill-down", params={"metric": "total", "page_size": 11}, headers=headers
    ).status_code == 422


def test_drill_down_requires_authentication():
    assert client.get("/dashboard/drill-down", params={"metric": "total"}).status_code == 401


def test_drill_down_rejects_unknown_metric():
    token, _ = _register_user()
    response = client.get(
        "/dashboard/drill-down",
        params={"metric": "not_a_real_metric"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
