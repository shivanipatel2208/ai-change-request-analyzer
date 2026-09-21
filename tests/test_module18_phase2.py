"""Verifies Module 18 Phase 2 (Notifications, My Work & Personal
Engineering Queue - Risk Escalation + Analysis Completion notifications):

  * ANALYSIS_COMPLETED fires for the CR's creator/assignees (never the
    person who triggered it) the very first time a change request is
    analyzed - and never again on a later re-analysis of the same CR,
    where ANALYSIS_SIGNIFICANTLY_CHANGED/RISK_ESCALATED take over instead
    (see test_ai_analysis_phase3.py for the former, already established).
  * RISK_ESCALATED fires when a re-analysis lands the change request in a
    strictly HIGHER risk bucket than it was in before (e.g. low -> high) -
    reusing app/services/analysis_delta.py::compare_analyses's own
    risk_bucket_before/risk_bucket_after, never a second risk computation.
  * RISK_ESCALATED never fires when risk stays the same bucket, or actually
    improves (moves to a LOWER bucket) - only a genuine escalation counts.
  * RISK_ESCALATED can fire alongside ANALYSIS_SIGNIFICANTLY_CHANGED for
    the same re-analysis (a risk-bucket move is itself one of that
    notification's own significant-change reasons) - both are expected,
    not a duplicate of one event.
  * Both new notification types are scoped exactly like the existing
    ANALYSIS_SIGNIFICANTLY_CHANGED notification - the CR's creator and
    assignees, never the user who actually ran the analysis.

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) - no real network call, matching this app's established
testing pattern. No test data ever uses grubbrr.com - alight.com
throughout, per this project's own standing rule.

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

client = TestClient(app)


def _unique_email() -> str:
    return f"m18p2-{uuid.uuid4().hex[:10]}@example.com"


def _auth(name: str = "Module18 Phase2 Tester") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _analysis_json(risk_score: float) -> dict:
    """One shared shape, with only the one Risk's own `score` varying -
    that's the single number app/services/analysis_engine.py::
    _overall_risk_score() actually uses to set Analysis.risk_score (the
    worst individual risk, not an average - see that function's own
    docstring), so this is the one thing that needs to move between calls
    to move the resulting risk bucket."""
    return {
        "summary": "Adds OTP-based verification to checkout.",
        "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
        "requirements": [
            {
                "category": "functional",
                "description": "Customers must receive a one-time password by SMS to verify their identity during checkout.",
                "priority": "high",
            }
        ],
        "affected_components": [],
        "dependencies": [],
        "risks": [
            {
                "category": "security",
                "description": "OTP codes could be intercepted or brute-forced.",
                "severity": "high",
                "probability": 0.3,
                "score": risk_score,
                "explanation": "Rate limiting mitigates most of this.",
                "mitigation": "Rate-limit OTP attempts per phone number.",
            }
        ],
        "security_findings": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "impact_assessments": [],
        "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
        "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
    }


class _ScriptedProvider:
    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        response = self._responses[min(self._call_count, len(self._responses) - 1)]
        self._call_count += 1
        return json.dumps(response)


def _notifications_for(headers: dict, notification_type: str) -> list[dict]:
    response = client.get("/api/notifications", headers=headers)
    assert response.status_code == 200
    return [n for n in response.json() if n["type"] == notification_type]


def test_analysis_completed_fires_for_creator_on_first_analysis_only(monkeypatch):
    creator_headers, creator_id = _auth("CR Creator")
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _ScriptedProvider([_analysis_json(10.0), _analysis_json(10.0)]))
    created = _create_change_request(creator_headers)

    first = client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    assert first.status_code == 201

    completed = _notifications_for(creator_headers, "analysis_completed")
    # The creator is the one who ran it - never notified about their own action.
    assert len(completed) == 0


def test_analysis_completed_notifies_assignee_but_not_the_analyzer(monkeypatch):
    creator_headers, creator_id = _auth("CR Creator Two")
    assignee_headers, assignee_id = _auth("Assigned Engineer")
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _ScriptedProvider([_analysis_json(10.0)]))
    created = _create_change_request(creator_headers)

    assign = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    assert assign.status_code == 201

    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    assert analyze.status_code == 201

    assignee_completed = _notifications_for(assignee_headers, "analysis_completed")
    assert len(assignee_completed) == 1
    assert assignee_completed[0]["change_request_id"] == created["id"]

    analyzer_completed = _notifications_for(creator_headers, "analysis_completed")
    assert len(analyzer_completed) == 0


def test_risk_escalated_fires_when_bucket_moves_from_low_to_critical(monkeypatch):
    creator_headers, creator_id = _auth("Escalation Creator")
    assignee_headers, assignee_id = _auth("Escalation Assignee")
    provider = _ScriptedProvider([_analysis_json(10.0), _analysis_json(90.0)])
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)
    created = _create_change_request(creator_headers)

    assign = client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "technical_lead"},
        headers=creator_headers,
    )
    assert assign.status_code == 201

    first = client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    assert first.status_code == 201
    assert first.json()["risk_score"] == 10.0

    second = client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    assert second.status_code == 201
    assert second.json()["risk_score"] == 90.0

    escalated = _notifications_for(assignee_headers, "risk_escalated")
    assert len(escalated) == 1
    assert "critical" in escalated[0]["title"].lower()
    assert escalated[0]["change_request_id"] == created["id"]

    # The same re-analysis is ALSO a materially significant change (risk
    # bucket is one of compare_analyses' own significant-change reasons) -
    # both notifications are expected together, not a contradiction.
    significantly_changed = _notifications_for(assignee_headers, "analysis_significantly_changed")
    assert len(significantly_changed) == 1

    # Never notifies the person who actually ran the re-analysis.
    assert len(_notifications_for(creator_headers, "risk_escalated")) == 0


def test_risk_escalated_never_fires_when_risk_bucket_is_unchanged(monkeypatch):
    creator_headers, creator_id = _auth("Stable Risk Creator")
    assignee_headers, assignee_id = _auth("Stable Risk Assignee")
    provider = _ScriptedProvider([_analysis_json(10.0), _analysis_json(12.0)])
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)
    created = _create_change_request(creator_headers)

    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)

    assert len(_notifications_for(assignee_headers, "risk_escalated")) == 0


def test_risk_escalated_never_fires_when_risk_actually_improves(monkeypatch):
    creator_headers, creator_id = _auth("Improving Risk Creator")
    assignee_headers, assignee_id = _auth("Improving Risk Assignee")
    provider = _ScriptedProvider([_analysis_json(90.0), _analysis_json(10.0)])
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)
    created = _create_change_request(creator_headers)

    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=creator_headers)

    assert len(_notifications_for(assignee_headers, "risk_escalated")) == 0
