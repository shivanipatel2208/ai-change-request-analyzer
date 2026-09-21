"""Verifies Module 13 Phase 4 (AI Analysis 2.0 - workflow recommendation
text + human-override recording):

  * AnalysisRead.workflow_recommendation - one computed (not AI-written)
    sentence combining the AI's own recommendation with which approvals it
    actually requires (app/services/workflow_rules.py::recommendation_summary)
  * ApprovalRead.ai_recommendation / overrode_ai_recommendation - what the
    AI recommended on the analysis THIS approval was requested against (by
    approval.cr_version, not necessarily the CR's *current* analysis), and
    whether the approver's decision matched it
  * responding in a way that doesn't match the AI's recommendation records
    an additional AI_RECOMMENDATION_OVERRIDDEN history event alongside the
    normal APPROVED/REJECTED/CHANGES_REQUESTED one - never instead of it,
    and never blocking the decision itself ("AI recommends, humans decide")

The real AI provider is never called - same monkeypatched _FakeProvider
pattern as the other test_ai_analysis_*.py files.

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
    return f"phase4-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Phase4 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


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


def _request_approval(cr_id: int, headers: dict, approver_id: int, approval_type: str = "engineering_manager"):
    return client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": approval_type, "approver_user_id": approver_id},
        headers=headers,
    )


class _FakeProvider:
    def __init__(self, response_text=None, configured=True):
        self._text = response_text
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)


def _analyze(headers, cr_id, response_dict, monkeypatch):
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(response_dict)))
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return response.json()


def _base_response(decision: str, risks=None, category: str = "Security"):
    return {
        "summary": "Adds OTP-based authentication at login.",
        "classification": {"category": category, "confidence": 0.8, "reason": "New authentication factor."},
        "requirements": [],
        "affected_components": [],
        "dependencies": [],
        "risks": risks or [],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "medium", "reasoning": "Touches auth flow."},
        "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
        "missing_information": [],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": decision, "reasoning": "See analysis."},
    }


# "Feature Enhancement" (not "Security") deliberately avoids the
# category-keyword approval add-ons below, so this exercises the plain
# low-risk baseline (Technical) on its own.
APPROVE_RESPONSE = _base_response("approve", category="Feature Enhancement")

# NOTE: the AI Analysis Engine's own response schema (app/schemas/ai_analysis.py
# ::RecommendationResult.decision_allowed) only ever lets the AI recommend
# "approve" / "approve_with_conditions" / "requires_clarification" - REJECT
# is a real ApprovalRecommendation value (kept for old seeded rows / a
# human's own decision) but the AI itself can never produce it via
# /analyze. So these tests use a high-risk "requires_clarification"
# response for the override scenarios instead of "reject".
HIGH_RISK_CLARIFICATION_RESPONSE = _base_response(
    "requires_clarification",
    risks=[
        {
            "category": "security",
            "description": "Severe vulnerability.",
            "severity": "critical",
            "probability": 0.8,
            "score": 90,
            "explanation": "Critical exposure if shipped as-is.",
            "mitigation": "Redesign before proceeding.",
        }
    ],
)
CLARIFICATION_RESPONSE = _base_response("requires_clarification")


# --- workflow_recommendation on the analysis --------------------------------


def test_workflow_recommendation_mentions_ai_decision_and_required_approvals(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    analysis = _analyze(headers, created["id"], HIGH_RISK_CLARIFICATION_RESPONSE, monkeypatch)

    assert "Requires Clarification" in analysis["workflow_recommendation"]
    # Risk score 90 -> critical baseline (Engineering Manager, Security, Director).
    assert "Engineering Manager" in analysis["workflow_recommendation"]
    assert "Security" in analysis["workflow_recommendation"]

    fetched = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers).json()
    assert fetched["workflow_recommendation"] == analysis["workflow_recommendation"]


def test_workflow_recommendation_names_the_low_risk_baseline_approval(monkeypatch):
    """No risks -> risk_score floors at 5.0 -> the low-risk baseline
    (Technical) - required_approval_types() always returns at least that
    baseline, so "no approval needed" never actually happens once a change
    request has been analyzed at all (see
    app/services/workflow_rules.py::_risk_baseline's fallback)."""
    headers, _ = _auth()
    created = _create_change_request(headers)
    analysis = _analyze(headers, created["id"], APPROVE_RESPONSE, monkeypatch)

    assert "Approve" in analysis["workflow_recommendation"]
    assert "requires Technical approval" in analysis["workflow_recommendation"]


# --- ai_recommendation / overrode_ai_recommendation on the approval --------


def test_approving_when_ai_only_asked_for_clarification_is_flagged_as_an_override(monkeypatch):
    """The AI recommended "requires clarification" (which aligns with a
    human responding "changes requested" - see
    test_requesting_changes_when_ai_only_asked_for_clarification_is_not_flagged
    below); approving it directly instead, skipping that clarification, is
    a real divergence from what the AI suggested."""
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], HIGH_RISK_CLARIFICATION_RESPONSE, monkeypatch)

    approver_headers, approver_id = _auth()
    requested = _request_approval(created["id"], headers, approver_id, "engineering_manager").json()
    assert requested["ai_recommendation"] == "Requires Clarification"
    assert requested["overrode_ai_recommendation"] is False  # still pending - nothing decided yet

    responded = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    ).json()
    assert responded["ai_recommendation"] == "Requires Clarification"
    assert responded["overrode_ai_recommendation"] is True

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    override_events = [h for h in history if h["action"] == "ai_recommendation_overridden"]
    assert len(override_events) == 1
    assert "Requires Clarification" in override_events[0]["old_value"]
    # The normal APPROVED event is still recorded too - this is additional,
    # never a replacement.
    assert any(h["action"] == "approved" for h in history)


def test_approving_in_line_with_an_ai_approve_recommendation_is_not_flagged(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], APPROVE_RESPONSE, monkeypatch)

    approver_headers, approver_id = _auth()
    requested = _request_approval(created["id"], headers, approver_id, "technical").json()

    responded = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    ).json()
    assert responded["overrode_ai_recommendation"] is False

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    assert not any(h["action"] == "ai_recommendation_overridden" for h in history)


def test_requesting_changes_when_ai_only_asked_for_clarification_is_not_flagged(monkeypatch):
    """NEEDS_MORE_INFO/REQUIRES_CLARIFICATION both align with a human
    responding "changes requested" - that's not a disagreement, it's the
    same call."""
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], CLARIFICATION_RESPONSE, monkeypatch)

    approver_headers, approver_id = _auth()
    requested = _request_approval(created["id"], headers, approver_id, "technical").json()
    assert requested["ai_recommendation"] == "Requires Clarification"

    responded = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "changes_requested", "comment": "Needs the OTP expiry window specified."},
        headers=approver_headers,
    ).json()
    assert responded["overrode_ai_recommendation"] is False


def test_override_uses_the_analysis_the_approval_was_actually_requested_against(monkeypatch):
    """Version-correctness: if the CR gets re-analyzed with a DIFFERENT
    recommendation after an approval was already requested, the override
    check must still use the analysis/version the approval was requested
    against - never whatever the CR's *current* analysis says now."""
    headers, _ = _auth()
    created = _create_change_request(headers)
    # version 1: AI says requires clarification
    _analyze(headers, created["id"], HIGH_RISK_CLARIFICATION_RESPONSE, monkeypatch)

    approver_headers, approver_id = _auth()
    requested = _request_approval(created["id"], headers, approver_id, "engineering_manager").json()
    assert requested["cr_version"] == 1
    assert requested["ai_recommendation"] == "Requires Clarification"

    # Edit the CR (bumps to version 2) and re-analyze with a completely
    # different recommendation. The pending approval above stays tied to
    # version 1's analysis (approval.cr_version doesn't move just because
    # the CR did - see app/services/approvals.py::is_approval_outdated).
    client.put(
        f"/api/change-requests/{created['id']}",
        json={"description": "Allow customers to log in using an OTP sent by SMS or email."},
        headers=headers,
    )
    _analyze(headers, created["id"], APPROVE_RESPONSE, monkeypatch)  # version 2: AI now says approve

    responded = client.post(
        f"/api/change-requests/{created['id']}/approvals/{requested['id']}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    ).json()
    # Still compared against version 1's "Requires Clarification" (what
    # this approval was actually requested against), not version 2's
    # "Approve".
    assert responded["ai_recommendation"] == "Requires Clarification"
    assert responded["overrode_ai_recommendation"] is True
