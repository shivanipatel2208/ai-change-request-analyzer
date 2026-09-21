"""Verifies Module 13 Phase 2 (AI Analysis 2.0 - analysis history +
version-to-version comparison):

  * GET /{id}/analyses - lightweight history list, newest first
  * GET /{id}/analysis/compare - a computed diff between two analyses,
    including the "significant change detected" flag/reasons and the
    best-effort added/removed requirement & affected-component lists

The real AI provider is never called - same monkeypatched _FakeProvider
pattern as test_analysis_engine.py and test_ai_analysis_v2.py.

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
    return f"delta-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Delta Tester", "email": email, "password": password, "confirm_password": password},
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


def _analyze(headers, cr_id, response_dict, monkeypatch):
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_dict)))
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return response.json()


# --- Two canned responses: a low-risk first pass, then a materially
# riskier second pass after the request "grew" - mirrors the spec's own
# example (Version 3 -> Version 4, "Financial transactions were added to
# scope", Risk: Medium -> High). --------------------------------------

FIRST_PASS = {
    "summary": "Adds OTP-based authentication at login.",
    "classification": {"category": "Security", "confidence": 0.8, "reason": "New authentication factor."},
    "requirements": [
        {"category": "functional", "description": "OTP is sent to the customer's registered mobile number."},
    ],
    "affected_components": [
        {
            "name": "Authentication Service",
            "type": "backend",
            "impact_level": "medium",
            "reason": "Adds OTP verification.",
            "confidence": 70,
        }
    ],
    "dependencies": [],
    "risks": [
        {
            "category": "security",
            "description": "OTP interception risk.",
            "severity": "medium",
            "probability": 0.3,
            "score": 40,
            "explanation": "Standard OTP risk.",
            "mitigation": "Use a short expiry window.",
        }
    ],
    "security_analysis": {"concerns": [], "summary": ""},
    "complexity": {"level": "medium", "reasoning": "Touches auth flow."},
    "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "approve_with_conditions", "reasoning": "Needs OTP expiry defined."},
}

# Second pass: scope grew to include a financial/payment step, materially
# raising risk - same change request, re-analyzed after an edit.
SECOND_PASS = {
    "summary": "Adds OTP-based authentication at login, now including a payment confirmation step.",
    "classification": {"category": "Security", "confidence": 0.8, "reason": "New authentication factor."},
    "requirements": [
        {"category": "functional", "description": "OTP is sent to the customer's registered mobile number."},
        {"category": "functional", "description": "OTP must also confirm high-value payment transactions."},
    ],
    "affected_components": [
        {
            "name": "Authentication Service",
            "type": "backend",
            "impact_level": "high",
            "reason": "Adds OTP verification.",
            "confidence": 75,
        },
        {
            "name": "Payment Gateway",
            "type": "third_party",
            "impact_level": "high",
            "reason": "OTP now confirms payments.",
            "confidence": 65,
        },
    ],
    "dependencies": [],
    "risks": [
        {
            "category": "security",
            "description": "OTP interception risk.",
            "severity": "high",
            "probability": 0.4,
            "score": 70,
            "explanation": "Now guards a financial transaction, not just login.",
            "mitigation": "Use a short expiry window and rate limiting.",
        },
        {
            "category": "compliance",
            "description": "Payment confirmation via OTP may need compliance review.",
            "severity": "high",
            "probability": 0.5,
            "score": 60,
            "explanation": "Financial transactions were added to scope.",
            "mitigation": "Confirm with compliance before implementation.",
        },
    ],
    "security_analysis": {"concerns": ["Financial transactions now in scope"], "summary": "Treat as high-risk."},
    "complexity": {"level": "high", "reasoning": "Now touches payments as well as auth."},
    "effort": {"backend": "4 days", "frontend": "2 days", "testing": "2 days", "total": "8 developer-days"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "requires_clarification", "reasoning": "Compliance review needed first."},
}


def test_list_analyses_returns_newest_first(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    second = _analyze(headers, created["id"], SECOND_PASS, monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/analyses", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert items[0]["id"] == second["id"]  # newest first


def test_compare_with_no_params_diffs_two_most_recent(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    _analyze(headers, created["id"], SECOND_PASS, monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/analysis/compare", headers=headers)
    assert response.status_code == 200
    body = response.json()

    fields = {f["field"]: f for f in body["fields"]}
    assert fields["risk_bucket"]["old_value"] == "Medium"
    assert fields["risk_bucket"]["new_value"] == "High"
    assert fields["risk_bucket"]["status"] == "changed"
    assert fields["complexity"]["old_value"] == "Medium"
    assert fields["complexity"]["new_value"] == "High"
    assert fields["recommendation"]["old_value"] == "approve_with_conditions"
    assert fields["recommendation"]["new_value"] == "requires_clarification"
    assert fields["affected_component_count"]["old_value"] == "1"
    assert fields["affected_component_count"]["new_value"] == "2"
    assert fields["requirement_count"]["old_value"] == "1"
    assert fields["requirement_count"]["new_value"] == "2"

    assert body["is_significant_change"] is True
    assert any("Risk moved from medium to high" in r for r in body["significant_change_reasons"])

    assert "OTP must also confirm high-value payment transactions." in body["requirements_added"]
    assert body["requirements_removed"] == []
    assert "Payment Gateway" in body["affected_components_added"]
    assert body["affected_components_removed"] == []


def test_compare_explicit_ids_regardless_of_order(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    first = _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    second = _analyze(headers, created["id"], SECOND_PASS, monkeypatch)

    # Pass them backwards - the endpoint must still compare chronologically
    # (old -> new), not literally "from" -> "to" as given.
    response = client.get(
        f"/api/change-requests/{created['id']}/analysis/compare",
        params={"from": second["id"], "to": first["id"]},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_analysis_id"] == first["id"]
    assert body["to_analysis_id"] == second["id"]
    fields = {f["field"]: f for f in body["fields"]}
    assert fields["risk_bucket"]["old_value"] == "Medium"
    assert fields["risk_bucket"]["new_value"] == "High"


def test_compare_returns_409_with_only_one_analysis(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/analysis/compare", headers=headers)
    assert response.status_code == 409


def test_compare_returns_404_for_analysis_from_a_different_change_request(monkeypatch):
    headers = _auth()
    created_a = _create_change_request(headers, title="Change request Alpha")
    created_b = _create_change_request(headers, title="Change request Beta")
    _analyze(headers, created_a["id"], FIRST_PASS, monkeypatch)
    _analyze(headers, created_a["id"], SECOND_PASS, monkeypatch)
    other = _analyze(headers, created_b["id"], FIRST_PASS, monkeypatch)

    response = client.get(
        f"/api/change-requests/{created_a['id']}/analysis/compare",
        params={"to": other["id"]},
        headers=headers,
    )
    assert response.status_code == 404


def test_compare_same_id_twice_returns_400(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    second = _analyze(headers, created["id"], SECOND_PASS, monkeypatch)

    response = client.get(
        f"/api/change-requests/{created['id']}/analysis/compare",
        params={"from": second["id"], "to": second["id"]},
        headers=headers,
    )
    assert response.status_code == 400


def test_no_significant_change_when_nothing_material_moved(monkeypatch):
    """Re-analyzing with an identical-shaped result (same risk bucket,
    complexity, recommendation, and recommended approvals) should not be
    flagged as a significant change, even though it's technically a new
    analysis row."""
    headers = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/analysis/compare", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["is_significant_change"] is False
    assert body["significant_change_reasons"] == []
