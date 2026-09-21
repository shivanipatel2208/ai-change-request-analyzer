"""Verifies Module 19 Phase 3 (Engineering Change Analytics): the new
GET /api/analytics/risk and GET /api/analytics/approval-bottlenecks
endpoints - spec sections 3 (Risk Analytics) and 4 (Approval Bottlenecks) -
against real database rows this test file creates itself.

Following this project's established HTTP-only testing convention, every
check here goes through real endpoints: analyses via the real /analyze
endpoint (monkeypatched provider, controlling the resulting risk_score via
the AI response's own `risks` list - see
app/services/analysis_engine.py::_overall_risk_score, which this file
mirrors rather than reimplements), approvals through the real approval
request/respond endpoints, never a direct database write.

Run with (from backend/):  pytest ../tests
"""
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

import app.services.analysis_engine as analysis_engine
from app.main import app

client = TestClient(app)


def _analysis_response(risk_score: float | None) -> dict:
    """A minimal, schema-valid AI response. risk_score is controlled via
    the `risks` list exactly the way _overall_risk_score computes it: no
    risks -> 5.0 (low); one risk with the given score -> that score."""
    risks = []
    if risk_score is not None:
        risks = [
            {
                "category": "operational",
                "description": "A risk used only to pin the overall risk score for this test.",
                "severity": "high" if risk_score >= 50 else "low",
                "probability": 0.5,
                "score": risk_score,
                "explanation": "Deterministic test fixture risk.",
                "mitigation": "N/A - test fixture.",
            }
        ]
    return {
        "summary": "A test change used only to exercise Module 19 Phase 3's analytics endpoints.",
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
        "risks": risks,
        "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
        "complexity": {"level": "low", "reasoning": "Test fixture."},
        "effort": {"backend": "1 day", "frontend": "Insufficient information.", "testing": "0.5 day", "total": "1-2 developer-days"},
        "missing_information": [],
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
        "recommendation": {"decision": "approve", "reasoning": "Test fixture - deterministic risk score only."},
    }


class _FixedProvider:
    def __init__(self, response_text):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch, risk_score: float | None) -> None:
    monkeypatch.setattr(
        analysis_engine, "get_ai_provider", lambda: _FixedProvider(json.dumps(_analysis_response(risk_score)))
    )


def _unique_email() -> str:
    return f"m19p3-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module19 Phase3 Tester") -> tuple[dict, int]:
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
        "title": "Module 19 Phase 3 fixture change request",
        "description": "A change request used only to exercise the risk/approval-bottleneck analytics endpoints.",
        "business_objective": "N/A - test fixture.",
        "priority": "medium",
        "requested_by": "Test Fixture",
        "target_system": "Test System",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _analyze(headers: dict, cr_id: int, monkeypatch, risk_score: float | None) -> None:
    _patch_provider(monkeypatch, risk_score)
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201, response.text


def _set_status(headers: dict, cr_id: int, target: str, reason: str | None = None) -> None:
    payload = {"status": target}
    if reason is not None:
        payload["reason"] = reason
    response = client.put(f"/api/change-requests/{cr_id}/status", json=payload, headers=headers)
    assert response.status_code == 200, response.text


def _get_risk(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/risk", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _get_bottlenecks(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/approval-bottlenecks", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_risk_not_analyzed_bucket():
    headers, owner_id = _auth()
    _create_change_request(headers)

    data = _get_risk(headers, owner_id=owner_id)
    assert data["current_distribution"]["not_analyzed"] == 1
    assert data["current_distribution"]["low"] == 0


def test_risk_low_bucket_when_no_risks_returned(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch, risk_score=None)

    data = _get_risk(headers, owner_id=owner_id)
    assert data["current_distribution"]["low"] == 1
    assert data["current_distribution"]["not_analyzed"] == 0


def test_risk_critical_bucket_and_over_time_entry(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch, risk_score=90)

    data = _get_risk(headers, owner_id=owner_id)
    assert data["current_distribution"]["critical"] == 1

    this_month = datetime.utcnow().strftime("%Y-%m")
    matching_periods = [point for point in data["over_time"] if point["period"] == this_month]
    assert len(matching_periods) == 1
    assert matching_periods[0]["critical"] == 1
    assert matching_periods[0]["low"] == 0


def test_bottlenecks_pending_by_type_and_person():
    requester_headers, requester_id = _auth("Bottleneck Requester Phase3")
    approver_headers, approver_id = _auth("Bottleneck Approver Phase3")
    created = _create_change_request(requester_headers)
    cr_id = created["id"]
    _set_status(requester_headers, cr_id, "analyzed")
    _set_status(requester_headers, cr_id, "in_review")

    response = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": "security", "approver_user_id": approver_id},
        headers=requester_headers,
    )
    assert response.status_code == 201

    data = _get_bottlenecks(requester_headers, owner_id=requester_id)
    assert data["pending_by_type"].get("Security") == 1
    assert len(data["pending_by_person"]) == 1
    entry = data["pending_by_person"][0]
    # Only a name and a count - no email or other account details leak here.
    assert set(entry.keys()) == {"approver_name", "count"}
    assert entry["count"] == 1


def test_bottlenecks_avg_duration_and_blockers_after_rejection():
    requester_headers, requester_id = _auth("Bottleneck Requester2 Phase3")
    approver_headers, approver_id = _auth("Bottleneck Approver2 Phase3")
    created = _create_change_request(requester_headers)
    cr_id = created["id"]
    _set_status(requester_headers, cr_id, "analyzed")
    _set_status(requester_headers, cr_id, "in_review")

    response = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": "technical", "approver_user_id": approver_id},
        headers=requester_headers,
    )
    approval_id = response.json()["id"]

    respond = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond",
        json={"status": "rejected", "comment": "Not ready yet."},
        headers=approver_headers,
    )
    assert respond.status_code == 200

    data = _get_bottlenecks(requester_headers, owner_id=requester_id)
    assert data["pending_by_type"] == {}
    assert data["avg_duration_hours_by_type"].get("Technical") is not None
    assert data["avg_duration_hours_by_type"]["Technical"] >= 0
    blocker_labels = {entry["approval_type_label"]: entry["count"] for entry in data["most_common_blockers"]}
    assert blocker_labels.get("Technical") == 1


def test_risk_endpoint_requires_authentication():
    response = client.get("/api/analytics/risk")
    assert response.status_code == 401


def test_bottlenecks_endpoint_requires_authentication():
    response = client.get("/api/analytics/approval-bottlenecks")
    assert response.status_code == 401
