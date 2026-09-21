"""Verifies Module 19 Phase 7 (Engineering Change Analytics) - the final
testing pass the spec's own section 10 asks for: calculations checked
against real database records, empty data, a larger dataset, and filters,
across all 6 analytics endpoints together. Phases 1-5 already covered each
endpoint's own logic in detail (see those files); this file's job is the
four things spec section 10 asks for explicitly, end-to-end, rather than
one more slice of any single endpoint's business rules.

This project's bulk-synthetic dataset (`app/database/seed_bulk.py`, ~3000
rows) is a standalone CLI script never run as part of `init_db()` or this
test suite - the shared pytest database never contains it. "Test large
data" here instead means a real, moderately large set of change requests
(60) created through this test file itself, independently counted in
Python and compared against what the endpoints report - large enough to
be a genuine multi-row aggregation check, not just "does it happen to work
for one row."

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

ANALYTICS_ENDPOINTS = [
    "/api/analytics/executive",
    "/api/analytics/risk",
    "/api/analytics/approval-bottlenecks",
    "/api/analytics/change",
    "/api/analytics/workload",
    "/api/analytics/ai",
]


def _unique_email() -> str:
    return f"m19p7-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module19 Phase7 Tester") -> tuple[dict, int]:
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
        "title": "Module 19 Phase 7 fixture change request",
        "description": "A change request used only to exercise the final analytics testing pass.",
        "business_objective": "N/A - test fixture.",
        "priority": "medium",
        "requested_by": "Test Fixture",
        "target_system": "Test System",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_every_endpoint_handles_a_brand_new_user_with_zero_data():
    """Empty data (spec 10.2): a freshly-registered user who has never
    created a change request. Every endpoint must respond 200 with a real
    "nothing yet" shape - zero counts, null averages, empty lists - never
    an error, and never a stray row belonging to some other test."""
    headers, owner_id = _auth("Phase7 Empty Data User")

    for path in ANALYTICS_ENDPOINTS:
        response = client.get(path, params={"owner_id": owner_id}, headers=headers)
        assert response.status_code == 200, f"{path} failed on empty data: {response.text}"

    executive = client.get("/api/analytics/executive", params={"owner_id": owner_id}, headers=headers).json()
    assert executive["executive"]["total"] == 0
    assert executive["workflow"]["avg_time_to_analysis_hours"] is None

    risk = client.get("/api/analytics/risk", params={"owner_id": owner_id}, headers=headers).json()
    assert risk["current_distribution"] == {"low": 0, "medium": 0, "high": 0, "critical": 0, "not_analyzed": 0}
    assert risk["over_time"] == []

    bottlenecks = client.get(
        "/api/analytics/approval-bottlenecks", params={"owner_id": owner_id}, headers=headers
    ).json()
    assert bottlenecks["pending_by_type"] == {}
    assert bottlenecks["pending_by_person"] == []
    assert bottlenecks["most_common_blockers"] == []

    change = client.get("/api/analytics/change", params={"owner_id": owner_id}, headers=headers).json()
    assert change["crs_with_multiple_revisions"] == 0
    assert change["avg_versions_per_cr"] is None
    assert change["most_changed_fields"] == []

    workload = client.get("/api/analytics/workload", params={"owner_id": owner_id}, headers=headers).json()
    assert workload["crs_per_owner"] == []
    assert workload["pending_reviews"] == 0

    ai = client.get("/api/analytics/ai", params={"owner_id": owner_id}, headers=headers).json()
    assert ai["total_analyses"] == 0
    assert ai["re_analysis_rate"] is None
    assert ai["average_confidence"] is None


def test_large_dataset_totals_and_filters_match_an_independent_python_count():
    """Large data + filters (spec 10.3/10.4), verified against real
    database records (spec 10.1): create 60 change requests under one
    owner with a deliberately uneven priority mix, independently count
    them in Python, and confirm both the unfiltered total and a
    priority-filtered count match the endpoint exactly - not an
    approximation."""
    headers, owner_id = _auth("Phase7 Large Dataset Owner")

    priorities = (["high"] * 15) + (["medium"] * 25) + (["low"] * 20)
    assert len(priorities) == 60
    for i, priority in enumerate(priorities):
        _create_change_request(headers, title=f"Phase7 bulk fixture #{i}", priority=priority)

    expected_high_count = sum(1 for p in priorities if p == "high")

    unfiltered = client.get("/api/analytics/executive", params={"owner_id": owner_id}, headers=headers)
    assert unfiltered.status_code == 200
    assert unfiltered.json()["executive"]["total"] == len(priorities)

    filtered = client.get(
        "/api/analytics/executive", params={"owner_id": owner_id, "priority": "high"}, headers=headers
    )
    assert filtered.status_code == 200
    assert filtered.json()["executive"]["total"] == expected_high_count

    # Every one of these 60 is freshly created (PENDING_ANALYSIS) - all
    # should land in the "Open" bucket, none anywhere else.
    executive = unfiltered.json()["executive"]
    assert executive["open"] == len(priorities)
    assert executive["closed"] == 0
    assert executive["approved"] == 0

    # Workload's own per-owner breakdown must agree with the same total -
    # cross-endpoint consistency, not just internal to one endpoint.
    workload = client.get("/api/analytics/workload", params={"owner_id": owner_id}, headers=headers).json()
    owner_counts = {entry["owner_name"]: entry["count"] for entry in workload["crs_per_owner"]}
    assert owner_counts.get("Phase7 Large Dataset Owner") == len(priorities)


def test_totals_agree_with_the_plain_change_requests_list_endpoint():
    """Cross-checks analytics against the plain change-requests list
    endpoint (not just against Python's own count) - the most direct
    "verify against real database records" check available: two
    independently-implemented endpoints reading the same rows must agree.
    `ChangeRequestListItem` has no owner field to filter list by, so this
    scopes both sides the same way instead - a unique title fragment only
    this test's own fixtures use, via the list endpoint's own `search`
    parameter."""
    headers, owner_id = _auth("Phase7 Cross-Check Owner")
    unique_marker = f"phase7-cross-check-{uuid.uuid4().hex[:8]}"
    for i in range(5):
        _create_change_request(headers, title=f"Phase7 cross-check fixture {unique_marker} #{i}")

    list_response = client.get("/api/change-requests", params={"search": unique_marker}, headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 5

    executive = client.get("/api/analytics/executive", params={"owner_id": owner_id}, headers=headers).json()
    assert executive["executive"]["total"] == 5


def test_invalid_owner_id_returns_empty_rather_than_error():
    headers, _ = _auth("Phase7 Invalid Owner Requester")
    response = client.get("/api/analytics/executive", params={"owner_id": 999999999}, headers=headers)
    assert response.status_code == 200
    assert response.json()["executive"]["total"] == 0
