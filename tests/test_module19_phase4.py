"""Verifies Module 19 Phase 4 (Engineering Change Analytics): the new
GET /api/analytics/change and GET /api/analytics/workload endpoints - spec
sections 5 (Change Analytics) and 6 (Workload) - against real database rows
this test file creates itself.

Following this project's established HTTP-only testing convention, every
check here goes through real endpoints: edits via the real PUT
/{id} endpoint (version bump + FIELD_CHANGED history), analyses via the
real /analyze endpoint (monkeypatched provider, controlling
missing_information to produce a real, unresolved ClarificationQuestion),
assignments and approvals via their own real endpoints - never a direct
database write.

Run with (from backend/):  pytest ../tests
"""
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

import app.services.analysis_engine as analysis_engine
from app.main import app

client = TestClient(app)


def _analysis_response(*, with_missing_information: bool) -> dict:
    missing_information = []
    if with_missing_information:
        missing_information = [
            {
                "question": "Which environments does this rollout target?",
                "priority": "important",
                "reason": "The change request doesn't say whether this covers staging, production, or both.",
            }
        ]
    return {
        "summary": "A test change used only to exercise Module 19 Phase 4's analytics endpoints.",
        "classification": {"category": "Configuration", "confidence": 0.8, "reason": "Test fixture."},
        "requirements": [
            {"category": "functional", "description": "Test fixture requirement.", "priority": "medium"},
        ],
        "affected_components": [
            {
                "name": "Test Component",
                "type": "backend",
                "impact_level": "low",
                "reason": "Test fixture.",
                "confidence": 70,
            }
        ],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
        "complexity": {"level": "low", "reasoning": "Test fixture."},
        "effort": {"backend": "1 day", "frontend": "Insufficient information.", "testing": "0.5 day", "total": "1-2 developer-days"},
        "missing_information": missing_information,
        "test_cases": [
            {
                "id": "TC-001",
                "title": "Test fixture case",
                "type": "integration",
                "priority": "medium",
                "description": "Test fixture.",
                "expected_result": "Test fixture.",
            }
        ],
        "implementation_plan": [
            {
                "task": "Test fixture task",
                "description": "Test fixture.",
                "component": "Test Component",
                "priority": "medium",
                "estimated_effort": "4h",
            }
        ],
        "recommendation": {
            "decision": "requires_clarification" if with_missing_information else "approve",
            "reasoning": "Test fixture.",
        },
    }


class _FixedProvider:
    def __init__(self, response_text):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch, *, with_missing_information: bool) -> None:
    monkeypatch.setattr(
        analysis_engine,
        "get_ai_provider",
        lambda: _FixedProvider(json.dumps(_analysis_response(with_missing_information=with_missing_information))),
    )


def _unique_email() -> str:
    return f"m19p4-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module19 Phase4 Tester") -> tuple[dict, int]:
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
        "title": "Module 19 Phase 4 fixture change request",
        "description": "A change request used only to exercise the change/workload analytics endpoints.",
        "business_objective": "N/A - test fixture.",
        "priority": "medium",
        "requested_by": "Test Fixture",
        "target_system": "Test System",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _get_change(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/change", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _get_workload(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/workload", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_no_multiple_revisions_when_never_edited():
    headers, owner_id = _auth()
    _create_change_request(headers)

    data = _get_change(headers, owner_id=owner_id)
    assert data["crs_with_multiple_revisions"] == 0
    assert data["avg_versions_per_cr"] == 1.0
    assert data["most_changed_fields"] == []


def test_editing_bumps_multiple_revisions_and_most_changed_fields():
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    response = client.put(
        f"/api/change-requests/{created['id']}", json={"priority": "high"}, headers=headers
    )
    assert response.status_code == 200

    data = _get_change(headers, owner_id=owner_id)
    assert data["crs_with_multiple_revisions"] == 1
    assert data["avg_versions_per_cr"] == 2.0
    field_labels = {entry["field_label"]: entry["count"] for entry in data["most_changed_fields"]}
    assert field_labels.get("Priority") == 1


def test_crs_returned_for_clarification(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, with_missing_information=True)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201

    data = _get_change(headers, owner_id=owner_id)
    assert data["crs_returned_for_clarification"] == 1


def test_no_clarification_needed_when_nothing_missing(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, with_missing_information=False)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201

    data = _get_change(headers, owner_id=owner_id)
    assert data["crs_returned_for_clarification"] == 0


def test_workload_crs_per_owner():
    headers_a, owner_a = _auth("Workload Owner A Phase4")
    headers_b, owner_b = _auth("Workload Owner B Phase4")
    _create_change_request(headers_a)
    _create_change_request(headers_b)
    _create_change_request(headers_b)

    data = _get_workload(headers_a, owner_id=owner_a)
    owners = {entry["owner_name"]: entry["count"] for entry in data["crs_per_owner"]}
    assert owners == {"Workload Owner A Phase4": 1}

    data_b = _get_workload(headers_a, owner_id=owner_b)
    owners_b = {entry["owner_name"]: entry["count"] for entry in data_b["crs_per_owner"]}
    assert owners_b == {"Workload Owner B Phase4": 2}


def test_workload_pending_reviews_pending_approvals_and_overdue():
    owner_headers, owner_id = _auth("Workload Requester Phase4")
    reviewer_headers, reviewer_id = _auth("Workload Reviewer Phase4")
    approver_headers, approver_id = _auth("Workload Approver Phase4")
    created = _create_change_request(owner_headers)
    cr_id = created["id"]

    assign_response = client.post(
        f"/api/change-requests/{cr_id}/assignments",
        json={"user_id": reviewer_id, "role": "reviewer"},
        headers=owner_headers,
    )
    assert assign_response.status_code == 201

    status_response = client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "analyzed"}, headers=owner_headers
    )
    assert status_response.status_code == 200
    status_response = client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "in_review"}, headers=owner_headers
    )
    assert status_response.status_code == 200

    past_due = (datetime.utcnow() - timedelta(days=3)).isoformat()
    approval_response = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": "technical", "approver_user_id": approver_id, "due_date": past_due},
        headers=owner_headers,
    )
    assert approval_response.status_code == 201

    data = _get_workload(owner_headers, owner_id=owner_id)
    assert data["pending_reviews"] == 1
    assert data["pending_approvals"] == 1
    assert data["overdue_tasks"] == 1


def test_workload_excludes_bulk_seed_bot_accounts_from_crs_per_owner():
    # loadtest1@alight.com is one of the app's own bulk-seed accounts (see
    # backend/app/database/seed_bulk.py) - never created through this test
    # file, so this only asserts it's absent from the breakdown when it
    # exists, not that it was ever present.
    headers, owner_id = _auth("Workload Real User Phase4")
    _create_change_request(headers)

    data = _get_workload(headers, owner_id=owner_id)
    owner_names = {entry["owner_name"] for entry in data["crs_per_owner"]}
    assert not any("loadtest" in name.lower() for name in owner_names)


def test_change_and_workload_endpoints_require_authentication():
    assert client.get("/api/analytics/change").status_code == 401
    assert client.get("/api/analytics/workload").status_code == 401
