"""Module 17 Phase 7 - dedicated end-to-end version-sync pass for Test
Cases & Implementation Plan 2.0 (the module's final phase, per your own
7-section spec: "a dedicated sync test verifying CR Version -> Analysis
Version -> Requirements -> Test Cases -> Implementation Plan all remain
synchronized"). This is not incidental coverage from earlier phases - it
walks the FULL lifecycle in one continuous story and checks every layer
agrees with every other layer at each step, mirroring
test_module15_phase7_security.py / test_module16_phase7_security.py's own
"a dedicated audit, not just leftover assertions" approach for this
module's own closing phase:

  * Right after the first /analyze: CR v1, Analysis v1, every test case/
    task reports analysis_version == 1 and is_outdated == False, and their
    requirement_references correctly point at THIS analysis's own
    requirement rows.
  * Editing the change request (PUT) bumps only the CR's own version - the
    analysis row itself is untouched - but GET .../analysis immediately
    starts reporting is_outdated == True, and that staleness propagates to
    every test case and task's own is_outdated exactly the same way it
    already does for knowledge_evidence (Module 16) and repository
    findings (Module 15). analysis_version does NOT change just because
    the CR did - it still correctly names the analysis's own version, not
    the CR's current one.
  * A human can still edit a test case/task while its parent analysis is
    outdated (editing is never blocked by staleness), and the edit's own
    audit-trail row is stamped with the CR's version AT THE TIME OF THE
    EDIT (2, since the CR was edited first) - proving the audit trail's
    version_number and the analysis's own change_request_version are two
    independent, correctly-tracked numbers, never conflated.
  * Re-analyzing (POST /analyze again) creates a brand-new Analysis tied
    to the CR's now-current version (2) with its own fresh requirements -
    every test case/task on THIS new analysis reports analysis_version
    == 2, is_outdated == False again, and requirement_references naming
    only this new analysis's own requirement id(s) - never a stale
    reference back to the previous analysis's now-superseded requirement
    row, even though both analyses happen to describe similar content.
  * The previous (now-superseded) analysis's own edited test case is
    never resurrected onto the new analysis - GET .../analysis (latest)
    never returns a test case whose edited_by was set on the old
    analysis; the edit lives only in that old analysis's own child rows
    and in the permanent history trail, exactly the "never presented as
    current once the CR has moved to a newer version" rule from the
    Module 12 architecture lock.
  * The full history trail, read once at the end, contains both the
    earlier CR field edit and the test-case edit, each correctly stamped
    with its own version_number, in the order they actually happened -
    a real end-to-end audit story, not just isolated per-action checks.

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) - no real network call, matching this app's established
testing pattern. The provider returns a slightly different requirement
wording on its second call, so the two analyses genuinely have distinct
requirement rows (never the same row reused across versions).

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
    return f"m17p7-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase7 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers) -> dict:
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


def _analysis_json(requirement_text: str, test_case_title: str, task_title: str) -> dict:
    """One shared shape, but with the requirement/test-case/task wording
    parameterized - the second analyze() call passes genuinely different
    text so the two analyses' own child rows are never accidentally
    identical, which would make "does analysis 2 reference analysis 2's
    own requirement, not analysis 1's" impossible to tell apart."""
    return {
        "summary": "Adds OTP-based verification to checkout.",
        "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
        "requirements": [
            {
                "category": "functional",
                "description": requirement_text,
                "priority": "high",
            }
        ],
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
                "title": test_case_title,
                "type": "security",
                "priority": "high",
                "description": f"Verify {requirement_text.lower()}",
                "preconditions": "A one-time password has been sent by SMS during checkout.",
                "steps": ["Wait 5 minutes", "Submit the one-time password"],
                "expected_result": "The expired code is rejected with a clear error.",
            }
        ],
        "implementation_plan": [
            {
                "task": task_title,
                "description": f"Implements: {requirement_text}",
                "component": "Backend",
                "priority": "high",
                "estimated_effort": "2 days",
                "dependencies": None,
                "owner_suggestion": "technical_lead",
            }
        ],
        "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
    }


class _ScriptedProvider:
    """Returns _RESPONSES[call_index] in order, one per call to
    complete() - lets a single test drive two distinct /analyze runs
    without a second monkeypatch."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        response = self._responses[min(self._call_count, len(self._responses) - 1)]
        self._call_count += 1
        return json.dumps(response)


def test_full_lifecycle_stays_synchronized_across_edit_and_reanalysis(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)

    provider = _ScriptedProvider(
        [
            _analysis_json(
                "Customers must receive a one-time password by SMS to verify their identity during checkout.",
                "OTP code expires after 5 minutes",
                "Add OTP generation endpoint",
            ),
            _analysis_json(
                "Customers must be able to request a fresh one-time password if the first one expired.",
                "OTP code can be resent after expiry",
                "Add OTP resend endpoint",
            ),
        ]
    )
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)

    # --- Step 1: first analysis. CR v1, Analysis v1, everything fresh. ---
    first = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert first.status_code == 201
    first_body = first.json()
    first_requirement_id = first_body["requirements"][0]["id"]
    first_test_case = first_body["test_cases"][0]
    first_task = first_body["implementation_tasks"][0]

    assert first_body["is_outdated"] is False
    assert first_test_case["analysis_version"] == 1
    assert first_test_case["is_outdated"] is False
    assert first_test_case["requirement_references"] == [f"REQ-{first_requirement_id}"]
    assert first_task["analysis_version"] == 1
    assert first_task["is_outdated"] is False
    assert first_task["requirement_references"] == [f"REQ-{first_requirement_id}"]

    # --- Step 2: edit the CR. Only the CR's own version moves. ---
    edit_response = client.put(
        f"/api/change-requests/{created['id']}",
        json={"priority": "high"},
        headers=headers,
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["new_version"] == 2

    # The analysis itself didn't change, but is now stale relative to the
    # CR's new version - and that staleness must be visible on every test
    # case/task, not just on the analysis header.
    stale = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert stale.status_code == 200
    stale_body = stale.json()
    assert stale_body["is_outdated"] is True
    stale_test_case = stale_body["test_cases"][0]
    stale_task = stale_body["implementation_tasks"][0]
    assert stale_test_case["is_outdated"] is True
    assert stale_task["is_outdated"] is True
    # analysis_version still correctly names the ANALYSIS's own version -
    # it must never drift just because the CR moved on.
    assert stale_test_case["analysis_version"] == 1
    assert stale_task["analysis_version"] == 1

    # --- Step 3: a human can still edit a test case while it's outdated. ---
    edit_test_case = client.patch(
        f"/api/change-requests/{created['id']}/test-cases/{first_test_case['id']}",
        json={"title": "OTP code is definitively rejected once expired", "reason": "Clarified wording."},
        headers=headers,
    )
    assert edit_test_case.status_code == 200
    edited_body = edit_test_case.json()
    assert edited_body["edited_by"] is not None
    # Editing doesn't secretly "fix" staleness - it's still the same old
    # (now-superseded) analysis underneath.
    assert edited_body["is_outdated"] is True

    # --- Step 4: re-analyze. Brand-new Analysis tied to CR v2. ---
    second = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert second.status_code == 201
    second_body = second.json()
    second_requirement_id = second_body["requirements"][0]["id"]
    second_test_case = second_body["test_cases"][0]
    second_task = second_body["implementation_tasks"][0]

    assert second_requirement_id != first_requirement_id
    assert second_body["is_outdated"] is False
    assert second_test_case["analysis_version"] == 2
    assert second_test_case["is_outdated"] is False
    # References only this new analysis's own requirement - never the old,
    # now-superseded one, even though both requirements are about OTP.
    assert second_test_case["requirement_references"] == [f"REQ-{second_requirement_id}"]
    assert second_task["requirement_references"] == [f"REQ-{second_requirement_id}"]

    # --- Step 5: the old analysis's edit is never resurrected as current. ---
    latest = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert latest.status_code == 200
    latest_test_case_ids = {tc["id"] for tc in latest.json()["test_cases"]}
    assert first_test_case["id"] not in latest_test_case_ids
    assert second_test_case["id"] in latest_test_case_ids
    # The new analysis's own test case was never touched by a human -
    # it's a fresh AI-written row, not the edited one from before.
    assert latest.json()["test_cases"][0]["edited_by"] is None

    # --- Step 6: the full history trail agrees with both events, each
    # correctly stamped with the CR version in effect at that moment. ---
    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers)
    assert history.status_code == 200
    events = history.json()

    priority_edits = [h for h in events if h["field_name"] == "priority"]
    assert len(priority_edits) == 1
    assert priority_edits[0]["version_number"] == 2

    test_case_edits = [h for h in events if h["action"] == "test_case_edited"]
    assert len(test_case_edits) == 1
    # The edit happened after the CR's own version-2 bump, so the audit
    # row correctly reflects version 2 - not version 1 (when the analysis
    # it belongs to was created) and not some future version.
    assert test_case_edits[0]["version_number"] == 2
    assert "OTP code expires after 5 minutes" in test_case_edits[0]["old_value"]
    assert "OTP code is definitively rejected once expired" in test_case_edits[0]["new_value"]

    # The field edit happened before the test-case edit in real time -
    # confirm the trail's own ordering (newest first, matching every other
    # history endpoint in this app) agrees with that.
    priority_index = events.index(priority_edits[0])
    test_case_index = events.index(test_case_edits[0])
    assert test_case_index < priority_index
