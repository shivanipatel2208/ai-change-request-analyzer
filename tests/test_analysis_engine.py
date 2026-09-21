"""Verifies Module 6 (AI Analysis Engine): POST /analyze and GET /analysis,
prompt->JSON->Pydantic validation, persistence across every child table,
and graceful handling of a not-configured provider, invalid JSON, a
schema-validation failure, and a timeout.

The real Anthropic API is never called here - `get_ai_provider()` is
monkeypatched with a fake provider that returns canned text, so these tests
run offline and don't cost API credits. Three distinct canned change
requests (a simple config tweak, a security-sensitive change, and one that
comes back needing clarification) exercise different parts of the schema,
satisfying the "test with at least 3 different change requests" requirement
without spending real API calls on every test run - the user separately
verifies the same endpoint live against the real provider.

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
from app.database.session import SessionLocal
from app.main import app
from app.models import Analysis

client = TestClient(app)


def _unique_email() -> str:
    return f"ai-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "AI Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add loyalty points to checkout",
        "description": "Award loyalty points automatically when a customer completes checkout on the POS.",
        "business_objective": "Increase repeat visits by rewarding customers automatically.",
        "priority": "medium",
        "requested_by": "Morgan Lee",
        "target_system": "POS Backend",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FakeProvider:
    """Stands in for AnthropicProvider in tests - returns canned text (or
    raises a canned exception) instead of calling the real API."""

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


# --- Three distinct canned AI responses --------------------------------
# Change request #1: a small, low-risk configuration change.
CONFIG_CHANGE_RESPONSE = {
    "summary": "Adds a configurable loyalty-points multiplier to the POS checkout flow.",
    "classification": {"category": "Configuration", "confidence": 0.86, "reason": "A tunable value, no new flow."},
    "requirements": [
        {"category": "business_objective", "description": "Increase repeat visits.", "priority": "medium"},
        {"category": "functional", "description": "Award points on checkout completion.", "priority": "high"},
    ],
    "affected_components": [
        {
            "name": "Checkout Service",
            "type": "backend",
            "impact_level": "low",
            "reason": "Reads a new config value at checkout time.",
            "confidence": 70,
        }
    ],
    "dependencies": [],
    "risks": [
        {
            "category": "operational",
            "description": "Misconfigured multiplier could award incorrect points.",
            "severity": "low",
            "probability": 0.2,
            "score": 15,
            "explanation": "Low blast radius, easy to correct.",
            "mitigation": "Validate the multiplier value before saving it.",
        }
    ],
    "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
    "complexity": {"level": "low", "reasoning": "Single config value, existing code path."},
    "effort": {"backend": "1 day", "frontend": "Insufficient information.", "testing": "0.5 day", "total": "1-2 developer-days"},
    "missing_information": [],
    "test_cases": [
        {
            "id": "TC-001",
            "title": "Checkout awards multiplied points",
            "type": "integration",
            "priority": "high",
            "description": "Complete a checkout and verify points awarded match the configured multiplier.",
            "expected_result": "Points awarded equal base points * multiplier.",
        }
    ],
    "implementation_plan": [
        {
            "task": "Add multiplier config field",
            "description": "Add a validated numeric config field for the multiplier.",
            "component": "Checkout Service",
            "priority": "high",
            "estimated_effort": "4h",
            "dependencies": None,
        }
    ],
    "recommendation": {"decision": "approve", "reasoning": "Small, well-scoped, low risk."},
}

# Change request #2: a security-sensitive change, high risk.
SECURITY_CHANGE_RESPONSE = {
    "summary": "Adds an admin API endpoint to refund a customer's order without manager approval.",
    "classification": {"category": "Security", "confidence": 0.74, "reason": "Bypasses an existing approval control."},
    "requirements": [
        {"category": "constraint", "description": "Must not remove the existing audit log entry.", "priority": "critical"},
    ],
    "affected_components": [
        {
            "name": "Admin API",
            "type": "api",
            "impact_level": "high",
            "reason": "New endpoint with elevated privileges.",
            "confidence": 65,
        },
        {
            "name": "Orders Database",
            "type": "database",
            "impact_level": "medium",
            "reason": "Refund writes bypass the approval-gated path.",
            "confidence": 60,
        },
    ],
    "dependencies": [
        {"name": "Auth Service", "type": "service", "impact_level": "medium", "reason": "Needs a new permission scope."}
    ],
    "risks": [
        {
            "category": "security",
            "description": "Removing manager approval increases fraud/misuse risk.",
            "severity": "critical",
            "probability": 0.5,
            "score": 88,
            "explanation": "No compensating control described.",
            "mitigation": "Require a secondary approval or hard refund cap instead of removing the control.",
        },
        {
            "category": "compliance",
            "description": "May violate change-control policy for financial transactions.",
            "severity": "high",
            "probability": 0.4,
            "score": 60,
            "explanation": "Insufficient information about applicable policy.",
            "mitigation": "Confirm with compliance before implementation.",
        },
    ],
    "security_analysis": {
        "concerns": ["Privilege escalation risk", "Missing audit trail requirement is unclear"],
        "summary": "This request removes an existing control; treat as high-risk until reviewed.",
    },
    "complexity": {"level": "high", "reasoning": "Touches auth, API, and financial data."},
    "effort": {"backend": "3-5 days", "frontend": "1 day", "testing": "2-3 days", "total": "6-9 developer-days"},
    "missing_information": [
        {
            "question": "Why is manager approval being removed rather than streamlined?",
            "priority": "critical",
            "reason": "Directly affects the security assessment.",
        },
        {
            "question": "Is there a refund amount cap in mind?",
            "priority": "important",
            "reason": "Affects mitigation design.",
        },
    ],
    "test_cases": [
        {
            "id": "TC-001",
            "title": "Refund without approval is logged",
            "type": "security",
            "priority": "critical",
            "description": "Issue a refund via the new endpoint.",
            "expected_result": "An audit log entry is created with the acting admin's identity.",
        }
    ],
    "implementation_plan": [
        {
            "task": "Add refund endpoint",
            "description": "Add the new admin refund endpoint behind a new permission scope.",
            "component": "Admin API",
            "priority": "critical",
            "estimated_effort": "2d",
            "dependencies": "Auth Service permission scope",
        }
    ],
    "recommendation": {
        "decision": "requires_clarification",
        "reasoning": "Removing an approval control needs a documented reason and compensating mitigation first.",
    },
}

# Change request #3: too vague to say much - tests the "insufficient
# information" / low-confidence path.
VAGUE_CHANGE_RESPONSE = {
    "summary": "Requests an unspecified improvement to reporting; too vague to scope further.",
    "classification": {"category": "Performance", "confidence": 0.3, "reason": "No concrete detail provided."},
    "requirements": [
        {"category": "assumption", "description": "Assuming this refers to the existing Reporting Dashboard.", "priority": "low"}
    ],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_analysis": {"concerns": [], "summary": "Insufficient information."},
    "complexity": {"level": "medium", "reasoning": "Insufficient information."},
    "effort": {
        "backend": "Insufficient information.",
        "frontend": "Insufficient information.",
        "testing": "Insufficient information.",
        "total": "Insufficient information.",
    },
    "missing_information": [
        {
            "question": "Which report(s) and what specific improvement is requested?",
            "priority": "critical",
            "reason": "Cannot scope work without this.",
        },
        {
            "question": "Is there a performance target (e.g. load time)?",
            "priority": "nice_to_have",
            "reason": "Would help size the effort.",
        },
    ],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {
        "decision": "requires_clarification",
        "reasoning": "Not enough detail to assess or plan.",
    },
}


def test_analyze_requires_authentication():
    response = client.post("/api/change-requests/1/analyze")
    assert response.status_code == 401


def test_get_analysis_requires_authentication():
    response = client.get("/api/change-requests/1/analysis")
    assert response.status_code == 401


def test_analyze_returns_404_for_unknown_change_request(monkeypatch):
    headers = _auth()
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(CONFIG_CHANGE_RESPONSE)))
    response = client.post("/api/change-requests/999999999/analyze", headers=headers)
    assert response.status_code == 404


def test_get_analysis_before_any_analysis_returns_404():
    headers = _auth()
    created = _create_change_request(headers)
    response = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert response.status_code == 404


def test_analyze_returns_503_when_provider_not_configured(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider(configured=False))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 503


def test_analyze_returns_422_on_invalid_json(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider("this is not json at all"))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 422


def test_analyze_strips_markdown_fences_before_parsing(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    fenced = "```json\n" + json.dumps(CONFIG_CHANGE_RESPONSE) + "\n```"
    _patch_provider(monkeypatch, _FakeProvider(fenced))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201


def test_analyze_returns_422_on_schema_validation_failure(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    broken = dict(CONFIG_CHANGE_RESPONSE)
    broken["classification"] = {"category": "Configuration", "confidence": 2.5, "reason": "out of range"}
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(broken)))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 422


def test_analyze_returns_504_on_timeout(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    class _Timeout(Exception):
        pass

    _Timeout.__name__ = "APITimeoutError"
    _patch_provider(monkeypatch, _FakeProvider(raise_exc=_Timeout("took too long")))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 504


def test_analyze_config_change_persists_low_risk_result(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers, title="Loyalty multiplier config change")
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(CONFIG_CHANGE_RESPONSE)))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    assert body["category"] == "Configuration"
    assert body["complexity"] == "low"
    assert body["recommendation"] == "approve"
    assert 0 < body["risk_score"] <= 20
    assert len(body["requirements"]) == 2
    assert len(body["affected_components"]) == 1
    assert len(body["risks"]) == 1
    assert len(body["test_cases"]) == 1
    assert len(body["implementation_tasks"]) == 1
    assert body["clarification_questions"] == []
    assert body["effort_estimate"].startswith("Backend: 1 day")


def test_analyze_security_change_persists_high_risk_and_clarification(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers, title="Refund endpoint without manager approval")
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(SECURITY_CHANGE_RESPONSE)))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    assert body["category"] == "Security"
    assert body["complexity"] == "high"
    assert body["recommendation"] == "requires_clarification"
    assert body["risk_score"] == 88  # max() of the two risk scores (88, 60)
    assert len(body["risks"]) == 2
    assert len(body["dependencies"]) == 1
    assert len(body["affected_components"]) == 2

    priorities = {q["priority"] for q in body["clarification_questions"]}
    assert priorities == {"critical", "high"}  # critical->critical, important->high

    security = json.loads(body["security_analysis"])
    assert len(security["concerns"]) == 2


def test_analyze_vague_change_low_confidence_and_missing_info(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers, title="Improve reporting somehow")
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(VAGUE_CHANGE_RESPONSE)))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    assert body["confidence_score"] == 30  # 0.3 * 100
    assert body["risk_score"] == 5.0  # no risks returned -> low default
    assert len(body["clarification_questions"]) == 2
    priorities = {q["priority"] for q in body["clarification_questions"]}
    assert priorities == {"critical", "low"}  # critical->critical, nice_to_have->low


def test_reanalyze_creates_new_row_and_get_analysis_returns_latest(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers, title="Re-analyzed request")

    _patch_provider(monkeypatch, _FakeProvider(json.dumps(CONFIG_CHANGE_RESPONSE)))
    first = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert first.status_code == 201

    _patch_provider(monkeypatch, _FakeProvider(json.dumps(SECURITY_CHANGE_RESPONSE)))
    second = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]

    db = SessionLocal()
    try:
        count = db.query(Analysis).filter(Analysis.change_request_id == created["id"]).count()
        assert count == 2
    finally:
        db.close()

    latest = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["id"] == second.json()["id"]
    assert latest.json()["category"] == "Security"


def test_change_request_detail_reflects_new_analysis(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers, title="Detail view picks up new analysis")
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(SECURITY_CHANGE_RESPONSE)))

    analyze_response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze_response.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["effective_status"] == "requires_clarification"
    assert body["latest_analysis"]["category"] == "Security"
    assert body["latest_analysis"]["recommendation"] == "requires_clarification"
    assert len(body["latest_analysis"]["clarification_questions"]) == 2
