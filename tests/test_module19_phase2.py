"""Verifies Module 19 Phase 2 (Engineering Change Analytics): the new
GET /api/analytics/executive endpoint - spec section 1 (Executive Metrics)
and section 2 (Workflow Metrics), computed together over real database
rows this test file creates itself (never invented numbers - every count
asserted below is checked against change requests this file can see the
full lifecycle of).

Following this project's established HTTP-only testing convention, every
check here goes through real endpoints: change requests are created and
walked through the real status-transition endpoint
(PUT /{id}/status), approvals through the real approval request/respond
endpoints, analyses through the real /analyze endpoint (monkeypatched
provider) - never a direct database write.

Run with (from backend/):  pytest ../tests
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

import app.services.analysis_engine as analysis_engine
from app.main import app

client = TestClient(app)

CONFIG_CHANGE_RESPONSE = {
    "summary": "Adds a configurable timeout to the payment gateway client.",
    "classification": {"category": "Configuration", "confidence": 0.8, "reason": "Tunable value only."},
    "requirements": [
        {"category": "functional", "description": "Add a timeout config value.", "priority": "medium"},
    ],
    "affected_components": [
        {
            "name": "Payment Client",
            "type": "backend",
            "impact_level": "low",
            "reason": "Reads a new timeout value.",
            "confidence": 70,
        }
    ],
    "dependencies": [],
    "risks": [],
    "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
    "complexity": {"level": "low", "reasoning": "Single config value."},
    "effort": {"backend": "1 day", "frontend": "Insufficient information.", "testing": "0.5 day", "total": "1-2 developer-days"},
    "missing_information": [],
    "test_cases": [
        {
            "id": "TC-001",
            "title": "Timeout applies to slow gateway calls",
            "type": "integration",
            "priority": "medium",
            "description": "Verify the configured timeout is honored.",
            "expected_result": "Call aborts at the configured timeout.",
        }
    ],
    "implementation_plan": [
        {
            "task": "Add timeout config field",
            "description": "Add a validated numeric timeout config field.",
            "component": "Payment Client",
            "priority": "medium",
            "estimated_effort": "4h",
        }
    ],
    "recommendation": {"decision": "approve", "reasoning": "Small, well-scoped, low risk."},
}


class _FixedProvider:
    def __init__(self, response_text):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(json.dumps(CONFIG_CHANGE_RESPONSE)))


def _unique_email() -> str:
    return f"m19p2-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module19 Phase2 Tester") -> tuple[dict, int]:
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
        "title": "Add payment gateway timeout config",
        "description": "Make the payment gateway client timeout configurable instead of hardcoded.",
        "business_objective": "Avoid hung requests during gateway outages.",
        "priority": "medium",
        "requested_by": "Jamie Alight",
        "target_system": "Payment Service",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _set_status(headers: dict, cr_id: int, target: str, reason: str | None = None) -> None:
    payload = {"status": target}
    if reason is not None:
        payload["reason"] = reason
    response = client.put(f"/api/change-requests/{cr_id}/status", json=payload, headers=headers)
    assert response.status_code == 200, response.text


def _get_executive(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/executive", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_executive_metrics_bucket_a_pending_analysis_cr_as_open():
    headers, owner_id = _auth()
    created = _create_change_request(headers)

    data = _get_executive(headers, owner_id=owner_id)
    assert data["executive"]["total"] == 1
    assert data["executive"]["open"] == 1
    assert data["executive"]["pending_approval"] == 0
    assert data["executive"]["approved"] == 0
    assert data["executive"]["closed"] == 0


def test_executive_metrics_approval_required_bucket():
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _set_status(headers, created["id"], "analyzed")
    _set_status(headers, created["id"], "in_review")
    _set_status(headers, created["id"], "approval_required")

    data = _get_executive(headers, owner_id=owner_id)
    assert data["executive"]["pending_approval"] == 1
    assert data["executive"]["open"] == 0


def test_executive_metrics_full_lifecycle_to_closed():
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    cr_id = created["id"]
    for target in (
        "analyzed",
        "in_review",
        "approval_required",
        "approved",
        "implementation_planned",
        "in_progress",
        "implemented",
        "validated",
        "closed",
    ):
        _set_status(headers, cr_id, target)

    data = _get_executive(headers, owner_id=owner_id)
    assert data["executive"]["closed"] == 1
    assert data["executive"]["total"] == 1
    # Every other named bucket is 0 - a CR only ever occupies exactly one.
    assert data["executive"]["open"] == 0
    assert data["executive"]["pending_approval"] == 0
    assert data["executive"]["approved"] == 0
    assert data["executive"]["rejected"] == 0
    assert data["executive"]["in_progress"] == 0

    # Workflow metrics: this CR really did reach In Progress and Closed, so
    # both averages should now be real, non-negative numbers, not null.
    assert data["workflow"]["avg_time_to_implementation_hours"] is not None
    assert data["workflow"]["avg_time_to_implementation_hours"] >= 0
    assert data["workflow"]["avg_time_to_closure_hours"] is not None
    assert data["workflow"]["avg_time_to_closure_hours"] >= 0


def test_executive_metrics_cancelled_counts_in_total_but_no_named_bucket():
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _set_status(headers, created["id"], "cancelled", reason="No longer needed.")

    data = _get_executive(headers, owner_id=owner_id)
    assert data["executive"]["total"] == 1
    assert data["executive"]["open"] == 0
    assert data["executive"]["pending_approval"] == 0
    assert data["executive"]["approved"] == 0
    assert data["executive"]["rejected"] == 0
    assert data["executive"]["in_progress"] == 0
    assert data["executive"]["closed"] == 0


def test_workflow_avg_time_to_analysis_and_crs_with_requested_changes(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201

    data = _get_executive(headers, owner_id=owner_id)
    assert data["workflow"]["avg_time_to_analysis_hours"] is not None
    assert data["workflow"]["avg_time_to_analysis_hours"] >= 0

    # No CR here has ever been moved to Changes Requested.
    assert data["workflow"]["crs_with_requested_changes"] == 0


def test_workflow_crs_with_requested_changes_and_no_data_defaults():
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _set_status(headers, created["id"], "analyzed")
    _set_status(headers, created["id"], "in_review")
    _set_status(headers, created["id"], "changes_requested", reason="Needs more detail.")

    data = _get_executive(headers, owner_id=owner_id)
    assert data["executive"]["open"] == 1  # CHANGES_REQUESTED is one of the "open" statuses
    assert data["workflow"]["crs_with_requested_changes"] == 1
    # This CR was never analyzed, so there's nothing to average - null, not 0.
    assert data["workflow"]["avg_time_to_analysis_hours"] is None


def test_workflow_approval_duration_and_waiting_for_approval(monkeypatch):
    requester_headers, requester_id = _auth("Approval Requester Phase2")
    approver_headers, approver_id = _auth("Approver Phase2")
    created = _create_change_request(requester_headers)
    cr_id = created["id"]
    _set_status(requester_headers, cr_id, "analyzed")
    _set_status(requester_headers, cr_id, "in_review")

    request_response = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": "technical", "approver_user_id": approver_id},
        headers=requester_headers,
    )
    assert request_response.status_code == 201
    approval_id = request_response.json()["id"]

    # Still pending: counts toward crs_waiting_for_approval.
    mid_data = _get_executive(requester_headers, owner_id=requester_id)
    assert mid_data["workflow"]["crs_waiting_for_approval"] == 1
    assert mid_data["workflow"]["avg_approval_time_hours"] is None

    respond_response = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert respond_response.status_code == 200

    final_data = _get_executive(requester_headers, owner_id=requester_id)
    assert final_data["workflow"]["crs_waiting_for_approval"] == 0
    assert final_data["workflow"]["avg_approval_time_hours"] is not None
    assert final_data["workflow"]["avg_approval_time_hours"] >= 0


def test_owner_filter_scopes_to_only_that_owners_change_requests():
    headers_a, owner_a = _auth("Owner A Phase2")
    headers_b, owner_b = _auth("Owner B Phase2")
    _create_change_request(headers_a)
    _create_change_request(headers_b)
    _create_change_request(headers_b)

    data_a = _get_executive(headers_a, owner_id=owner_a)
    data_b = _get_executive(headers_a, owner_id=owner_b)
    assert data_a["executive"]["total"] == 1
    assert data_b["executive"]["total"] == 2


def test_invalid_risk_filter_returns_422():
    headers, _ = _auth()
    response = client.get("/api/analytics/executive", params={"risk": "extreme"}, headers=headers)
    assert response.status_code == 422


def test_invalid_category_filter_returns_422():
    headers, _ = _auth()
    response = client.get("/api/analytics/executive", params={"category": "Not A Real Category"}, headers=headers)
    assert response.status_code == 422


def test_executive_endpoint_requires_authentication():
    response = client.get("/api/analytics/executive")
    assert response.status_code == 401
