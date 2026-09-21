"""Verifies Module 17 Phase 3 (Test Cases & Implementation Plan 2.0 -
richer implementation-plan generation):

  * ImplementationTaskItem (the AI's own output shape) accepts
    owner_suggestion and ImplementationTask persists it correctly
    end-to-end through a real POST /analyze call, using Module 12's own
    AssignmentRole vocabulary (see Module 17 Phase 1's own docstrings for
    why this reuses that enum rather than inventing a second one).
  * An owner_suggestion value that isn't one of Module 12's real
    AssignmentRole options (a placeholder like "N/A", or a value the AI
    simply made up) normalizes to null rather than a fabricated role -
    the same "never invent, say so instead" rule every other AI-facing
    normalizer in app/schemas/ai_analysis.py already follows.
  * A task naming no owner_suggestion at all (the exact shape every
    fixture in test_analysis_engine.py already uses) still persists
    cleanly - Phase 3 never made this field required.
  * The full owner-suggestion menu (Module 12's 8 AssignmentRole values)
    is actually present in the system prompt sent to the AI - a silent
    prompt/enum drift bug elsewhere in this module would otherwise never
    be caught by any test.

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) - no real network call, matching this app's established
testing pattern.

Run with (from backend/):  python -m pytest ../tests
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
from app.models.enums import AssignmentRole
from app.schemas.ai_analysis import ImplementationTaskItem

client = TestClient(app)


def _unique_email() -> str:
    return f"m17p3-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase3 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _base_analysis_json(implementation_plan):
    return {
        "summary": "Adds OTP-based verification to checkout.",
        "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_findings": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "impact_assessments": [],
        "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
        "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
        "missing_information": [],
        "test_cases": [
            {
                "id": "TC-001",
                "title": "OTP code expires after 5 minutes",
                "type": "security",
                "priority": "high",
                "description": "Verify an OTP code can't be used once it has expired.",
                "expected_result": "The expired code is rejected with a clear error.",
            }
        ],
        "implementation_plan": implementation_plan,
        "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
    }


class _FixedProvider:
    def __init__(self, analysis_json):
        self._analysis_json = analysis_json

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(self._analysis_json)


def test_owner_suggestion_persists_end_to_end(monkeypatch):
    analysis_json = _base_analysis_json(
        [
            {
                "task": "Add rate limiting to the OTP verification endpoint",
                "description": "Cap OTP verification attempts to stop brute-forcing.",
                "component": "Backend",
                "priority": "high",
                "estimated_effort": "1 day",
                "dependencies": None,
                "owner_suggestion": "security_reviewer",
            }
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    task = response.json()["implementation_tasks"][0]

    assert task["owner_suggestion"] == "security_reviewer"


def test_invalid_owner_suggestion_normalizes_to_none_end_to_end(monkeypatch):
    analysis_json = _base_analysis_json(
        [
            {
                "task": "Write release notes",
                "description": "Summarize the change for the changelog.",
                "component": "Docs",
                "priority": "low",
                "estimated_effort": "1 hour",
                "dependencies": None,
                "owner_suggestion": "N/A",
            }
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    task = response.json()["implementation_tasks"][0]

    assert task["owner_suggestion"] is None


def test_task_with_no_owner_suggestion_still_persists_cleanly(monkeypatch):
    # The exact shape test_analysis_engine.py's own fixtures already use -
    # Phase 3 must never make owner_suggestion required.
    analysis_json = _base_analysis_json(
        [
            {
                "task": "Add OTP generation endpoint",
                "description": "Backend endpoint that generates and stores a one-time password.",
                "component": "Backend",
                "priority": "high",
                "estimated_effort": "2 days",
                "dependencies": None,
            }
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    task = response.json()["implementation_tasks"][0]

    assert task["owner_suggestion"] is None


def test_implementation_task_item_rejects_a_fabricated_role_in_favor_of_none():
    item = ImplementationTaskItem(
        task="t",
        description="d",
        owner_suggestion="chief wizard",
    )
    assert item.owner_suggestion is None

    item2 = ImplementationTaskItem(
        task="t",
        description="d",
        owner_suggestion="Technical Lead",
    )
    assert item2.owner_suggestion == AssignmentRole.TECHNICAL_LEAD


def test_owner_suggestion_menu_is_present_in_the_system_prompt():
    for role in AssignmentRole:
        assert role.value in analysis_engine.OWNER_SUGGESTIONS
        assert f"'{role.value}'" in analysis_engine._SYSTEM_PROMPT
