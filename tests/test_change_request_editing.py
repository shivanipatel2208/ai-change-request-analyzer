"""Verifies Module 12 Phase 2 (Enterprise Workflow - Editing, Versioning,
Audit Trail, AI-outdated detection):

  * PUT /api/change-requests/{id} - partial-update editing, permission
    check, no-op edits create no version/history noise
  * field-level history (app/services/history.py + versioning.py) records
    the real old/new value per changed field, not one vague "updated" line
  * GET .../history, GET .../versions, GET .../versions/{n}, GET .../compare
  * "is the AI analysis outdated" - becomes true after an edit, becomes
    false again after re-analyzing (uses the same _FakeProvider/monkeypatch
    pattern as tests/test_analysis_engine.py so no real API key/call is
    needed)
  * the first successful analysis auto-transitions status from
    Pending Analysis -> Analyzed
  * tags round-trip through create and edit

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
from app.models.change_request import ChangeRequest

client = TestClient(app)


def _unique_email() -> str:
    return f"edit-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Editing Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP login to mobile app",
        "description": "Allow customers to log in using a one-time passcode sent to their registered number.",
        "priority": "medium",
        "requested_by": "Morgan Lee",
        "target_system": "Mobile App",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FakeProvider:
    """Same stand-in used in tests/test_analysis_engine.py - returns canned
    text instead of calling the real AI provider."""

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


# A minimal, valid AIAnalysisResult - only the editing/versioning behavior
# is under test here, not the analysis content itself (that's Module 6's
# own test file), so this stays as small as the schema allows.
_MINIMAL_ANALYSIS_RESPONSE = {
    "summary": "Adds OTP-based login to the mobile app.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.8, "reason": "New auth flow."},
    "requirements": [],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
    "complexity": {"level": "medium", "reasoning": "New auth flow, moderate scope."},
    "effort": {"backend": "2 days", "frontend": "2 days", "testing": "1 day", "total": "5 developer-days"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "approve", "reasoning": "Well-scoped."},
}


# --- Basic auth / not-found guards --------------------------------------


def test_edit_requires_authentication():
    response = client.put("/api/change-requests/1", json={"title": "New title here"})
    assert response.status_code == 401


def test_edit_returns_404_for_unknown_change_request():
    headers = _auth()
    response = client.put(
        "/api/change-requests/999999999", json={"title": "New title here"}, headers=headers
    )
    assert response.status_code == 404


# --- Editing / versioning ------------------------------------------------


def test_creator_can_edit_and_version_increments():
    headers = _auth()
    created = _create_change_request(headers)
    assert created["current_version"] == 1

    response = client.put(
        f"/api/change-requests/{created['id']}",
        json={"title": "Add OTP login to mobile checkout"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["new_version"] == 2
    assert body["change_request"]["current_version"] == 2
    assert body["change_request"]["title"] == "Add OTP login to mobile checkout"
    assert len(body["changes"]) == 1
    assert body["changes"][0]["field"] == "title"
    assert body["changes"][0]["old_value"] == "Add OTP login to mobile app"
    assert body["changes"][0]["new_value"] == "Add OTP login to mobile checkout"


def test_edit_with_no_real_changes_creates_no_new_version():
    headers = _auth()
    created = _create_change_request(headers)

    # Re-submitting the exact same values that are already stored is a
    # no-op edit - shouldn't create version 2 or any history noise.
    response = client.put(
        f"/api/change-requests/{created['id']}",
        json={
            "title": created["title"],
            "priority": created["priority"],
            "requested_by": created["requested_by"],
            "target_system": created["target_system"],
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["changes"] == []
    assert body["new_version"] is None
    assert body["change_request"]["current_version"] == 1


def test_edit_multiple_fields_records_one_history_event_per_field():
    headers = _auth()
    created = _create_change_request(headers)

    response = client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "high", "environment": "Production"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert {c["field"] for c in body["changes"]} == {"priority", "environment"}

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    field_changed_events = [h for h in history if h["action"] == "field_changed"]
    assert {e["field_name"] for e in field_changed_events} == {"priority", "environment"}

    priority_event = next(e for e in field_changed_events if e["field_name"] == "priority")
    assert priority_event["old_value"] == "Medium"
    assert priority_event["new_value"] == "High"

    env_event = next(e for e in field_changed_events if e["field_name"] == "environment")
    assert env_event["old_value"] is None
    assert env_event["new_value"] == "Production"

    # A VERSION_CREATED event is also recorded alongside the field changes.
    assert any(h["action"] == "version_created" for h in history)


def test_unrelated_user_cannot_edit():
    headers = _auth()
    created = _create_change_request(headers)
    other_headers = _auth()

    response = client.put(
        f"/api/change-requests/{created['id']}",
        json={"title": "Hijacked title change"},
        headers=other_headers,
    )
    assert response.status_code == 403


# --- History / versions / compare endpoints -------------------------------


def test_history_returns_events_newest_first():
    headers = _auth()
    created = _create_change_request(headers)
    client.put(f"/api/change-requests/{created['id']}", json={"priority": "high"}, headers=headers)
    client.put(f"/api/change-requests/{created['id']}", json={"priority": "critical"}, headers=headers)

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert len(history) >= 3  # created + 2 edits (each edit adds a version_created + field_changed pair)
    timestamps = [h["created_at"] for h in history]
    assert timestamps == sorted(timestamps, reverse=True)
    assert history[-1]["action"] == "created"  # oldest event is always creation


def test_versions_list_and_get_single_version():
    headers = _auth()
    created = _create_change_request(headers)
    client.put(f"/api/change-requests/{created['id']}", json={"priority": "high"}, headers=headers)

    versions = client.get(f"/api/change-requests/{created['id']}/versions", headers=headers).json()
    assert [v["version_number"] for v in versions] == [2, 1]  # newest first

    v1 = client.get(f"/api/change-requests/{created['id']}/versions/1", headers=headers)
    assert v1.status_code == 200
    assert v1.json()["snapshot"]["priority"] == "medium"

    v2 = client.get(f"/api/change-requests/{created['id']}/versions/2", headers=headers)
    assert v2.status_code == 200
    assert v2.json()["snapshot"]["priority"] == "high"

    missing = client.get(f"/api/change-requests/{created['id']}/versions/99", headers=headers)
    assert missing.status_code == 404


def test_compare_versions_endpoint():
    headers = _auth()
    created = _create_change_request(headers)
    client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "high", "business_impact": "Improves conversion"},
        headers=headers,
    )

    response = client.get(
        f"/api/change-requests/{created['id']}/compare",
        params={"from": 1, "to": 2},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_version"] == 1
    assert body["to_version"] == 2

    fields = {f["field"]: f for f in body["fields"]}
    assert fields["priority"]["status"] == "changed"
    assert fields["priority"]["old_value"] == "Medium"
    assert fields["priority"]["new_value"] == "High"
    assert fields["business_impact"]["status"] == "added"
    assert fields["title"]["status"] == "unchanged"


# --- AI-outdated detection + re-analyze -----------------------------------


def test_first_analysis_transitions_status_to_analyzed(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    assert created["status"] == "pending_analysis"
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))

    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["status"] == "analyzed"
    assert detail["is_analysis_outdated"] is False


def test_editing_after_analysis_marks_it_outdated_then_reanalyze_clears_it(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))

    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["is_analysis_outdated"] is False
    assert detail["latest_analysis"]["change_request_version"] == 1

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["is_analysis_outdated"] is True

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["is_analysis_outdated"] is True
    assert detail["current_version"] == 2

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert any(h["action"] == "ai_analysis_invalidated" for h in history)

    # Re-analyzing brings it back up to date, tagged with the new version.
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))
    reanalyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert reanalyze.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["is_analysis_outdated"] is False
    assert detail["latest_analysis"]["change_request_version"] == 2


def test_reanalyzing_a_cr_already_past_analyzed_does_not_move_status_backwards(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)

    # Manually move the CR further along the lifecycle than Analyzed.
    with SessionLocal() as db:
        from app.models.enums import ChangeRequestStatus

        cr = db.get(ChangeRequest, created["id"])
        cr.status = ChangeRequestStatus.IN_REVIEW
        db.commit()

    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_MINIMAL_ANALYSIS_RESPONSE)))
    reanalyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert reanalyze.status_code == 201

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["status"] == "in_review"  # unchanged - not forced back to "analyzed"


# --- Tags round-trip -------------------------------------------------------


def test_tags_round_trip_through_create_and_edit():
    headers = _auth()
    created = _create_change_request(headers, tags=["mobile", "auth"])
    assert created["tags"] == ["mobile", "auth"]

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["tags"] == ["mobile", "auth"]

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"tags": ["mobile", "auth", "otp"]},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["tags"] == ["mobile", "auth", "otp"]
    assert edit.json()["changes"][0]["field"] == "tags"

    detail = client.get(f"/api/change-requests/{created['id']}", headers=headers).json()
    assert detail["tags"] == ["mobile", "auth", "otp"]
