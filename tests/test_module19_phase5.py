"""Verifies Module 19 Phase 5 (Engineering Change Analytics): the new
GET /api/analytics/ai endpoint - spec section 7, deliberately called "AI
recommendation statistics" (never "AI accuracy" - see
app/services/analytics.py::AIAnalyticsMetrics for why) - against real
database rows this test file creates itself.

Following this project's established HTTP-only testing convention, every
check here goes through the real /analyze endpoint (monkeypatched
provider, controlling confidence/risk_score/recommendation via the AI
response's own fields) - never a direct database write. The AI-failure
count reuses Module 19 Phase 1's own AI_ANALYSIS_FAILED history hook,
verified end-to-end here through this new endpoint rather than only
through the /history endpoint Phase 1's own test file already covers.

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


def _analysis_response(*, confidence: float, risk_score: float, decision: str) -> dict:
    risks = []
    if risk_score:
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
        "summary": "A test change used only to exercise Module 19 Phase 5's AI analytics endpoint.",
        "classification": {"category": "Configuration", "confidence": confidence, "reason": "Test fixture."},
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
        "recommendation": {"decision": decision, "reasoning": "Test fixture."},
    }


class _FixedProvider:
    def __init__(self, response_text=None, raise_exc=None):
        self._text = response_text
        self._raise = raise_exc

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        if self._raise is not None:
            raise self._raise
        return self._text


def _patch_provider(monkeypatch, *, confidence=0.8, risk_score=10.0, decision="approve") -> None:
    response_text = json.dumps(_analysis_response(confidence=confidence, risk_score=risk_score, decision=decision))
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(response_text))


def _patch_failure(monkeypatch) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider("this is not json at all"))


def _unique_email() -> str:
    return f"m19p5-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module19 Phase5 Tester") -> tuple[dict, int]:
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
        "title": "Module 19 Phase 5 fixture change request",
        "description": "A change request used only to exercise the AI analytics endpoint.",
        "business_objective": "N/A - test fixture.",
        "priority": "medium",
        "requested_by": "Test Fixture",
        "target_system": "Test System",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _get_ai(headers: dict, **params) -> dict:
    response = client.get("/api/analytics/ai", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_total_analyses_and_average_confidence(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, confidence=0.8)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201

    data = _get_ai(headers, owner_id=owner_id)
    assert data["total_analyses"] == 1
    assert abs(data["average_confidence"] - 80.0) < 0.01
    assert data["re_analysis_rate"] == 0.0


def test_re_analysis_rate_none_with_nothing_analyzed():
    headers, owner_id = _auth()
    _create_change_request(headers)

    data = _get_ai(headers, owner_id=owner_id)
    assert data["total_analyses"] == 0
    assert data["re_analysis_rate"] is None
    assert data["average_confidence"] is None


def test_re_analysis_rate_combines_analyzed_and_reanalyzed_crs(monkeypatch):
    headers, owner_id = _auth()
    once_analyzed = _create_change_request(headers, title="Analyzed once")
    twice_analyzed = _create_change_request(headers, title="Analyzed twice")

    _patch_provider(monkeypatch)
    assert client.post(f"/api/change-requests/{once_analyzed['id']}/analyze", headers=headers).status_code == 201
    assert client.post(f"/api/change-requests/{twice_analyzed['id']}/analyze", headers=headers).status_code == 201
    assert client.post(f"/api/change-requests/{twice_analyzed['id']}/analyze", headers=headers).status_code == 201

    data = _get_ai(headers, owner_id=owner_id)
    assert data["total_analyses"] == 3
    # 2 analyzed CRs total, 1 of them (twice_analyzed) re-analyzed - 0.5.
    assert abs(data["re_analysis_rate"] - 0.5) < 0.001


def test_risk_changes_after_edits_counts_bucket_transitions(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)

    _patch_provider(monkeypatch, risk_score=10.0)  # low
    assert client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).status_code == 201
    _patch_provider(monkeypatch, risk_score=90.0)  # critical
    assert client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).status_code == 201

    data = _get_ai(headers, owner_id=owner_id)
    assert data["risk_changes_after_edits"] == 1


def test_ai_recommended_approvals_counts_approve_decisions_only(monkeypatch):
    headers, owner_id = _auth()
    approved_cr = _create_change_request(headers, title="AI recommends approve")
    clarification_cr = _create_change_request(headers, title="AI requires clarification")

    _patch_provider(monkeypatch, decision="approve")
    assert client.post(f"/api/change-requests/{approved_cr['id']}/analyze", headers=headers).status_code == 201
    _patch_provider(monkeypatch, decision="requires_clarification")
    assert client.post(f"/api/change-requests/{clarification_cr['id']}/analyze", headers=headers).status_code == 201

    data = _get_ai(headers, owner_id=owner_id)
    assert data["ai_recommended_approvals"] == 1


def test_ai_analysis_failures_counted(monkeypatch):
    headers, owner_id = _auth()
    created = _create_change_request(headers)
    _patch_failure(monkeypatch)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 422

    data = _get_ai(headers, owner_id=owner_id)
    assert data["ai_analysis_failures"] == 1
    assert data["total_analyses"] == 0


def test_ai_endpoint_requires_authentication():
    response = client.get("/api/analytics/ai")
    assert response.status_code == 401
