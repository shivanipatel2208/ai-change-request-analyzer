"""Verifies Module 13 Phase 1 (AI Analysis 2.0 - epistemic tagging):
Requirement/AffectedComponent/Risk each carry a Known/Inferred/Unknown
`certainty` label, and Requirement/Risk also carry a per-finding
`confidence` (0-100) and `evidence` string.

Three things matter most here, since they're easy to get subtly wrong:
  * "unknown" must persist as a real Certainty.UNKNOWN value - not be
    swallowed by the "no answer provided" placeholder handling that every
    other enum field in this codebase uses (where the string "unknown"
    means "the AI didn't answer", not "the AI said unknown").
  * A canned response shaped like pre-Module-13 output (no certainty/
    confidence/evidence keys at all) must still validate and persist -
    existing behavior must not break.
  * Risk.evidence is populated from the AI's `explanation` field.

The real AI provider is never called here - same monkeypatched
_FakeProvider pattern as test_analysis_engine.py.

Run with (from backend/):  pytest ../tests
"""
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
    return f"ai2-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "AI2 Tester", "email": email, "password": password, "confirm_password": password},
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
    """The smallest valid AIAnalysisResult shape (mirrors the required
    fields only) - callers layer in requirements/affected_components/risks
    to exercise Module 13's new fields."""
    base = {
        "summary": "Adds OTP-based authentication at login.",
        "classification": {"category": "Security", "confidence": 0.9, "reason": "New authentication factor."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "medium", "reasoning": "Touches auth flow."},
        "effort": {
            "backend": "2-3 days",
            "frontend": "1 day",
            "testing": "1 day",
            "total": "4-5 developer-days",
        },
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve_with_conditions", "reasoning": "Needs OTP expiry defined."},
    }
    base.update(overrides)
    return base


def test_known_inferred_unknown_round_trip_via_api(monkeypatch):
    """The exact three-way example from the spec: a known fact, an
    inferred judgment call, and a genuinely unknown detail - each must
    persist and come back through the API as the distinct value it was,
    not collapsed into one default."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        requirements=[
            {
                "category": "functional",
                "description": "OTP is sent to the customer's registered mobile number.",
                "priority": "high",
                "certainty": "known",
                "confidence": 95,
                "evidence": "Explicitly stated in the change request description.",
            },
            {
                "category": "non_functional",
                "description": "Rate limiting is probably required on OTP requests.",
                "priority": "medium",
                "certainty": "inferred",
                "confidence": 60,
                "evidence": "Common practice for OTP flows, not stated in the request.",
            },
            {
                "category": "functional",
                "description": "OTP expiration window.",
                "priority": "high",
                "certainty": "unknown",
                "confidence": 20,
                "evidence": "Not mentioned anywhere in the change request.",
            },
        ],
    )
    import json as _json

    _patch_provider(monkeypatch, _FakeProvider(_json.dumps(response_json)))

    analyze_response = client.post(
        f"/api/change-requests/{created['id']}/analyze", headers=headers
    )
    assert analyze_response.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    reqs = {r["description"]: r for r in detail["requirements"]}

    known = reqs["OTP is sent to the customer's registered mobile number."]
    assert known["certainty"] == "known"
    assert known["confidence"] == 95
    assert "Explicitly stated" in known["evidence"]

    inferred = reqs["Rate limiting is probably required on OTP requests."]
    assert inferred["certainty"] == "inferred"
    assert inferred["confidence"] == 60

    unknown = reqs["OTP expiration window."]
    # This is the critical assertion: "unknown" must survive as a real
    # value, not be swallowed by the generic placeholder-detection used
    # for every other enum field in this codebase.
    assert unknown["certainty"] == "unknown"
    assert unknown["confidence"] == 20


def test_affected_component_certainty_round_trips(monkeypatch):
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
            }
        ],
    )
    import json as _json

    _patch_provider(monkeypatch, _FakeProvider(_json.dumps(response_json)))
    assert client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    component = detail["affected_components"][0]
    assert component["certainty"] == "inferred"
    assert component["confidence"] == 78


def test_risk_confidence_and_evidence_round_trip(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        risks=[
            {
                "category": "security",
                "description": "OTP brute-forcing without a retry limit.",
                "severity": "high",
                "probability": 0.6,
                "score": 75,
                "explanation": "No retry limit was mentioned in the request.",
                "mitigation": "Add a maximum attempt count with lockout.",
                "certainty": "known",
                "confidence": 85,
            }
        ],
    )
    import json as _json

    _patch_provider(monkeypatch, _FakeProvider(_json.dumps(response_json)))
    assert client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    risk = detail["risks"][0]
    assert risk["certainty"] == "known"
    assert risk["confidence"] == 85
    assert risk["evidence"] == "No retry limit was mentioned in the request."


def test_pre_module_13_shaped_response_still_validates(monkeypatch):
    """A response with no certainty/confidence/evidence keys at all (the
    exact shape Module 6 originally produced) must still validate and
    persist - Module 13's additions must not be a breaking change."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        requirements=[{"category": "functional", "description": "Legacy-shaped requirement.", "priority": "medium"}],
        risks=[
            {
                "category": "operational",
                "description": "Legacy-shaped risk.",
                "severity": "low",
                "probability": 0.2,
                "score": 20,
                "explanation": "",
                "mitigation": "None needed.",
            }
        ],
    )
    import json as _json

    _patch_provider(monkeypatch, _FakeProvider(_json.dumps(response_json)))
    analyze_response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze_response.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    # Defaults kick in rather than a validation failure.
    assert detail["requirements"][0]["certainty"] == "inferred"
    assert detail["requirements"][0]["confidence"] == 70.0
    assert detail["risks"][0]["certainty"] == "inferred"
    assert detail["risks"][0]["confidence"] == 70.0


def test_garbled_certainty_value_falls_back_to_inferred(monkeypatch):
    """A weaker model that writes something other than known/inferred/
    unknown shouldn't fail validation - it should fall back to the safe
    "inferred" default, same pattern as every other enum field here."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        requirements=[
            {
                "category": "functional",
                "description": "Garbled certainty value.",
                "priority": "medium",
                "certainty": "maybe kind of sure",
            }
        ],
    )
    import json as _json

    _patch_provider(monkeypatch, _FakeProvider(_json.dumps(response_json)))
    assert client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    assert detail["requirements"][0]["certainty"] == "inferred"
