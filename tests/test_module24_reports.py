"""Verifies Module 24 (Reports section):

  * A report is never a separate, manually-generated thing - the instant an
    analysis completes for a change request's current version, that
    automatically becomes a REPORT_GENERATED event and the report shows up
    on the Reports page with no extra action (confirmed with the project
    owner: "the reports should not be generated separately, once the
    analysis is complete, it should reflect in the reports section"). This
    file tests that behaviour directly - it never posts to a "generate"
    endpoint, because none exists.
  * GET /api/reports, GET /api/reports/stats, GET /api/reports/{id},
    GET /api/reports/{id}/download, and
    GET /api/change-requests/{id}/reports all exist and work against real
    data - never hard-coded numbers.
  * Reports are NOT a separate database table (see
    app/services/report_registry.py): the automatic event recorded when
    analysis completes and the pre-existing Analysis Dashboard "Download
    Report" button both feed the exact same event stream, and collapse into
    the SAME reports-list row when they're for the same change request +
    version - this is the core architecture claim of this module and gets
    its own test below.
  * An unanalyzed change request has no report at all - never a fabricated
    or misleading one. Editing a change request after it was analyzed
    leaves its old report as historical/outdated rather than mutating it or
    silently generating a new "current" one.
  * Historical reports (spec section 11) are never mixed with other
    versions' data.
  * Search, filters, and permissions all work against real records.

Following this project's established HTTP-only testing convention (see
tests/test_module20_phase1.py), everything here goes through the real
endpoints - never by calling report_registry.py's functions directly.

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
    return f"m24-{uuid.uuid4().hex[:10]}@alight.com"


def _auth(name: str = "Module24 Reports Tester") -> tuple[dict, int]:
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
        "title": "Add loyalty points expiry job",
        "description": "Run a nightly job that expires loyalty points older than 12 months.",
        "business_objective": "Keep the loyalty ledger accurate and bounded in size.",
        "priority": "medium",
        "requested_by": "Casey Alight",
        "target_system": "Loyalty Service",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


_OK_AI_RESPONSE = {
    "summary": "Adds a nightly job that expires old loyalty points.",
    "classification": {"category": "Infrastructure", "confidence": 0.75, "reason": "New scheduled job."},
    "requirements": [
        {"category": "functional", "description": "Expire points older than 12 months nightly.", "priority": "high"},
    ],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_analysis": {"concerns": [], "summary": "No new attack surface identified."},
    "complexity": {"level": "low", "reasoning": "Single new scheduled job."},
    "effort": {
        "backend": "1 day",
        "frontend": "Insufficient information.",
        "testing": "0.5 day",
        "total": "1-2 developer-days",
    },
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
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
    """Runs the real /analyze endpoint - this is now also the only way a
    report ever comes into existence (see the module docstring above), so
    every test that needs a report just calls this, never a "generate"
    endpoint."""
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


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


# --- Reports appear automatically the moment analysis completes ---------------


def test_report_appears_automatically_after_analysis(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Report Module Basic Flow CR")

    before_stats = client.get("/api/reports/stats", headers=headers).json()

    # No "generate" call anywhere - analyzing IS what makes the report exist.
    _analyze(headers, created["id"], monkeypatch)

    after_stats = client.get("/api/reports/stats", headers=headers).json()
    assert after_stats["total_reports"] == before_stats["total_reports"] + 1
    assert after_stats["change_requests_with_reports"] >= before_stats["change_requests_with_reports"] + 1

    listing = client.get("/api/reports", headers=headers).json()
    matching = [item for item in listing["items"] if item["change_request_id"] == created["id"]]
    assert len(matching) == 1
    report = matching[0]
    assert report["version"] == 1
    assert report["has_analysis"] is True
    assert report["is_current_version"] is True
    assert report["is_historical_pull"] is False

    detail = client.get(f"/api/reports/{report['report_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["change_request_title"] == "Report Module Basic Flow CR"

    download = client.get(f"/api/reports/{report['report_id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    text = _pdf_text(download.content)
    assert "Report Module Basic Flow CR" in text
    assert "Adds a nightly job that expires old loyalty points." in text


def test_reports_for_change_request_endpoint(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Per-CR Reports Listing")
    _analyze(headers, created["id"], monkeypatch)

    response = client.get(f"/api/change-requests/{created['id']}/reports", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["change_request_id"] == created["id"]


def test_reanalyzing_the_same_version_does_not_duplicate_the_report(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Re-run Analysis Without Editing CR")
    _analyze(headers, created["id"], monkeypatch)
    _analyze(headers, created["id"], monkeypatch)  # re-analyzed, but still version 1

    response = client.get(f"/api/change-requests/{created['id']}/reports", headers=headers)
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["pull_count"] == 2


# --- No report exists before analysis; edits never mutate an old report -------


def test_unanalyzed_change_request_has_no_report(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Never Analyzed CR")

    response = client.get(f"/api/change-requests/{created['id']}/reports", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_editing_after_analysis_leaves_old_report_outdated_with_no_new_one(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Edited After Analysis CR")
    _analyze(headers, created["id"], monkeypatch)
    _edit(headers, created["id"], description="A materially different description than before, changing scope.")

    response = client.get(f"/api/change-requests/{created['id']}/reports", headers=headers)
    body = response.json()
    # Editing alone never generates a report for the new version - only a
    # completed analysis does - so the CR still has exactly the one report,
    # now flagged as no longer matching the CR's current version.
    assert body["total"] == 1
    assert body["items"][0]["version"] == 1
    assert body["items"][0]["is_current_version"] is False


# --- Historical reports (spec section 11) -------------------------------------


def test_historical_report_never_mixes_versions(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Historical Report CR")
    _analyze(headers, created["id"], monkeypatch)
    _edit(headers, created["id"], description="A materially different description, now on version two.")
    _analyze(headers, created["id"], monkeypatch)

    listing = client.get(f"/api/change-requests/{created['id']}/reports", headers=headers).json()
    by_version = {item["version"]: item for item in listing["items"]}
    assert set(by_version) == {1, 2}

    report_v1 = by_version[1]
    assert report_v1["is_current_version"] is False

    report_v2 = by_version[2]
    assert report_v2["is_current_version"] is True

    # Two distinct rows - never collapsed into one just because they're the
    # same change request.
    assert report_v1["report_id"] != report_v2["report_id"]

    download_v1 = client.get(f"/api/reports/{report_v1['report_id']}/download", headers=headers)
    text_v1 = _pdf_text(download_v1.content)
    assert "HISTORICAL REPORT" in text_v1


# --- No duplicate system: the automatic analysis-time event and the ---
# --- long-standing Analysis Dashboard download converge on the same row -------


def test_auto_generated_event_and_dashboard_download_share_one_row(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Shared Audit Trail CR")

    # Analyzing is itself the only "generate" step there is - already
    # records one REPORT_GENERATED event.
    _analyze(headers, created["id"], monkeypatch)

    listing = client.get("/api/reports", headers=headers).json()
    matching = [item for item in listing["items"] if item["change_request_id"] == created["id"]]
    assert len(matching) == 1
    assert matching[0]["pull_count"] == 1

    # ...pulled again via the long-standing Analysis Dashboard "Download
    # Report" button - same (change request, version) pair, so it's still
    # exactly one row, now with pull_count 2, not a second report entry.
    old_endpoint = client.get(f"/api/change-requests/{created['id']}/report", headers=headers)
    assert old_endpoint.status_code == 200

    listing_after = client.get("/api/reports", headers=headers).json()
    matching_after = [item for item in listing_after["items"] if item["change_request_id"] == created["id"]]
    assert len(matching_after) == 1
    assert matching_after[0]["pull_count"] == 2


# --- Search / filters -----------------------------------------------------------


def test_search_and_filters(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Searchable Widget Rollout CR")
    _analyze(headers, created["id"], monkeypatch)

    by_title = client.get("/api/reports", params={"search": "Searchable Widget"}, headers=headers).json()
    assert any(item["change_request_id"] == created["id"] for item in by_title["items"])

    by_cr_code = client.get(
        "/api/reports", params={"search": f"CR-{created['id']:04d}"}, headers=headers
    ).json()
    assert any(item["change_request_id"] == created["id"] for item in by_cr_code["items"])

    by_version = client.get("/api/reports", params={"version": 1}, headers=headers).json()
    assert all(item["version"] == 1 for item in by_version["items"])

    by_status = client.get("/api/reports", params={"status": "analyzed"}, headers=headers).json()
    assert all(item["cr_status"] == "analyzed" for item in by_status["items"])

    no_match = client.get(
        "/api/reports", params={"search": "definitely-not-a-real-change-request-xyz"}, headers=headers
    ).json()
    assert no_match["total"] == 0


# --- Permissions ------------------------------------------------------------


def test_reports_endpoints_require_authentication(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers, title="Auth Required CR")
    _analyze(headers, created["id"], monkeypatch)
    listing = client.get("/api/reports", headers=headers).json()
    report_id = next(item["report_id"] for item in listing["items"] if item["change_request_id"] == created["id"])

    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports/stats").status_code == 401
    assert client.get(f"/api/reports/{report_id}").status_code == 401
    assert client.get(f"/api/reports/{report_id}/download").status_code == 401
    assert client.get(f"/api/change-requests/{created['id']}/reports").status_code == 401


def test_unknown_report_id_is_404(monkeypatch):
    headers, _ = _auth()
    assert client.get("/api/reports/999999999", headers=headers).status_code == 404
    assert client.get("/api/reports/999999999/download", headers=headers).status_code == 404


# --- Empty state --------------------------------------------------------------


def test_empty_reports_list_is_not_an_error(monkeypatch):
    headers, _ = _auth()
    # A brand-new account with no change requests of its own yet still gets
    # a clean, valid (possibly non-empty, since other tests share the same
    # database - see tests/conftest.py) response, never an error.
    response = client.get("/api/reports", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)
    assert body["total"] == len(body["items"])
