"""Verifies Module 14 Phase 6 (Analysis & Impact Intelligence - Human
Review):

  * PATCH .../requirements/{id}/review - an authorized human marks a
    Requirement Confirmed or Needs Clarification, WITHOUT touching that
    row's AI-generated certainty/confidence/evidence. A comment is
    required for Needs Clarification, optional for Confirmed. Permission-
    gated (workflow_rules.can_review_analysis_findings) and recorded on
    the change request's audit history (HistoryAction.REQUIREMENT_REVIEWED).
  * PATCH .../security-findings/{id}/status - an authorized human moves a
    Security finding's Status (typically Open -> Acknowledged ->
    Resolved, but a human may also reopen one) - the AI itself can only
    ever leave a finding Open/Not Applicable (see test_module14_phase5.py's
    test_ai_cannot_claim_acknowledged_or_resolved_status), so Acknowledged/
    Resolved only ever appear via this endpoint. Same permission-gating
    and audit-history recording (HistoryAction.SECURITY_FINDING_STATUS_CHANGED).

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
    return f"m14p6-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module14 Phase6 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add bulk export to admin dashboard",
        "description": "Let Alight.com admins export the full customer list as a CSV from the dashboard.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Admin Dashboard",
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
        "summary": "Adds a CSV export button to the admin dashboard.",
        "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New export capability."},
        "requirements": [
            {
                "category": "functional",
                "description": "Admins can export the full customer list as a CSV file.",
                "priority": "medium",
                "certainty": "known",
                "confidence": 90.0,
                "evidence": "The request explicitly asks for a CSV export.",
            }
        ],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_findings": [
            {
                "category": "data_protection",
                "finding": "Bulk customer data export needs access controls.",
                "severity": "high",
                "evidence": "The export includes the full customer list.",
                "recommendation": "Restrict export to admin roles and log every export.",
                "status": "open",
            }
        ],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "low", "reasoning": "A straightforward export feature."},
        "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
    }
    base.update(overrides)
    return base


def _analyze(headers, cr_id):
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return client.get(f"/api/change-requests/{cr_id}/analysis", headers=headers).json()


def _setup_analysis(monkeypatch, headers, cr_id):
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_minimal_response())))
    return _analyze(headers, cr_id)


def test_review_requirement_round_trip_never_touches_ai_columns(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    requirement = detail["requirements"][0]
    assert requirement["review_status"] is None  # unreviewed until a human acts

    response = client.patch(
        f"/api/change-requests/{created['id']}/requirements/{requirement['id']}/review",
        json={"review_status": "confirmed"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "confirmed"
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None
    # The AI's own findings are untouched by the review.
    assert body["certainty"] == requirement["certainty"]
    assert body["confidence"] == requirement["confidence"]
    assert body["evidence"] == requirement["evidence"]

    # A human can change their mind - moving to Needs Clarification with a
    # comment overwrites review_status/comment but still leaves certainty/
    # confidence/evidence alone.
    response = client.patch(
        f"/api/change-requests/{created['id']}/requirements/{requirement['id']}/review",
        json={"review_status": "needs_clarification", "comment": "Which admin roles should have export access?"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "needs_clarification"
    assert body["review_comment"] == "Which admin roles should have export access?"
    assert body["certainty"] == requirement["certainty"]


def test_review_requirement_needs_clarification_requires_comment(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    requirement = detail["requirements"][0]

    response = client.patch(
        f"/api/change-requests/{created['id']}/requirements/{requirement['id']}/review",
        json={"review_status": "needs_clarification"},
        headers=headers,
    )
    assert response.status_code == 422


def test_review_requirement_forbidden_for_unrelated_user(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    requirement = detail["requirements"][0]

    outsider_headers, _ = _auth()
    response = client.patch(
        f"/api/change-requests/{created['id']}/requirements/{requirement['id']}/review",
        json={"review_status": "confirmed"},
        headers=outsider_headers,
    )
    assert response.status_code == 403


def test_review_requirement_records_history(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    requirement = detail["requirements"][0]

    client.patch(
        f"/api/change-requests/{created['id']}/requirements/{requirement['id']}/review",
        json={"review_status": "confirmed"},
        headers=headers,
    ).raise_for_status()

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    matching = [h for h in history if h["action"] == "requirement_reviewed"]
    assert len(matching) == 1
    assert matching[0]["new_value"] == "confirmed"
    assert matching[0]["old_value"] == "unreviewed"


def test_update_security_finding_status_round_trip(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    finding = next(f for f in detail["security_findings"] if f["category"] == "data_protection")
    assert finding["status"] == "open"

    response = client.patch(
        f"/api/change-requests/{created['id']}/security-findings/{finding['id']}/status",
        json={"status": "acknowledged", "comment": "Tracked in the export-access ticket."},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["review_comment"] == "Tracked in the export-access ticket."
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None
    # The AI's own finding/severity/evidence/recommendation are untouched.
    assert body["finding"] == finding["finding"]
    assert body["severity"] == finding["severity"]

    response = client.patch(
        f"/api/change-requests/{created['id']}/security-findings/{finding['id']}/status",
        json={"status": "resolved"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_update_security_finding_status_forbidden_for_unrelated_user(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    finding = next(f for f in detail["security_findings"] if f["category"] == "data_protection")

    outsider_headers, _ = _auth()
    response = client.patch(
        f"/api/change-requests/{created['id']}/security-findings/{finding['id']}/status",
        json={"status": "resolved"},
        headers=outsider_headers,
    )
    assert response.status_code == 403


def test_update_security_finding_status_records_history(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    finding = next(f for f in detail["security_findings"] if f["category"] == "data_protection")

    client.patch(
        f"/api/change-requests/{created['id']}/security-findings/{finding['id']}/status",
        json={"status": "acknowledged"},
        headers=headers,
    ).raise_for_status()

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    matching = [h for h in history if h["action"] == "security_finding_status_changed"]
    assert len(matching) == 1
    assert matching[0]["old_value"] == "open"
    assert matching[0]["new_value"] == "acknowledged"
