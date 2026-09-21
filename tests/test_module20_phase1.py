"""Verifies Module 20 Phase 1 (Version-Aware Reports - engine + endpoint):

  * GET /{id}/report (no `?version=`) now REFUSES to build a report when
    the change request has been edited since its last analysis - spec
    section 3 ("do not generate a misleading current report") - instead of
    the old behavior of silently mixing today's CR fields with yesterday's
    analysis. It returns 409 with the last-analyzed version named, so a
    caller can offer that as an explicit historical report instead of a
    dead end.
  * GET /{id}/report?version=N builds a report for that specific past
    version - CR fields reconstructed from that version's own snapshot,
    analysis (if any) that ran against exactly that version, never mixed
    with data from any other version - clearly labeled "HISTORICAL REPORT"
    in the PDF itself.
  * GET /{id}/report/versions lists every version with an is_current /
    has_analysis flag each, what the frontend's version picker reads from.
  * The new Approval Status section reflects real Approval rows (approved,
    rejected, pending), never invented data.

Following this project's established HTTP-only testing convention, all of
this is verified through the real endpoints - never by calling
report_generator.py's functions directly. Verifying the PDF's actual
CONTENT (not just that bytes came back) uses pypdf, already a project
dependency (see app/services/knowledge_chunker.py's own PDF parsing).

Run with (from backend/):  pytest ../tests
"""
import io
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.services.analysis_engine as analysis_engine
from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"m20p1-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module20 Phase1 Tester") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


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


_OK_AI_RESPONSE = {
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
    "effort": {
        "backend": "1 day",
        "frontend": "Insufficient information.",
        "testing": "0.5 day",
        "total": "1-2 developer-days",
    },
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


class _FakeProvider:
    def __init__(self, response_text=None):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _analyze(headers: dict, cr_id: int, monkeypatch, response_dict=None) -> dict:
    monkeypatch.setattr(
        analysis_engine, "get_ai_provider", lambda: _FakeProvider(json.dumps(response_dict or _OK_AI_RESPONSE))
    )
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return response.json()


def _edit(headers: dict, cr_id: int, **fields) -> dict:
    response = client.put(f"/api/change-requests/{cr_id}", json=fields, headers=headers)
    assert response.status_code == 200
    return response.json()


def _request_approval(cr_id: int, headers: dict, approver_id: int, approval_type: str = "security") -> dict:
    response = client.post(
        f"/api/change-requests/{cr_id}/approvals",
        json={"approval_type": approval_type, "approver_user_id": approver_id},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _respond_to_approval(cr_id: int, approval_id: int, headers: dict, status_value: str, comment=None) -> dict:
    body = {"status": status_value}
    if comment is not None:
        body["comment"] = comment
    response = client.post(
        f"/api/change-requests/{cr_id}/approvals/{approval_id}/respond", json=body, headers=headers
    )
    assert response.status_code == 200
    return response.json()


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    # A narrow table column (e.g. the Approval Status table's Comment
    # column) word-wraps a longer phrase onto more than one visual line -
    # correct, professional PDF rendering - but pypdf's extraction turns
    # that in-cell wrap into a hard newline rather than the space it
    # visually reads as. Collapsing all whitespace runs to single spaces
    # means an assertion checking a multi-word phrase verifies the real
    # wording, not incidental line breaks from the layout.
    return " ".join(raw.split())


# --- Current version, up to date ---------------------------------------------


def test_current_version_report_succeeds_and_contains_real_data(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Order Status Webhook Report Check")
    _analyze(headers, created["id"], monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "v1-analysis-report.pdf" in response.headers["content-disposition"]

    text = _pdf_text(response.content)
    assert f"CR-{created['id']:04d}" in text
    assert "Order Status Webhook Report Check" in text
    assert "Version 1" in text
    assert "HISTORICAL REPORT" not in text
    assert "Adds a webhook emitted on order status change." in text


def test_report_requires_authentication():
    headers, _ = _auth()
    created = _create_change_request(headers)
    response = client.get(f"/api/change-requests/{created['id']}/report")
    assert response.status_code == 401


# --- Version mismatch: the core Module 20 bugfix -----------------------------


def test_editing_after_analysis_returns_409_instead_of_a_misleading_report(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)

    _edit(headers, created["id"], description="A materially different description than what was analyzed.")

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["cr_version"] == 2
    assert detail["last_analyzed_version"] == 1
    assert detail["can_reanalyze"] is True


def test_never_analyzed_current_version_returns_409(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["last_analyzed_version"] is None


# --- Explicit historical reports ----------------------------------------------


def test_historical_report_for_the_last_analyzed_version_succeeds(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Historical Report Target")
    _analyze(headers, created["id"], monkeypatch)
    _edit(headers, created["id"], description="Edited after analysis - CR is now Version 2.")

    response = client.get(f"/api/change-requests/{created['id']}/report?version=1", headers=headers)
    assert response.status_code == 200
    assert "v1-historical-report.pdf" in response.headers["content-disposition"]

    text = _pdf_text(response.content)
    assert "HISTORICAL REPORT - Version 1" in text
    assert "Historical Report Target" in text
    # The analysis that ran against Version 1 is still shown...
    assert "Adds a webhook emitted on order status change." in text
    # ...and the description shown is Version 1's original text...
    assert "Emit a webhook event whenever an order's status changes on the POS." in text
    # ...never the live Version 2 edit.
    assert "Edited after analysis" not in text


def test_historical_report_for_a_never_analyzed_version_is_cr_only(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Never Analyzed Version One")
    _edit(headers, created["id"], description="Version 2 description.")
    _analyze(headers, created["id"], monkeypatch)  # analyzes Version 2, not Version 1

    response = client.get(f"/api/change-requests/{created['id']}/report?version=1", headers=headers)
    assert response.status_code == 200

    text = _pdf_text(response.content)
    assert "HISTORICAL REPORT - Version 1" in text
    assert "No analysis was performed against Version 1" in text
    # Version 2's edited description must never leak into the Version 1 report.
    assert "Version 2 description." not in text


def test_requesting_a_version_that_does_not_exist_returns_404():
    headers, _ = _auth()
    created = _create_change_request(headers)
    response = client.get(f"/api/change-requests/{created['id']}/report?version=99", headers=headers)
    assert response.status_code == 404


# --- Reportable-versions listing ----------------------------------------------


def test_list_reportable_versions(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)
    _edit(headers, created["id"], description="Bumps this CR to Version 2, unanalyzed.")

    response = client.get(f"/api/change-requests/{created['id']}/report/versions", headers=headers)
    assert response.status_code == 200
    versions = {row["version_number"]: row for row in response.json()}

    assert versions[1]["has_analysis"] is True
    assert versions[1]["is_current"] is False
    assert versions[2]["has_analysis"] is False
    assert versions[2]["is_current"] is True


# --- Approval Status section --------------------------------------------------


def test_report_shows_approved_approval(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)
    approver_headers, approver_id = _auth("Approver One")

    requested = _request_approval(created["id"], headers, approver_id, approval_type="technical")
    _respond_to_approval(created["id"], requested["id"], approver_headers, "approved")

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Approval Status" in text
    assert "Approver One" in text
    assert "Approved" in text


def test_report_shows_rejected_approval_with_comment(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)
    approver_headers, approver_id = _auth("Approver Two")

    requested = _request_approval(created["id"], headers, approver_id, approval_type="security")
    _respond_to_approval(
        created["id"], requested["id"], approver_headers, "rejected", comment="Needs a rate-limit design."
    )

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Rejected" in text
    assert "Needs a rate-limit design." in text


def test_report_shows_pending_approval_count(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)
    _, approver_id = _auth("Approver Three")

    _request_approval(created["id"], headers, approver_id, approval_type="qa")

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Pending" in text
    assert "Approver Three" in text


def test_report_with_no_approvals_says_so(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "No approvals have been requested" in text


# --- REPORT_GENERATED audit event ---------------------------------------------


def test_downloading_a_report_logs_a_report_generated_history_event(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    _analyze(headers, created["id"], monkeypatch)

    # Module 24: analyzing a change request already logs one
    # REPORT_GENERATED event on its own (see app/api/change_requests.py::
    # analyze_change_request - a report is never a separate, manual step),
    # so this counts before/after the download rather than asserting an
    # absolute total, to isolate what THIS test is actually about: that
    # downloading logs its own, independent event too.
    before = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    before_count = len([h for h in before if h["action"] == "report_generated"])

    response = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert response.status_code == 200

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    report_events = [h for h in history if h["action"] == "report_generated"]
    assert len(report_events) == before_count + 1
    assert all(event["new_value"] == "Version 1" for event in report_events)
