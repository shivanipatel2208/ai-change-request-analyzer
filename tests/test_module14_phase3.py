"""Verifies Module 14 Phase 3 (Analysis & Impact Intelligence - Complexity
& Effort confidence):

  * Analysis now carries `complexity_confidence` and `effort_confidence`,
    each a coarse Low/Medium/High rating - deliberately not a finer-grained
    numeric confidence, since Complexity/Effort are already plain-language
    estimates on purpose ("a range, not fake precision").
  * Both are distinct from `confidence_score` (the overall classification
    confidence) - a change request can have high overall confidence but a
    low confidence specifically in its effort estimate, and vice versa.
  * A response shaped like pre-Module-14 output (no confidence key on
    complexity/effort at all) must still validate and persist, falling
    back to "medium" - same rule every other Module 13/14 addition follows.

The real AI provider is never called here - same monkeypatched
_FakeProvider pattern as the other test_module14_*.py files.

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


def _unique_email() -> str:
    return f"m14p3-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module14 Phase3 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication to login",
        "description": "Send a one-time password to the customer's registered mobile number at login.",
        "priority": "high",
        "requested_by": "Shivani",
        "target_system": "Auth Service",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FakeProvider:
    def __init__(self, response_text):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)


def _minimal_response(**overrides) -> dict:
    base = {
        "summary": "Adds OTP-based authentication at login.",
        "classification": {"category": "Security", "confidence": 0.9, "reason": "New authentication factor."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "medium", "reasoning": "Touches auth flow."},
        "effort": {"backend": "2-3 days", "frontend": "1 day", "testing": "1 day", "total": "4-5 developer-days"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve_with_conditions", "reasoning": "Needs OTP expiry defined."},
    }
    base.update(overrides)
    return base


def _analyze(headers, cr_id, response_dict):
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return client.get(f"/api/change-requests/{cr_id}/analysis", headers=headers).json()


def test_complexity_and_effort_confidence_round_trip(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        complexity={"level": "high", "reasoning": "Touches auth and session handling.", "confidence": "low"},
        effort={
            "backend": "5-8 days",
            "frontend": "2-3 days",
            "testing": "2 days",
            "total": "9-13 developer-days",
            "confidence": "high",
        },
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    assert detail["complexity_confidence"] == "low"
    assert detail["effort_confidence"] == "high"
    # Distinct from the overall classification confidence.
    assert detail["confidence_score"] == 90.0


def test_pre_module_14_shaped_response_defaults_to_medium(monkeypatch):
    """No confidence key at all on complexity/effort (the exact shape
    Module 6 originally produced) must still validate and persist, falling
    back to "medium" rather than a validation failure."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        complexity={"level": "medium", "reasoning": "Legacy-shaped complexity, no confidence key."},
        effort={"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    assert detail["complexity_confidence"] == "medium"
    assert detail["effort_confidence"] == "medium"


def test_garbled_confidence_value_falls_back_to_medium(monkeypatch):
    """Same "no answer" placeholder handling every other enum field in this
    codebase relies on - a recognized placeholder string falls back safely
    rather than failing validation."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        complexity={"level": "medium", "reasoning": "Placeholder confidence value.", "confidence": "not specified"},
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    assert detail["complexity_confidence"] == "medium"
