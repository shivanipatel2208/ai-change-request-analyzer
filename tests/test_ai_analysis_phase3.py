"""Verifies Module 13 Phase 3 (AI Analysis 2.0 - outdated awareness,
re-analysis notifications, AI-failure safety):

  * AnalysisRead.is_outdated - computed fresh by GET .../analysis and
    POST .../analyze, using the same workflow_rules.is_analysis_outdated
    ChangeRequestDetail.is_analysis_outdated already relies on - just
    exposed on the Analysis object itself so a caller doesn't have to also
    fetch the CR detail to know whether what they're looking at is stale.
  * re-analyzing into a materially different result (bigger risk bucket,
    changed recommendation, ...) notifies the CR's creator + assignees
    with a new ANALYSIS_SIGNIFICANTLY_CHANGED notification - but never the
    person who triggered the re-analysis - reusing Phase 2's
    compare_analyses()/is_significant_change rather than a second
    "did this change materially" check.
  * re-analyzing into something NOT materially different sends no such
    notification.
  * a failed (re-)analysis never touches whatever analysis already existed
    - the API layer's own error message says so.

The real AI provider is never called - same monkeypatched _FakeProvider
pattern as test_analysis_engine.py / test_change_request_editing.py /
test_analysis_delta.py.

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
    return f"phase3-{uuid.uuid4().hex[:10]}@example.com"


def _register(name: str) -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _auth() -> tuple[dict, int]:
    return _register("Phase3 Tester")


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


def _notifications(headers: dict):
    return client.get("/api/notifications", headers=headers).json()


class _FakeProvider:
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


def _analyze(headers, cr_id, response_dict, monkeypatch):
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_dict)))
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return response.json()


# Same low-risk -> high-risk pair test_analysis_delta.py already validated
# as "a significant change" (risk moved medium -> high, complexity medium
# -> high, recommendation approve_with_conditions -> requires_clarification).
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


# --- is_outdated on the Analysis itself ------------------------------------


def test_is_outdated_false_immediately_after_analysis(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    analysis = _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    assert analysis["is_outdated"] is False

    fetched = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    assert fetched["is_outdated"] is False


def test_is_outdated_true_after_edit_until_reanalyzed(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )
    assert edit.status_code == 200

    fetched = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    assert fetched["is_outdated"] is True
    assert fetched["change_request_version"] == 1  # still the version it actually ran against

    reanalyzed = _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    assert reanalyzed["is_outdated"] is False
    assert reanalyzed["change_request_version"] == 2


# --- Significant-change notification on re-analysis ------------------------


def test_significant_reanalysis_notifies_creator_and_assignees_not_the_reanalyzer(monkeypatch):
    creator_headers, _ = _auth()
    created = _create_change_request(creator_headers)

    assignee_headers, assignee_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "technical_lead"},
        headers=creator_headers,
    )

    reanalyzer_headers, _ = _auth()  # a different, unassigned authenticated user

    _analyze(creator_headers, created["id"], FIRST_PASS, monkeypatch)
    _analyze(reanalyzer_headers, created["id"], SECOND_PASS, monkeypatch)

    creator_notifs = _notifications(creator_headers)
    assignee_notifs = _notifications(assignee_headers)
    reanalyzer_notifs = _notifications(reanalyzer_headers)

    assert any(n["type"] == "analysis_significantly_changed" for n in creator_notifs)
    assert any(n["type"] == "analysis_significantly_changed" for n in assignee_notifs)
    # The person who triggered the re-analysis never gets notified about
    # their own action.
    assert not any(n["type"] == "analysis_significantly_changed" for n in reanalyzer_notifs)


def test_non_significant_reanalysis_sends_no_notification(monkeypatch):
    creator_headers, _ = _auth()
    created = _create_change_request(creator_headers)

    assignee_headers, assignee_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )

    _analyze(creator_headers, created["id"], FIRST_PASS, monkeypatch)
    # Re-analyzing with the exact same canned response - nothing material
    # moved, so no ANALYSIS_SIGNIFICANTLY_CHANGED notification should fire.
    _analyze(creator_headers, created["id"], FIRST_PASS, monkeypatch)

    assignee_notifs = _notifications(assignee_headers)
    assert not any(n["type"] == "analysis_significantly_changed" for n in assignee_notifs)


def test_first_ever_analysis_sends_no_significant_change_notification(monkeypatch):
    """There's nothing to compare against yet - a first analysis is never
    itself a "change", significant or otherwise."""
    creator_headers, _ = _auth()
    created = _create_change_request(creator_headers)

    assignee_headers, assignee_id = _auth()
    client.post(
        f"/api/change-requests/{created['id']}/assignments",
        json={"user_id": assignee_id, "role": "reviewer"},
        headers=creator_headers,
    )

    _analyze(creator_headers, created["id"], SECOND_PASS, monkeypatch)  # even the "riskier" shape

    assignee_notifs = _notifications(assignee_headers)
    assert not any(n["type"] == "analysis_significantly_changed" for n in assignee_notifs)


# --- AI-failure safety -------------------------------------------------------


def test_failed_reanalysis_leaves_prior_analysis_untouched_and_says_so(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)
    prior = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()

    _patch_provider(monkeypatch, _FakeProvider(response_text="not valid json at all"))
    failed = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert failed.status_code == 422
    detail = failed.json()["detail"]
    assert "still available" in detail
    assert "Version 1" in detail

    still_there = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    assert still_there["id"] == prior["id"]
    assert still_there["summary"] == prior["summary"]


def test_failed_first_analysis_error_has_no_prior_analysis_mention(monkeypatch):
    """No prior analysis exists yet, so the error shouldn't claim one is
    "still available" - that would be misleading, not reassuring."""
    headers, _ = _auth()
    created = _create_change_request(headers)

    _patch_provider(monkeypatch, _FakeProvider(configured=False))
    failed = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert failed.status_code == 503
    assert "still available" not in failed.json()["detail"]


# --- Report generation and an outdated analysis ------------------------------
#
# Module 20 (Version-Aware Reports) deliberately changed this behavior: this
# test used to assert that downloading the CURRENT report still succeeded
# even when the analysis was outdated (just with a warning banner) - but
# that meant the report silently mixed the CR's live (post-edit) fields with
# the stale, pre-edit analysis, exactly what that module's own spec says
# never to do ("do not generate a misleading current report"). The current-
# report request now correctly refuses (409) instead; the change request's
# data is still fully reportable, just explicitly as a labeled historical
# report for the version that was actually analyzed. Full coverage of the
# new version-mismatch/historical-report behavior lives in
# tests/test_module20_phase1.py - this one test is kept here (updated) since
# it's the one place in this file that already had the exact "outdated
# analysis" setup handy.


def test_current_report_now_refuses_when_analysis_is_outdated_but_historical_report_still_works(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)

    client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )

    current = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert current.status_code == 409
    assert current.json()["detail"]["last_analyzed_version"] == 1

    historical = client.get(f"/api/change-requests/{created['id']}/report?version=1", headers=headers)
    assert historical.status_code == 200
    assert historical.headers["content-type"] == "application/pdf"
    assert len(historical.content) > 0


def test_report_downloads_successfully_when_analysis_is_current(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], FIRST_PASS, monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    assert len(response.content) > 0
