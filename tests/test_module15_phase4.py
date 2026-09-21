"""Verifies Module 15 Phase 4 (Repository Intelligence - Version
Awareness + Re-scan):

  * A repository finding, read back right after it's generated, is never
    outdated - it IS "the latest" of everything the moment it's written.
  * Editing the change request afterward (bumping its version) makes
    every one of its repository findings report is_outdated=True with a
    reason naming the edit - via GET, without anything about the finding
    rows themselves changing (workflow_rules.repository_finding_
    outdated_reasons is a computed-fresh check, same rule
    is_analysis_outdated already follows for AI analyses).
  * Running a NEW repository scan afterward (without touching the change
    request at all) makes existing findings outdated too, with a reason
    naming the newer scan - proving the three staleness triggers (CR
    edit / newer analysis / newer scan) are genuinely independent of each
    other, not all folded into "the CR changed."
  * The underlying rule function (workflow_rules.
    repository_finding_outdated_reasons) is also exercised directly for
    its third branch (a newer AI analysis) - not reachable through the
    two repository-findings endpoints today, since both of them only ever
    operate on a change request's current latest analysis by
    construction, but the rule itself is written generally enough to
    apply if a future endpoint ever needs it (e.g. viewing an older
    analysis's own repository findings on a history view).

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
from app.models.change_request import ChangeRequest
from app.services import workflow_rules
from app.services.repository_scanner import scan_repository

client = TestClient(app)


def _unique_email() -> str:
    return f"m15p4-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module15 Phase4 Tester", "email": email, "password": password, "confirm_password": password},
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
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(
            {
                "matches": [
                    {
                        "file_path": "otp_service.py",
                        "impact_level": "high",
                        "confidence": 85,
                        "reason": "Implements OTP generation, exactly what this change extends.",
                        "evidence": "Function generate_otp",
                    }
                ]
            }
        )


def _make_otp_repo(tmp_path: Path) -> Path:
    root = tmp_path / "otp_repo"
    root.mkdir()
    (root / "otp_service.py").write_text("def generate_otp():\n    return 123456\n")
    return root


def _setup_cr_with_findings(monkeypatch, tmp_path):
    headers = _auth()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeAnalysisProvider())
    created = _create_change_request(headers)
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).raise_for_status()

    root = _make_otp_repo(tmp_path)
    db = SessionLocal()
    try:
        scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(repository_matcher, "get_ai_provider", lambda: _FakeMatchProvider())
    response = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert response.status_code == 201
    assert len(response.json()) == 1
    return headers, created


def test_fresh_findings_are_not_outdated(monkeypatch, tmp_path):
    headers, created = _setup_cr_with_findings(monkeypatch, tmp_path)
    listing = client.get(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert listing.status_code == 200
    finding = listing.json()[0]
    assert finding["is_outdated"] is False
    assert finding["outdated_reasons"] == []


def test_editing_change_request_marks_findings_outdated(monkeypatch, tmp_path):
    headers, created = _setup_cr_with_findings(monkeypatch, tmp_path)

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"title": "Add OTP authentication for customers at checkout"},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["current_version"] == 2

    listing = client.get(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    finding = listing.json()[0]
    assert finding["is_outdated"] is True
    assert any("edited" in reason for reason in finding["outdated_reasons"])


def test_new_scan_marks_findings_outdated(monkeypatch, tmp_path):
    headers, created = _setup_cr_with_findings(monkeypatch, tmp_path)

    # A second scan of a DIFFERENT folder - the finding's own scan is no
    # longer "the latest" one, even though nothing about the change
    # request itself changed.
    other_root = tmp_path / "other_repo"
    other_root.mkdir()
    (other_root / "misc.py").write_text("def noop():\n    pass\n")
    db = SessionLocal()
    try:
        scan_repository(db, root_path=other_root)
    finally:
        db.close()

    listing = client.get(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    finding = listing.json()[0]
    assert finding["is_outdated"] is True
    assert any("newer repository scan" in reason for reason in finding["outdated_reasons"])


def test_repository_finding_outdated_reasons_unit():
    change_request = ChangeRequest(current_version=3)

    # Nothing has moved - no reasons.
    assert workflow_rules.repository_finding_outdated_reasons(
        change_request, 3, 10, 20, latest_analysis_id=10, latest_repository_scan_id=20
    ) == []

    # CR edited since (version 3 -> finding still says 2).
    reasons = workflow_rules.repository_finding_outdated_reasons(
        change_request, 2, 10, 20, latest_analysis_id=10, latest_repository_scan_id=20
    )
    assert len(reasons) == 1 and "edited" in reasons[0]

    # A newer analysis exists (not reachable via the current endpoints,
    # but the rule itself must still recognize it).
    reasons = workflow_rules.repository_finding_outdated_reasons(
        change_request, 3, 10, 20, latest_analysis_id=11, latest_repository_scan_id=20
    )
    assert len(reasons) == 1 and "newer AI analysis" in reasons[0]

    # A newer scan exists.
    reasons = workflow_rules.repository_finding_outdated_reasons(
        change_request, 3, 10, 20, latest_analysis_id=10, latest_repository_scan_id=21
    )
    assert len(reasons) == 1 and "newer repository scan" in reasons[0]

    # All three at once.
    reasons = workflow_rules.repository_finding_outdated_reasons(
        change_request, 1, 5, 5, latest_analysis_id=11, latest_repository_scan_id=21
    )
    assert len(reasons) == 3
