"""Verifies Module 14 Phase 2 (Analysis & Impact Intelligence -
Affected Components + Dependencies filled out):

  * AffectedComponent now carries an `evidence` string, the same role it
    already plays on Requirement/Risk (Module 13 Phase 1).
  * Dependency now carries `relationship_type` (direct/indirect/potential -
    how directly this change actually relies on it) and `risk_severity` (a
    severity rating of relying on it), both distinct from the pre-existing
    `impact_level`.
  * A response shaped like pre-Module-14 output (no evidence/relationship/
    risk keys at all) must still validate and persist - these additions
    must not be a breaking change, same rule Module 13 Phase 1 followed.
  * The "do not invent dependencies" placeholder-name filtering
    (AIAnalysisResult.drop_placeholder_list_items) still works unchanged
    alongside the new fields.

The real AI provider is never called here - same monkeypatched
_FakeProvider pattern as test_ai_analysis_v2.py.

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
    return f"m14p2-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module14 Phase2 Tester", "email": email, "password": password, "confirm_password": password},
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


def test_affected_component_evidence_round_trips(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        affected_components=[
            {
                "name": "Authentication Service",
                "type": "backend",
                "impact_level": "high",
                "reason": "Central place OTP verification would be added.",
                "confidence": 78,
                "certainty": "inferred",
                "evidence": "The description names login as the affected flow.",
            }
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    component = detail["affected_components"][0]
    assert component["evidence"] == "The description names login as the affected flow."


def test_dependency_relationship_and_risk_round_trip(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        dependencies=[
            {
                "name": "SMS Gateway",
                "type": "external",
                "impact_level": "high",
                "reason": "OTP codes must be delivered via SMS.",
                "relationship": "direct",
                "risk": "high",
            },
            {
                "name": "User Session Store",
                "type": "internal",
                "impact_level": "medium",
                "reason": "Session state may need a new OTP-pending flag.",
                "relationship": "indirect",
                "risk": "low",
            },
            {
                "name": "Fraud Detection Service",
                "type": "service",
                "impact_level": "low",
                "reason": "May eventually want to flag suspicious OTP requests.",
                "relationship": "potential",
                "risk": "medium",
            },
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    deps = {d["dependency_name"]: d for d in detail["dependencies"]}
    assert deps["SMS Gateway"]["relationship_type"] == "direct"
    assert deps["SMS Gateway"]["risk_severity"] == "high"
    assert deps["User Session Store"]["relationship_type"] == "indirect"
    assert deps["User Session Store"]["risk_severity"] == "low"
    assert deps["Fraud Detection Service"]["relationship_type"] == "potential"
    assert deps["Fraud Detection Service"]["risk_severity"] == "medium"


def test_pre_module_14_shaped_dependency_and_component_still_validate(monkeypatch):
    """No evidence/relationship/risk keys at all (the exact shape Module 6/
    13 produced before this module) must still validate and persist, with
    safe defaults rather than a validation failure."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        affected_components=[
            {
                "name": "Legacy-shaped Component",
                "type": "backend",
                "impact_level": "medium",
                "reason": "No evidence field at all.",
                "confidence": 50,
            }
        ],
        dependencies=[
            {
                "name": "Legacy-shaped Dependency",
                "type": "service",
                "impact_level": "low",
                "reason": "No relationship/risk fields at all.",
            }
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    component = detail["affected_components"][0]
    assert component["evidence"] is None

    dependency = detail["dependencies"][0]
    assert dependency["relationship_type"] == "direct"
    assert dependency["risk_severity"] == "low"


def test_placeholder_relationship_and_risk_fall_back_to_safe_defaults(monkeypatch):
    """A weaker model's "no answer" placeholder text (e.g. "not specified",
    "n/a") should fall back to a safe default rather than fail validation -
    same _normalize() "no answer" handling every other enum field in this
    file already relies on (see ai_analysis.py's module docstring). Note
    this is specifically about a *placeholder* string, not arbitrary
    gibberish: _normalize() only rescues values in its known "no answer"
    set - a genuinely garbled value that ISN'T one of those (e.g. "sort of
    maybe") still fails validation today, and that's true for every other
    enum field here (type, impact_level, category, ...), not something
    Module 14 introduced or is expected to change."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        dependencies=[
            {
                "name": "Placeholder-value Dependency",
                "type": "service",
                "impact_level": "medium",
                "reason": "Placeholder relationship/risk values.",
                "relationship": "not specified",
                "risk": "n/a",
            }
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    dependency = detail["dependencies"][0]
    assert dependency["relationship_type"] == "direct"
    assert dependency["risk_severity"] == "low"


def test_placeholder_named_dependency_still_dropped(monkeypatch):
    """Module 6's existing "don't persist a fake dependency literally named
    'None specified'" filtering (drop_placeholder_list_items) must keep
    working unchanged alongside the new relationship/risk fields - Module
    14 doesn't touch that logic, this just confirms it wasn't disturbed."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        dependencies=[
            {
                "name": "None specified",
                "type": "internal",
                "impact_level": "low",
                "reason": "Placeholder row a weaker model sometimes emits.",
                "relationship": "direct",
                "risk": "low",
            },
            {
                "name": "Real Payment Gateway",
                "type": "external",
                "impact_level": "high",
                "reason": "Payments are processed through it.",
                "relationship": "direct",
                "risk": "high",
            },
        ],
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"], response_json)

    names = [d["dependency_name"] for d in detail["dependencies"]]
    assert "None specified" not in names
    assert "Real Payment Gateway" in names
