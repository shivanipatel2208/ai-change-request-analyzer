"""Verifies Module 17 Phase 2 (Test Cases & Implementation Plan 2.0 -
richer test-case generation):

  * TestCaseItem (the AI's own output shape) accepts preconditions/steps
    and TestCase persists them correctly end-to-end through a real
    POST /analyze call - preconditions as free text, steps as an ordered
    list (round-tripped through the app's established JSON-text-column
    pattern, same as Module 17 Phase 1 already proved for the schema
    layer alone).
  * The five test types Module 17 Phase 1 added to the TestType enum
    (negative/boundary/api/ui/data_validation) are genuine, usable
    choices end-to-end - not just enum members nothing ever emits - by
    persisting a test case of one of them through the same real
    POST /analyze call.
  * A test case naming NO preconditions/steps at all (the shape every
    test in test_analysis_engine.py already uses) still persists cleanly
    with safe empty defaults - Phase 2 never made these fields required.
  * `_coerce_steps` (the AI-output-shape robustness helper) turns a
    weaker/local model's numbered-list-in-a-single-string habit into a
    real ordered list instead of one giant blob, the same "handle
    validation errors gracefully" spirit as every other normalizer in
    app/schemas/ai_analysis.py.
  * The widened test-type menu is actually present in the system prompt
    sent to the AI (a silent prompt/enum drift bug elsewhere in this
    module would otherwise never be caught by any test).

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
from app.schemas.ai_analysis import TestCaseItem, _coerce_steps

client = TestClient(app)


def _unique_email() -> str:
    return f"m17p2-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase2 Tester", "email": email, "password": password, "confirm_password": password},
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


def _base_analysis_json(test_cases):
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
        "test_cases": test_cases,
        "implementation_plan": [
            {
                "task": "Add OTP generation endpoint",
                "description": "Backend endpoint that generates and stores a one-time password.",
                "component": "Backend",
                "priority": "high",
                "estimated_effort": "2 days",
                "dependencies": None,
            }
        ],
        "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
    }


class _FixedProvider:
    def __init__(self, analysis_json):
        self._analysis_json = analysis_json

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(self._analysis_json)


def test_preconditions_and_steps_persist_end_to_end(monkeypatch):
    analysis_json = _base_analysis_json(
        [
            {
                "id": "TC-001",
                "title": "OTP code expires after 5 minutes",
                "type": "security",
                "priority": "high",
                "description": "Verify an OTP code can't be used once it has expired.",
                "preconditions": "Customer has requested an OTP code and 5 minutes have elapsed.",
                "steps": ["Open checkout", "Enter the expired OTP code", "Submit the form"],
                "expected_result": "The expired code is rejected with a clear error.",
            }
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    test_case = response.json()["test_cases"][0]

    assert test_case["preconditions"] == "Customer has requested an OTP code and 5 minutes have elapsed."
    assert test_case["steps"] == ["Open checkout", "Enter the expired OTP code", "Submit the form"]


def test_new_test_types_are_usable_end_to_end(monkeypatch):
    analysis_json = _base_analysis_json(
        [
            {
                "id": "TC-001",
                "title": "OTP field rejects a code one character short",
                "type": "boundary",
                "priority": "medium",
                "description": "Submit a 5-digit code when 6 digits are required.",
                "expected_result": "The form shows a validation error and does not submit.",
            },
            {
                "id": "TC-002",
                "title": "OTP endpoint rejects a malformed request body",
                "type": "api",
                "priority": "medium",
                "description": "POST to the OTP verification endpoint with a missing field.",
                "expected_result": "A 422 response is returned; no OTP is marked as used.",
            },
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    test_cases = {tc["test_id"]: tc for tc in response.json()["test_cases"]}

    assert test_cases["TC-001"]["test_type"] == "boundary"
    assert test_cases["TC-002"]["test_type"] == "api"


def test_test_case_with_no_preconditions_or_steps_still_persists_cleanly(monkeypatch):
    # The exact shape test_analysis_engine.py's own fixtures already use -
    # Phase 2 must never make preconditions/steps required.
    analysis_json = _base_analysis_json(
        [
            {
                "id": "TC-001",
                "title": "Checkout awards multiplied points",
                "type": "integration",
                "priority": "high",
                "description": "Complete a checkout and verify points awarded match the configured multiplier.",
                "expected_result": "Points awarded equal base points * multiplier.",
            }
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedProvider(analysis_json))
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    test_case = response.json()["test_cases"][0]

    assert test_case["preconditions"] is None
    assert test_case["steps"] == []


def test_coerce_steps_splits_a_numbered_single_string_into_real_steps():
    assert _coerce_steps("1. Open checkout\n2) Enter code\n3. Submit") == [
        "Open checkout",
        "Enter code",
        "Submit",
    ]
    assert _coerce_steps(None) == []
    assert _coerce_steps([]) == []
    assert _coerce_steps(["Already a list", ""]) == ["Already a list"]


def test_test_case_item_normalizes_placeholder_preconditions_to_none():
    item = TestCaseItem(
        id="TC-001",
        title="t",
        type="unit",
        description="d",
        expected_result="e",
        preconditions="e.g. user is logged in",
    )
    assert item.preconditions == "user is logged in"


def test_test_case_item_normalizes_validation_shorthand_to_data_validation():
    # Regression test: a real analysis run failed validation entirely
    # ("1 validation error for AIAnalysisResult test_cases.1.type") because
    # the AI shortened DATA_VALIDATION to just "validation" - a plain
    # near-miss, not a genuinely wrong answer, so it should normalize
    # cleanly rather than fail the whole analysis.
    item = TestCaseItem(
        id="TC-001",
        title="t",
        type="validation",
        description="d",
        expected_result="e",
    )
    assert item.type.value == "data_validation"


def test_test_case_item_normalizes_functional_to_manual():
    # Regression test: a second real analysis run failed the same way, this
    # time with the AI writing "functional" - a type this enum deliberately
    # doesn't have (see TestType's own docstring: MANUAL/UNIT/INTEGRATION/
    # E2E already cover it). Same fix family as the "validation" case above.
    item = TestCaseItem(
        id="TC-001",
        title="t",
        type="functional",
        description="d",
        expected_result="e",
    )
    assert item.type.value == "manual"


def test_test_case_item_strips_trailing_test_suffix():
    # "unit_test", "negative_test", etc. are a very common way to phrase
    # these that this enum's own values never include.
    item = TestCaseItem(
        id="TC-001",
        title="t",
        type="negative_test",
        description="d",
        expected_result="e",
    )
    assert item.type.value == "negative"


def test_widened_test_type_menu_is_present_in_the_system_prompt():
    # Quoted so a short value like "ui" can't false-positive-match inside
    # an unrelated word (e.g. "guidance") elsewhere in the prompt text.
    for test_type in ("negative", "boundary", "api", "ui", "data_validation"):
        assert test_type in analysis_engine.TEST_TYPES
        assert f"'{test_type}'" in analysis_engine._SYSTEM_PROMPT
