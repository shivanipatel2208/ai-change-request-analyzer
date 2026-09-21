"""Verifies Module 14 Phase 4 (Analysis & Impact Intelligence - Impact
Analysis):

  * Analysis now carries a full "impact_assessments" list - one structured
    finding per fixed lens (Business/Technical/Customer/Operational/
    Security/Data/Performance - see app.models.enums.ImpactCategory), each
    with its own impact_level/description/certainty/confidence.
  * The AI is expected to return exactly one entry per category, but if it
    leaves one out (or all of them, for a pre-Module-14-shaped response),
    AIAnalysisResult.fill_missing_impact_categories fills the gap with an
    honest "no assessment given" placeholder (medium impact, unknown
    certainty, 0 confidence) rather than silently rendering fewer than 7
    cards - the result is always exactly 7 entries, one per category.
  * A placeholder/garbled category or impact_level value falls back to a
    safe default ("technical" / "medium" respectively) via the same
    _normalize() rules every other enum field in this codebase relies on.

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

ALL_CATEGORIES = ["business", "technical", "customer", "operational", "security", "data", "performance"]


def _unique_email() -> str:
    return f"m14p4-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module14 Phase4 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add multi-factor authentication to checkout",
        "description": "Require a second verification step before a customer can complete checkout on Alight.com.",
        "priority": "high",
        "requested_by": "Shivani",
        "target_system": "Checkout Service",
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
        "summary": "Adds an MFA step to checkout.",
        "classification": {"category": "Security", "confidence": 0.9, "reason": "New verification step."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "medium", "reasoning": "Touches checkout flow."},
        "effort": {"backend": "3-4 days", "frontend": "2 days", "testing": "1 day", "total": "6-7 developer-days"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve_with_conditions", "reasoning": "Needs UX review of the MFA prompt."},
    }
    base.update(overrides)
    return base


def _analyze(headers, cr_id):
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return client.get(f"/api/change-requests/{cr_id}/analysis", headers=headers).json()


def test_impact_assessments_round_trip(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        impact_assessments=[
            {
                "category": category,
                "impact_level": "high" if category == "security" else "medium",
                "description": f"{category.title()} impact description.",
                "certainty": "known",
                "confidence": 85.0,
            }
            for category in ALL_CATEGORIES
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    assert len(detail["impact_assessments"]) == 7
    by_category = {item["category"]: item for item in detail["impact_assessments"]}
    assert set(by_category.keys()) == set(ALL_CATEGORIES)
    assert by_category["security"]["impact_level"] == "high"
    assert by_category["security"]["certainty"] == "known"
    assert by_category["security"]["confidence"] == 85.0
    assert by_category["business"]["description"] == "Business impact description."


def test_pre_module_14_shaped_response_fills_all_categories(monkeypatch):
    """No "impact_assessments" key at all (the exact shape every prior
    module produced) must still validate and persist, filling in all 7
    categories with an honest placeholder rather than a validation
    failure or a shorter-than-7 list."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response()
    assert "impact_assessments" not in response_json
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    assert len(detail["impact_assessments"]) == 7
    assert {item["category"] for item in detail["impact_assessments"]} == set(ALL_CATEGORIES)
    for item in detail["impact_assessments"]:
        assert item["certainty"] == "unknown"
        assert item["confidence"] == 0.0
        assert item["description"] == "Insufficient information."


def test_partial_impact_assessments_fills_only_missing_categories(monkeypatch):
    """Only 2 of the 7 categories provided - the other 5 get filled in with
    the placeholder, but the 2 real ones are kept exactly as given."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        impact_assessments=[
            {
                "category": "customer",
                "impact_level": "high",
                "description": "Customers will see a new MFA prompt at checkout.",
                "certainty": "known",
                "confidence": 90.0,
            },
            {
                "category": "data",
                "impact_level": "low",
                "description": "No new data is stored beyond the MFA code itself.",
                "certainty": "inferred",
                "confidence": 60.0,
            },
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    assert len(detail["impact_assessments"]) == 7
    by_category = {item["category"]: item for item in detail["impact_assessments"]}
    assert by_category["customer"]["description"] == "Customers will see a new MFA prompt at checkout."
    assert by_category["customer"]["confidence"] == 90.0
    assert by_category["data"]["impact_level"] == "low"
    for category in ["business", "technical", "operational", "security", "performance"]:
        assert by_category[category]["description"] == "Insufficient information."
        assert by_category[category]["certainty"] == "unknown"


def test_placeholder_category_and_impact_level_fall_back_to_safe_defaults(monkeypatch):
    """Same "no answer" placeholder handling every other enum field in this
    codebase relies on - a recognized placeholder string (never invented
    gibberish, which _normalize() does NOT rescue) falls back safely
    rather than failing validation."""
    headers = _auth()
    created = _create_change_request(headers)

    response_json = _minimal_response(
        impact_assessments=[
            {
                "category": "not specified",
                "impact_level": "n/a",
                "description": "Placeholder category and impact level.",
                "certainty": "known",
                "confidence": 55.0,
            }
        ]
    )
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_json)))
    detail = _analyze(headers, created["id"])

    by_category = {item["category"]: item for item in detail["impact_assessments"]}
    # Falls back to "technical" (category default) / "medium" (impact_level
    # default) - and since "technical" is one of the 7 required categories,
    # the fill-missing-categories step does NOT add a second placeholder
    # entry for it.
    assert by_category["technical"]["impact_level"] == "medium"
    assert by_category["technical"]["description"] == "Placeholder category and impact level."
    assert len(detail["impact_assessments"]) == 7
