"""Verifies Module 14 Phase 5 (Analysis & Impact Intelligence - Security):

  * Analysis now carries a full "security_findings" list - one structured
    finding per fixed lens (Authentication/Authorization/Data Protection/
    Secrets/API Security/Rate Limiting/Privacy/Audit Logging/Compliance -
    see app.models.enums.SecurityCategory), each with severity/evidence/
    recommendation/status.
  * The AI is expected to return exactly one entry per category; if it
    leaves one out (or all of them, for a pre-Module-14-Phase-5-shaped
    response), AIAnalysisResult.fill_missing_security_categories fills the
    gap with an honest "nothing flagged" placeholder (low severity,
    not_applicable status) - the result is always exactly 9 entries.
  * The AI can only ever set status to "open" or "not_applicable" -
    "acknowledged"/"resolved" are reserved for a human reviewer (Module 14
    Phase 6, not yet built) - an AI response that tries to claim either of
    those falls back to "open" rather than being trusted.
  * A placeholder/garbled category or severity value falls back to a safe
    default ("compliance" / "medium" respectively).
  * The old flat `security_analysis` blob is still persisted unchanged
    alongside the new structured findings - Phase 5 adds to it, it doesn't
    replace it at the database level (only the frontend switches which one
    it shows as primary).

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

ALL_CATEGORIES = [
    "authentication",
    "authorization",
    "data_protection",
    "secrets",
    "api_security",
    "rate_limiting",
    "privacy",
    "audit_logging",
    "compliance",
]


def _unique_email() -> str:
    return f"m14p5-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module14 Phase5 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add API key rotation for partner integrations",
        "description": "Let Alight.com admins rotate partner API keys without downtime.",
        "priority": "high",
        "requested_by": "Shivani",
        "target_system": "Partner API Gateway",
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
        "summary": "Adds a key-rotation flow for partner API keys.",
        "classification": {"category": "Security", "confidence": 0.9, "reason": "Touches credential lifecycle."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": ["Old keys must be invalidated immediately on rotation."], "summary": ""},
        "complexity": {"level": "medium", "reasoning": "Touches auth/credential flow."},
        "effort": {"backend": "3-4 days", "frontend": "1 day", "testing": "1 day", "total": "5-6 developer-days"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve_with_conditions", "reasoning": "Needs a key-invalidation audit."},
    }
    base.update(overrides)
    return base


def _analyze(headers, cr_id):
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return client.get(f"/api/change-requests/{cr_id}/analysis", headers=headers).json()


def test_security_findings_round_trip(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        security_findings=[
            {
                "category": category,
                "finding": f"{category.title()} finding.",
                "severity": "critical" if category == "secrets" else "medium",
                "evidence": f"{category} evidence.",
                "recommendation": f"{category} recommendation.",
                "status": "open",
            }
            for category in ALL_CATEGORIES
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    assert len(detail["security_findings"]) == 9
    by_category = {item["category"]: item for item in detail["security_findings"]}
    assert set(by_category.keys()) == set(ALL_CATEGORIES)
    assert by_category["secrets"]["severity"] == "critical"
    assert by_category["secrets"]["status"] == "open"
    assert by_category["compliance"]["evidence"] == "compliance evidence."
    # The old flat blob is still persisted alongside the new list.
    assert detail["security_analysis"] is not None
    assert "invalidated" in detail["security_analysis"]


def test_pre_module_14_phase5_shaped_response_fills_all_categories(monkeypatch):
    """No "security_findings" key at all (the exact shape every prior
    module produced) must still validate and persist, filling in all 9
    categories with an honest placeholder rather than a validation failure
    or a shorter-than-9 list."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response()
    assert "security_findings" not in response_json
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    assert len(detail["security_findings"]) == 9
    assert {item["category"] for item in detail["security_findings"]} == set(ALL_CATEGORIES)
    for item in detail["security_findings"]:
        assert item["status"] == "not_applicable"
        assert item["severity"] == "low"


def test_ai_cannot_claim_acknowledged_or_resolved_status(monkeypatch):
    """Status is only ever AI-settable as open/not_applicable - Module 14
    Phase 6 reserves acknowledged/resolved for a human reviewer. An AI
    response that tries to claim either of those falls back to "open"
    rather than being trusted at face value."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        security_findings=[
            {
                "category": "authentication",
                "finding": "MFA is not required for admin key rotation.",
                "severity": "high",
                "evidence": "The request doesn't mention any additional verification step.",
                "recommendation": "Require MFA before allowing key rotation.",
                "status": "resolved",
            }
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    by_category = {item["category"]: item for item in detail["security_findings"]}
    assert by_category["authentication"]["status"] == "open"
    assert len(detail["security_findings"]) == 9


def test_placeholder_category_and_severity_fall_back_to_safe_defaults(monkeypatch):
    """Same "no answer" placeholder handling every other enum field in this
    codebase relies on - a recognized placeholder string (never invented
    gibberish, which _normalize() does NOT rescue) falls back safely
    rather than failing validation."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        security_findings=[
            {
                "category": "not specified",
                "severity": "n/a",
                "finding": "Placeholder category and severity.",
                "evidence": "Evidence text.",
                "recommendation": "Recommendation text.",
                "status": "open",
            }
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    by_category = {item["category"]: item for item in detail["security_findings"]}
    # Falls back to "compliance" (category default) / "medium" (severity
    # default) - and since "compliance" is one of the 9 required
    # categories, the fill-missing-categories step does NOT add a second
    # placeholder entry for it.
    assert by_category["compliance"]["severity"] == "medium"
    assert by_category["compliance"]["finding"] == "Placeholder category and severity."
    assert len(detail["security_findings"]) == 9
