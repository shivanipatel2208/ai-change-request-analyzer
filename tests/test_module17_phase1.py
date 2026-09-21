"""Verifies Module 17 Phase 1 (Test Cases & Implementation Plan 2.0 -
Foundation):

  * The new TestType values (negative/boundary/api/ui/data_validation) and
    HistoryAction values (test_case_edited/implementation_task_edited)
    exist with the exact string values the rest of the app will rely on.
  * TestCaseRead/ImplementationTaskRead expose every new Phase 1+ field
    (preconditions, steps, owner_suggestion, requirement/risk references,
    analysis_version, is_outdated, edited_by/edited_at/edit_reason) with
    safe defaults for an analysis that predates this module - nothing
    from before Module 17 breaks.
  * `steps` round-trips correctly through its JSON-encoded storage column,
    the same pattern ChangeRequest.tags already uses.
  * analysis_version and is_outdated are populated fresh by the API layer
    on every test case/task, mirroring KnowledgeEvidenceRead.is_outdated -
    both start false/current right after a fresh analysis, and is_outdated
    flips to true for every test case/task once the change request is
    edited, exactly like the analysis (and its knowledge evidence)
    already do.

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
from app.models.enums import HistoryAction, TestType
from app.schemas.implementation_task import ImplementationTaskRead
from app.schemas.test_case import TestCaseRead

client = TestClient(app)


def _unique_email() -> str:
    return f"m17p1-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase1 Tester", "email": email, "password": password, "confirm_password": password},
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


_VALID_ANALYSIS_JSON = {
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


class _FixedAnalysisProvider:
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(_VALID_ANALYSIS_JSON)


def test_new_enum_values_exist_with_expected_string_values():
    assert TestType.NEGATIVE.value == "negative"
    assert TestType.BOUNDARY.value == "boundary"
    assert TestType.API.value == "api"
    assert TestType.UI.value == "ui"
    assert TestType.DATA_VALIDATION.value == "data_validation"
    assert HistoryAction.TEST_CASE_EDITED.value == "test_case_edited"
    assert HistoryAction.IMPLEMENTATION_TASK_EDITED.value == "implementation_task_edited"


def test_schemas_expose_every_new_field_with_safe_defaults():
    test_case_fields = set(TestCaseRead.model_fields.keys())
    assert {
        "preconditions",
        "steps",
        "requirement_references",
        "risk_references",
        "analysis_version",
        "is_outdated",
        "edited_by",
        "edited_at",
        "edit_reason",
    }.issubset(test_case_fields)

    task_fields = set(ImplementationTaskRead.model_fields.keys())
    assert {
        "owner_suggestion",
        "requirement_references",
        "analysis_version",
        "is_outdated",
        "edited_by",
        "edited_at",
        "edit_reason",
    }.issubset(task_fields)

    # An analysis from before this module ran has none of this recorded -
    # the schema must still validate cleanly with every new field at its
    # safe default (empty list / None / False), never a validation error.
    pre_module17_test_case = TestCaseRead(
        id=1,
        analysis_id=1,
        test_id="TC-001",
        title="Legacy test",
        test_type="manual",
        priority="medium",
        description="d",
        expected_result="e",
    )
    assert pre_module17_test_case.preconditions is None
    assert pre_module17_test_case.steps == []
    assert pre_module17_test_case.requirement_references == []
    assert pre_module17_test_case.is_outdated is False
    assert pre_module17_test_case.edited_by is None

    pre_module17_task = ImplementationTaskRead(
        id=1,
        analysis_id=1,
        task="Legacy task",
        description="d",
        component="Backend",
        priority="medium",
        estimated_effort="1 day",
    )
    assert pre_module17_task.owner_suggestion is None
    assert pre_module17_task.is_outdated is False


def test_steps_round_trips_through_json_storage():
    parsed = TestCaseRead(
        id=1,
        analysis_id=1,
        test_id="TC-002",
        title="Steps round-trip",
        test_type="unit",
        priority="medium",
        description="d",
        expected_result="e",
        steps=json.dumps(["Open checkout", "Enter an expired OTP code", "Submit"]),
    )
    assert parsed.steps == ["Open checkout", "Enter an expired OTP code", "Submit"]

    # Malformed/garbage stored JSON degrades to an empty list, never a
    # validation error or a crash.
    garbage = TestCaseRead(
        id=1,
        analysis_id=1,
        test_id="TC-003",
        title="Garbage steps",
        test_type="unit",
        priority="medium",
        description="d",
        expected_result="e",
        steps="not valid json",
    )
    assert garbage.steps == []


def test_analysis_version_and_outdated_populated_fresh_and_flip_on_edit(monkeypatch):
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedAnalysisProvider())
    headers = _auth()
    created = _create_change_request(headers)

    analyze_response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze_response.status_code == 201
    body = analyze_response.json()

    assert len(body["test_cases"]) == 1
    assert len(body["implementation_tasks"]) == 1
    assert body["test_cases"][0]["analysis_version"] == 1
    assert body["test_cases"][0]["is_outdated"] is False
    assert body["implementation_tasks"][0]["analysis_version"] == 1
    assert body["implementation_tasks"][0]["is_outdated"] is False

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"title": "Add OTP authentication for customers at checkout"},
        headers=headers,
    )
    assert edit.status_code == 200

    latest = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert latest.status_code == 200
    latest_body = latest.json()
    assert latest_body["is_outdated"] is True
    assert latest_body["test_cases"][0]["is_outdated"] is True
    assert latest_body["implementation_tasks"][0]["is_outdated"] is True
    # The test case/task itself never silently changes what version it
    # actually belongs to - only whether that version is now stale.
    assert latest_body["test_cases"][0]["analysis_version"] == 1
    assert latest_body["implementation_tasks"][0]["analysis_version"] == 1
