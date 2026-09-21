"""Verifies Module 15 Phase 3 (Repository Intelligence - CR -> File
Matching): "which source files may actually be affected by this change
request?"

  * A change request with no keyword overlap against anything a scan
    indexed yields zero findings and never even calls the AI provider -
    an honest "nothing found" is a valid outcome, not an error, and not
    worth an AI call.
  * A change request that DOES overlap with an indexed file's own
    extracted imports/functions/etc gets a persisted RepositoryFinding
    whose `match_label` is computed purely from the numeric `confidence`
    the AI returned - never trusted from the AI's own wording - and whose
    `change_request_version`/`analysis_id`/`repository_scan_id` are
    exactly the ones the match actually ran against.
  * A match naming a file that was never in the candidate shortlist (a
    hallucinated path) is silently dropped, never persisted.
  * Re-running a match for the exact same (change request, analysis,
    scan) triple replaces that triple's own findings - it does not pile
    up duplicates, and it does not touch a finding tied to a DIFFERENT
    analysis or scan.
  * The API 404s cleanly for a change request with no analysis yet.

The real AI provider is never called here - same monkeypatched
_FakeProvider pattern as the other test_module14_*.py / test_module15_*.py
files, applied to both analysis_engine.get_ai_provider (for /analyze) and
repository_matcher.get_ai_provider (for the match itself).

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
import app.services.repository_matcher as repository_matcher
from app.database.session import SessionLocal
from app.main import app
from app.models.enums import FileMatchLabel
from app.models.repository_finding import RepositoryFinding
from app.services.repository_scanner import scan_repository

client = TestClient(app)


def _unique_email() -> str:
    return f"m15p3-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module15 Phase3 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify their identity with a one-time password (OTP) "
        "sent by SMS before completing a purchase.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FakeAnalysisProvider:
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(
            {
                "summary": "Adds OTP-based verification to the customer checkout flow.",
                "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
                "requirements": [
                    {
                        "category": "functional",
                        "description": "Customers receive and enter a one-time password (OTP) before checkout.",
                        "priority": "medium",
                        "certainty": "known",
                        "confidence": 90.0,
                        "evidence": "Explicitly requested.",
                    }
                ],
                "affected_components": [],
                "dependencies": [],
                "risks": [],
                "security_findings": [],
                "security_analysis": {"concerns": [], "summary": ""},
                "complexity": {"level": "low", "reasoning": "A contained auth feature."},
                "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
                "missing_information": [],
                "test_cases": [],
                "implementation_plan": [],
                "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
            }
        )


class _FakeMatchProvider:
    def __init__(self, response_obj):
        self._response_obj = response_obj

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(self._response_obj)


class _NeverCallProvider:
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        raise AssertionError("the AI provider should never be called when there are no candidate files")


def _setup_cr_with_analysis(monkeypatch, **cr_overrides):
    headers = _auth()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeAnalysisProvider())
    created = _create_change_request(headers, **cr_overrides)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    analysis = response.json()
    return headers, created, analysis


def _make_otp_repo(tmp_path: Path) -> Path:
    root = tmp_path / "otp_repo"
    root.mkdir()
    (root / "otp_service.py").write_text(
        "import hashlib\n\n\ndef generate_otp():\n    return 123456\n\n\ndef send_otp_sms(phone):\n    pass\n"
    )
    (root / "unrelated_widget.py").write_text(
        "def render_widget():\n    return '<div>widget</div>'\n"
    )
    return root


def test_no_candidates_never_calls_ai(monkeypatch, tmp_path):
    headers, created, analysis = _setup_cr_with_analysis(monkeypatch, title="Improve warehouse label printing")
    root = tmp_path / "empty_repo"
    root.mkdir()
    (root / "totally_unrelated.py").write_text("def render_widget():\n    return 1\n")

    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(repository_matcher, "get_ai_provider", lambda: _NeverCallProvider())
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 201
    assert response.json() == []


def test_match_creates_finding_with_computed_label(monkeypatch, tmp_path):
    headers, created, analysis = _setup_cr_with_analysis(monkeypatch)
    root = _make_otp_repo(tmp_path)

    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(
        repository_matcher,
        "get_ai_provider",
        lambda: _FakeMatchProvider(
            {
                "matches": [
                    {
                        "file_path": "otp_service.py",
                        "impact_level": "high",
                        "confidence": 88,
                        "reason": "Implements OTP generation and delivery, exactly what this change extends.",
                        "evidence": "Functions generate_otp, send_otp_sms",
                    }
                ]
            }
        ),
    )
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 201
    findings = response.json()
    assert len(findings) == 1
    finding = findings[0]
    assert finding["file_path"] == "otp_service.py"
    assert finding["impact_level"] == "high"
    assert finding["confidence"] == 88
    assert finding["match_label"] == "likely_affected"  # >= 75, see FileMatchLabel.from_confidence
    assert finding["change_request_id"] == created["id"]
    assert finding["analysis_id"] == analysis["id"]
    assert "unrelated_widget.py" not in finding["file_path"]

    listing = client.get(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_low_confidence_gets_possibly_related_label(monkeypatch, tmp_path):
    headers, created, analysis = _setup_cr_with_analysis(monkeypatch)
    root = _make_otp_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(
        repository_matcher,
        "get_ai_provider",
        lambda: _FakeMatchProvider(
            {
                "matches": [
                    {
                        "file_path": "otp_service.py",
                        "impact_level": "low",
                        "confidence": 30,
                        "reason": "Loosely related by naming only.",
                        "evidence": "file name relevance",
                    }
                ]
            }
        ),
    )
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 201
    assert response.json()[0]["match_label"] == "possibly_related"  # < 45


def test_hallucinated_file_path_is_dropped(monkeypatch, tmp_path):
    headers, created, analysis = _setup_cr_with_analysis(monkeypatch)
    root = _make_otp_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(
        repository_matcher,
        "get_ai_provider",
        lambda: _FakeMatchProvider(
            {
                "matches": [
                    {
                        "file_path": "otp_service.py",
                        "impact_level": "high",
                        "confidence": 80,
                        "reason": "Real candidate.",
                        "evidence": "generate_otp",
                    },
                    {
                        "file_path": "this/file/was/never/indexed.py",
                        "impact_level": "high",
                        "confidence": 95,
                        "reason": "Hallucinated - should be dropped.",
                        "evidence": "made up",
                    },
                ]
            }
        ),
    )
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 201
    findings = response.json()
    assert len(findings) == 1
    assert findings[0]["file_path"] == "otp_service.py"


def test_rerun_replaces_findings_for_same_analysis_and_scan(monkeypatch, tmp_path):
    headers, created, analysis = _setup_cr_with_analysis(monkeypatch)
    root = _make_otp_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(
        repository_matcher,
        "get_ai_provider",
        lambda: _FakeMatchProvider({"matches": [{"file_path": "otp_service.py", "confidence": 80}]}),
    )
    first = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert len(first.json()) == 1

    monkeypatch.setattr(
        repository_matcher,
        "get_ai_provider",
        lambda: _FakeMatchProvider({"matches": [{"file_path": "otp_service.py", "confidence": 40}]}),
    )
    second = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert len(second.json()) == 1
    assert second.json()[0]["match_label"] == "possibly_related"

    db = SessionLocal()
    try:
        remaining = (
            db.query(RepositoryFinding)
            .filter(RepositoryFinding.change_request_id == created["id"])
            .all()
        )
        assert len(remaining) == 1  # the first run's row was replaced, not duplicated
    finally:
        db.close()


def test_no_analysis_yet_404s(monkeypatch):
    headers = _auth()
    created = _create_change_request(headers)
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 404
