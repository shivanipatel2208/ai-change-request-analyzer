"""Verifies Module 22 (Final Integration, Security & Quality) spec sections
1 and 2: one real, continuous walk through the ENTIRE lifecycle this app
supports, through the real HTTP API only (this project's established
testing convention - never by calling internal functions directly), with a
version-integrity assertion at every step that produces a version-scoped
artifact:

  Register/Login -> Create CR -> Edit CR -> Version created -> Audit
  recorded -> AI analysis -> Impact analysis -> Repository analysis -> RAG
  evidence -> Risk/security -> Test cases -> Implementation plan ->
  Assignment -> Approval request -> Notification -> Review -> Approval ->
  Implementation -> Validation -> Closure -> Report

This single test also happens to be the first real exercise of two Module
22 fixes made alongside it:

  * the new approval-bypass gate in change_status (app/api/change_requests.py) -
    the test explicitly proves a change request CANNOT be marked Approved
    while an approval it requested is still Pending (409), then proves it
    CAN once that approval is resolved.
  * the new recommended_approvals.is_outdated flag (app/schemas/approval.py) -
    the test edits the CR after its first analysis and confirms the
    recommendation the endpoint returns is flagged outdated, then confirms
    it clears again after a fresh analysis.

Two AI-provider-shaped things are monkeypatched, matching this project's
own established conventions for each: `analysis_engine.get_ai_provider`
for the main analysis completion call (same pattern as
tests/test_module20_phase1.py's own _FakeProvider), and
`knowledge_embeddings.get_ai_provider` for embeddings (same pattern as
tests/test_module16_phase3.py's own _FakeEmbeddingProvider, keyed off a
shared keyword instead of a real embedding model) - so the knowledge-base
evidence step is exercised against a REAL uploaded document and REAL
computed chunk embeddings, not a hand-built fake evidence row.

Run with (from backend/):  pytest ../tests
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

import io

from fastapi.testclient import TestClient

import app.services.analysis_engine as analysis_engine
import app.services.knowledge_embeddings as knowledge_embeddings
from app.main import app

client = TestClient(app)

# --- Shared fixtures / helpers ---------------------------------------------

_KEYWORD = "loyaltyreconciliation"  # deliberately unusual - avoids accidentally
# matching content left behind by any other test file sharing the same
# database, since every test in this suite runs against one throwaway
# sqlite file for the whole session (see tests/conftest.py).


def _unique_email(tag: str = "m22") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@alight.com"


def _register(name: str) -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


_AI_RESPONSE = {
    "summary": f"Reconciles {_KEYWORD} nightly between the POS and the loyalty service.",
    "classification": {"category": "Integration", "confidence": 0.82, "reason": "New scheduled reconciliation job."},
    "requirements": [
        {
            "category": "functional",
            "description": f"Nightly job reconciles {_KEYWORD} balances between systems.",
            "priority": "high",
        },
    ],
    "affected_components": [
        {
            "name": "Loyalty Service",
            "type": "backend",
            "impact_level": "medium",
            "reason": "New scheduled reconciliation job reads and writes loyalty balances.",
            "confidence": 75,
        }
    ],
    "dependencies": [],
    "risks": [
        {
            "category": "data",
            "description": "A failed reconciliation run could double-count loyalty points.",
            "severity": "high",
            "probability": 0.3,
            "score": 60,
            "mitigation": "Make the job idempotent and log every adjustment made.",
        }
    ],
    "security_analysis": {"concerns": [], "summary": "No new external attack surface identified."},
    "complexity": {"level": "medium", "reasoning": "New scheduled job plus a reconciliation algorithm."},
    "effort": {
        "backend": "3 days",
        "frontend": "Insufficient information.",
        "testing": "1 day",
        "total": "4-5 developer-days",
    },
    "missing_information": [],
    "test_cases": [
        {
            "id": "TC-001",
            "title": f"{_KEYWORD} reconciliation corrects a mismatch",
            "type": "integration",
            "priority": "high",
            "description": "Introduce a loyalty balance mismatch and run the nightly job.",
            "expected_result": "Balances match across both systems after the job runs.",
        }
    ],
    "implementation_plan": [
        {
            "task": "Add nightly reconciliation job",
            "description": "Scheduled job that reconciles loyalty balances and logs adjustments.",
            "component": "Loyalty Service",
            "priority": "high",
            "estimated_effort": "2 days",
        }
    ],
    "recommendation": {"decision": "approve_with_conditions", "reasoning": "Sound approach; needs idempotency review."},
}


class _FakeProvider:
    def __init__(self, response_text: str):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _keyword_vector(text: str) -> list[float]:
    """A minimal, deterministic stand-in for a real embedding model (same
    approach as tests/test_module16_phase3.py's own _keyword_vector) - 1.0
    in every dimension if the shared keyword is present, 0.0 otherwise.
    Real enough to exercise cosine-similarity ranking and the min_score
    filter in app/services/knowledge_embeddings.py without a real AI call.

    Deliberately 8-dimensional, not 1: this suite runs every test file
    against one shared, persistent database (tests/conftest.py), so by the
    time this test runs, many other documents' chunks already carry their
    OWN test file's single-dimension [0.0]/[1.0] fake embedding from an
    unrelated keyword. _cosine_similarity() scores two vectors of
    different lengths as 0.0 - see app/services/knowledge_embeddings.py -
    so an 8-dimensional vector here can never tie with (or be beaten by) a
    leftover 1-dimensional vector from a different test file, no matter
    how many prior runs have piled up. A same-length collision was
    exactly what caused this test to intermittently retrieve some other
    test's document as "evidence" instead of the one it just uploaded."""
    hit = 1.0 if _KEYWORD in text.lower() else 0.0
    return [hit] * 8


class _FakeEmbeddingProvider:
    def is_configured(self) -> bool:
        return True

    def embed(self, texts, *, timeout=None):
        return [_keyword_vector(t) for t in texts]


def test_full_lifecycle_end_to_end_with_version_integrity(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())

    # --- Register/Login -----------------------------------------------
    creator_headers, creator_id = _register("E2E Creator")
    approver_headers, approver_id = _register("E2E Approver")

    login = client.post(
        "/auth/login",
        json={"email": _unique_email(), "password": "irrelevant"},  # sanity: unknown login still clean 401
    )
    assert login.status_code == 401

    # --- Create CR ------------------------------------------------------
    created = client.post(
        "/api/change-requests",
        json={
            "title": f"Nightly {_KEYWORD} reconciliation job",
            "description": f"Add a nightly job that reconciles {_KEYWORD} balances between the POS and the loyalty service.",
            "business_objective": "Keep loyalty balances accurate across systems.",
            "priority": "medium",
            "requested_by": "Casey Alight",
            "target_system": "Loyalty Service",
        },
        headers=creator_headers,
    ).json()
    cr_id = created["id"]
    assert created["status"] == "pending_analysis"
    assert created["current_version"] == 1

    # --- Upload + embed a real knowledge-base document (for RAG evidence) ---
    upload = client.post(
        "/api/knowledge/documents",
        headers=creator_headers,
        files={
            "file": (
                "loyalty-reconciliation-notes.md",
                io.BytesIO(
                    f"# Loyalty Reconciliation\n\nThe {_KEYWORD} process compares point balances "
                    "nightly and reports mismatches for manual review.".encode()
                ),
                "text/markdown",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    embed_response = client.post(f"/api/knowledge/documents/{document_id}/embed", headers=creator_headers)
    assert embed_response.status_code == 200, embed_response.text

    # --- Repository analysis (real scan of this project's own repo) -------
    scan_response = client.post("/api/repository/scan", headers=creator_headers)
    assert scan_response.status_code in (200, 201), scan_response.text

    # --- AI analysis (version 1) -----------------------------------------
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeProvider(json.dumps(_AI_RESPONSE)))
    analyze_response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=creator_headers)
    assert analyze_response.status_code == 201, analyze_response.text
    analysis_v1 = analyze_response.json()
    analysis_v1_id = analysis_v1["id"]

    # Version integrity: this analysis, and everything it produced, is
    # tagged with version 1 - the CR hasn't been edited yet.
    assert analysis_v1["change_request_version"] == 1
    assert analysis_v1["is_outdated"] is False
    assert len(analysis_v1["requirements"]) >= 1
    assert len(analysis_v1["risks"]) >= 1
    assert len(analysis_v1["impact_assessments"]) >= 7  # the 7 fixed lenses, always filled
    assert len(analysis_v1["security_findings"]) >= 9  # the 9 fixed lenses, always filled
    assert len(analysis_v1["test_cases"]) >= 1
    assert len(analysis_v1["implementation_tasks"]) >= 1
    for tc in analysis_v1["test_cases"]:
        assert tc["analysis_id"] == analysis_v1_id
    for task in analysis_v1["implementation_tasks"]:
        assert task["analysis_id"] == analysis_v1_id
    for req in analysis_v1["requirements"]:
        assert req["analysis_id"] == analysis_v1_id

    # RAG evidence: the uploaded document should have been retrieved and
    # recorded as grounding context for this exact analysis (Module 16
    # Phase 4/5) - version-tagged the same way as every other artifact.
    assert len(analysis_v1["knowledge_evidence"]) >= 1, "expected the uploaded document to be retrieved as evidence"
    evidence = analysis_v1["knowledge_evidence"][0]
    assert evidence["document_id"] == document_id
    assert evidence["is_outdated"] is False

    change_request = client.get(f"/api/change-requests/{cr_id}", headers=creator_headers).json()
    assert change_request["status"] == "analyzed"  # first analysis auto-advances from Pending Analysis
    assert change_request["is_analysis_outdated"] is False

    # Repository analysis: whatever the real scan/matcher found (if
    # anything - matching depends on this repo's actual file names, which
    # this test doesn't try to force) must be tagged with the CR's current
    # version, never a mismatched one.
    findings_v1 = client.get(f"/api/change-requests/{cr_id}/repository-findings", headers=creator_headers)
    assert findings_v1.status_code == 200
    for finding in findings_v1.json():
        assert finding["change_request_version"] == 1
        assert finding["analysis_id"] == analysis_v1_id

    # Recommended approvals should exist and not be flagged outdated yet.
    recommended_v1 = client.get(f"/api/change-requests/{cr_id}/approvals/recommended", headers=creator_headers).json()
    assert recommended_v1, "a medium-complexity, high-severity-risk CR should recommend at least one approval type"
    assert all(r["is_outdated"] is False for r in recommended_v1)

    # --- Edit CR -> new version + audit -----------------------------------
    edited = client.put(
        f"/api/change-requests/{cr_id}",
        json={"description": change_request["description"] + " Also covers a manual reconciliation report."},
        headers=creator_headers,
    )
    assert edited.status_code == 200, edited.text
    edited_body = edited.json()
    # PUT returns {change_request, changes, new_version} - not a flat CR
    # object - so the updated version lives at both of these paths.
    assert edited_body["new_version"] == 2
    assert edited_body["change_request"]["current_version"] == 2

    versions = client.get(f"/api/change-requests/{cr_id}/versions", headers=creator_headers).json()
    assert {v["version_number"] for v in versions} >= {1, 2}

    history = client.get(f"/api/change-requests/{cr_id}/history", headers=creator_headers).json()
    field_changed_events = [h for h in history if h["action"] == "field_changed"]
    assert len(field_changed_events) >= 1
    assert field_changed_events[0]["user_id"] == creator_id  # audit correctness: real actor, not spoofable

    # Module 22 fix in action: the analysis is now outdated (CR moved to
    # version 2, analysis #1 still says version 1), and recommended
    # approvals now say so too - this is the exact gap this module closed.
    stale_cr = client.get(f"/api/change-requests/{cr_id}", headers=creator_headers).json()
    assert stale_cr["is_analysis_outdated"] is True
    recommended_stale = client.get(
        f"/api/change-requests/{cr_id}/approvals/recommended", headers=creator_headers
    ).json()
    assert recommended_stale and all(r["is_outdated"] is True for r in recommended_stale)

    # Downloading the CURRENT report is correctly refused while the
    # analysis is outdated (Module 20's own fix, still holding).
    stale_report = client.get(f"/api/change-requests/{cr_id}/report", headers=creator_headers)
    assert stale_report.status_code == 409

    # --- Re-analyze (version 2) --------------------------------------------
    reanalyze_response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=creator_headers)
    assert reanalyze_response.status_code == 201, reanalyze_response.text
    analysis_v2 = reanalyze_response.json()
    analysis_v2_id = analysis_v2["id"]
    assert analysis_v2_id != analysis_v1_id
    assert analysis_v2["change_request_version"] == 2
    assert analysis_v2["is_outdated"] is False

    fresh_cr = client.get(f"/api/change-requests/{cr_id}", headers=creator_headers).json()
    assert fresh_cr["is_analysis_outdated"] is False

    recommended_fresh = client.get(
        f"/api/change-requests/{cr_id}/approvals/recommended", headers=creator_headers
    ).json()
    assert recommended_fresh and all(r["is_outdated"] is False for r in recommended_fresh)

    # --- Review (Requirements + Security findings) --------------------------
    requirement_id = analysis_v2["requirements"][0]["id"]
    review = client.patch(
        f"/api/change-requests/{cr_id}/requirements/{requirement_id}/review",
        json={"review_status": "confirmed"},
        headers=creator_headers,
    )
    assert review.status_code == 200, review.text
    assert review.json()["reviewed_by"] == creator_id

    security_finding_id = analysis_v2["security_findings"][0]["id"]
    finding_update = client.patch(
        f"/api/change-requests/{cr_id}/security-findings/{security_finding_id}/status",
        json={"status": "acknowledged"},
        headers=creator_headers,
    )
    assert finding_update.status_code == 200, finding_update.text
    assert finding_update.json()["status"] == "acknowledged"

    reviewed_history = client.get(f"/api/change-requests/{cr_id}/history", headers=creator_headers).json()
    assert any(h["action"] == "requirement_reviewed" for h in reviewed_history)

    # --- Assignment -----------------------------------------------------
    assignment = client.post(
        f"/api/change-requests/{cr_id}/assignments",
        json={"user_id": approver_id, "role": "reviewer"},
        headers=creator_headers,
    )
    assert assignment.status_code == 201, assignment.text

    # --- Status: Analyzed -> In Review -> Approval Required -----------------
    assert client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "in_review"}, headers=creator_headers
    ).status_code == 200
    assert client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "approval_required"}, headers=creator_headers
    ).status_code == 200

    # --- Approval request -> Notification ------------------------------------
    approval_request = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": "technical", "approver_user_id": approver_id},
        headers=creator_headers,
    )
    assert approval_request.status_code == 201, approval_request.text
    approval_id = approval_request.json()["id"]

    approver_notifications = client.get("/api/notifications", headers=approver_headers).json()
    assert any(
        n.get("type") == "approval_requested" and n.get("change_request_id") == cr_id
        for n in approver_notifications
    ), "the tagged approver should have been notified of the approval request"

    # --- Approval bypass gate (Module 22 fix) - proven both ways -----------
    bypass_attempt = client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "approved"}, headers=creator_headers
    )
    assert bypass_attempt.status_code == 409, (
        "a change request must not be approvable while an approval it requested is still Pending"
    )

    # A non-approver cannot respond on the approver's behalf.
    unauthorized_respond = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond",
        json={"status": "approved"},
        headers=creator_headers,
    )
    assert unauthorized_respond.status_code == 403

    # --- Approval (the real approver responds) -------------------------------
    respond = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond",
        json={"status": "approved"},
        headers=approver_headers,
    )
    assert respond.status_code == 200, respond.text

    requester_notifications = client.get("/api/notifications", headers=creator_headers).json()
    assert any(n.get("type") == "approved" and n.get("change_request_id") == cr_id for n in requester_notifications)

    # Now that the only requested approval is resolved, the same
    # transition that was blocked above succeeds.
    approved = client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "approved"}, headers=creator_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    # --- Implementation -> Validation -> Closure ------------------------------
    for target in ("implementation_planned", "in_progress", "implemented", "validated", "closed"):
        step = client.put(f"/api/change-requests/{cr_id}/status", json={"status": target}, headers=creator_headers)
        assert step.status_code == 200, f"transition to {target} failed: {step.text}"
        assert step.json()["status"] == target

    # An invalid transition from a terminal state is still rejected.
    dead_end = client.put(
        f"/api/change-requests/{cr_id}/status", json={"status": "in_progress"}, headers=creator_headers
    )
    assert dead_end.status_code == 422

    # --- Report (final, current version) ---------------------------------
    final_report = client.get(f"/api/change-requests/{cr_id}/report", headers=creator_headers)
    assert final_report.status_code == 200
    assert final_report.headers["content-type"] == "application/pdf"
    assert len(final_report.content) > 1000  # a real, non-trivial PDF, not an empty stub

    final_history = client.get(f"/api/change-requests/{cr_id}/history", headers=creator_headers).json()
    assert any(h["action"] == "report_generated" for h in final_history)
    status_changed_events = [h for h in final_history if h["action"] == "status_changed"]
    assert len(status_changed_events) >= 7  # in_review, approval_required, approved, +5 implementation/close steps
    assert all(h["user_id"] == creator_id for h in status_changed_events)  # every change made by the real actor

    # --- Audit integrity: history has no write route at all -----------------
    # app/api/change_requests.py registers GET .../history only - there is
    # no PUT/PATCH/DELETE path for it to even attempt, so this confirms
    # the negative directly against the running app rather than asserting
    # something about code this test can't otherwise observe.
    assert client.put(f"/api/change-requests/{cr_id}/history", headers=creator_headers).status_code == 405
    assert client.delete(f"/api/change-requests/{cr_id}/history", headers=creator_headers).status_code == 405
