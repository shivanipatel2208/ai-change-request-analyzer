"""Verifies Module 19 Phase 1 (Engineering Change Analytics - foundation):
the new `AI_ANALYSIS_FAILED` history event that gets logged whenever a
POST /analyze attempt fails, and the shared `app/services/analytics.py`
filtering helpers those failure counts (and every later Module 19 metric)
will build on.

Before this phase, a failed analysis attempt (bad JSON, schema validation
failure, timeout, etc.) resulted in nothing at all being persisted to the
database - just an HTTPException returned to the caller. That was a real
gap: Module 19's "AI analysis failures" metric (spec section 7) would have
had zero real data to report. This is the one dedicated test file for that
new tracking hook.

Following this project's established HTTP-only testing convention, the new
history event is verified the same way every other history event in this
suite is - through the real `/analyze` endpoint (monkeypatched with a fake
AI provider that fails in different ways) and the real
GET /{id}/history endpoint, never by touching the database directly.

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
    return f"m19-{uuid.uuid4().hex[:10]}@alight.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module19 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add order-status webhook to POS",
        "description": "Emit a webhook event whenever an order's status changes on the POS.",
        "business_objective": "Let downstream systems react to order status changes in real time.",
        "priority": "medium",
        "requested_by": "Casey Alight",
        "target_system": "POS Backend",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FailingProvider:
    """Same shape as test_analysis_engine.py's own `_FakeProvider` - stands
    in for AnthropicProvider, but always fails in one of the ways the real
    provider already can (invalid JSON, schema violation, or a raised
    exception standing in for a timeout)."""

    def __init__(self, response_text=None, raise_exc=None):
        self._text = response_text
        self._raise = raise_exc

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        if self._raise is not None:
            raise self._raise
        return self._text


def _patch_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)


def _get_history(headers: dict, change_request_id: int) -> list:
    response = client.get(f"/api/change-requests/{change_request_id}/history", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_invalid_json_failure_logs_ai_analysis_failed_history_event(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FailingProvider("this is not json at all"))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 422

    history = _get_history(headers, created["id"])
    failed_events = [event for event in history if event["action"] == "ai_analysis_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["actor_label"] == "AI Analyzer"
    assert failed_events[0]["user_id"] is None
    assert failed_events[0]["new_value"]


def test_timeout_failure_logs_ai_analysis_failed_history_event(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    class _Timeout(Exception):
        pass

    _Timeout.__name__ = "APITimeoutError"
    _patch_provider(monkeypatch, _FailingProvider(raise_exc=_Timeout("took too long")))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 504

    history = _get_history(headers, created["id"])
    failed_events = [event for event in history if event["action"] == "ai_analysis_failed"]
    assert len(failed_events) == 1
    assert "took too long" in failed_events[0]["new_value"]


def test_successful_analysis_does_not_log_a_failure_event(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    ok_response = {
        "summary": "Adds a webhook emitted on order status change.",
        "classification": {"category": "Integration", "confidence": 0.8, "reason": "New outbound event."},
        "requirements": [
            {"category": "functional", "description": "Emit webhook on status change.", "priority": "high"},
        ],
        "affected_components": [
            {
                "name": "Order Service",
                "type": "backend",
                "impact_level": "low",
                "reason": "Adds an outbound call on an existing state transition.",
                "confidence": 70,
            }
        ],
        "dependencies": [],
        "risks": [],
        "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
        "complexity": {"level": "low", "reasoning": "Single new outbound call."},
        "effort": {"backend": "1 day", "frontend": "Insufficient information.", "testing": "0.5 day", "total": "1-2 developer-days"},
        "missing_information": [],
        "test_cases": [
            {
                "id": "TC-001",
                "title": "Webhook fires on status change",
                "type": "integration",
                "priority": "high",
                "description": "Change an order's status and verify the webhook fires.",
                "expected_result": "Webhook payload matches the new status.",
            }
        ],
        "implementation_plan": [
            {
                "task": "Add webhook emitter",
                "description": "Emit the webhook after the status transition commits.",
                "component": "Order Service",
                "priority": "high",
                "estimated_effort": "4h",
            }
        ],
        "recommendation": {"decision": "approve", "reasoning": "Small, well-scoped, low risk."},
    }
    _patch_provider(monkeypatch, _FailingProvider(json.dumps(ok_response)))

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201

    history = _get_history(headers, created["id"])
    failed_events = [event for event in history if event["action"] == "ai_analysis_failed"]
    assert failed_events == []


def test_repeated_failures_log_one_event_each(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    _patch_provider(monkeypatch, _FailingProvider("still not json"))

    first = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert first.status_code == 422
    second = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert second.status_code == 422

    history = _get_history(headers, created["id"])
    failed_events = [event for event in history if event["action"] == "ai_analysis_failed"]
    assert len(failed_events) == 2
