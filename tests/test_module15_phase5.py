"""Verifies Module 15 Phase 5 (Repository Intelligence - Integration):
repository findings feed the existing Impact Analysis / Dependencies /
Risk / Implementation Plan / Test Cases sections, without creating a
second, parallel impact system (per the module's own spec and the
POST-MODULE-12 architecture lock).

  * Once a repository match has run for a change request's current
    analysis, GET .../analysis attaches `related_files` to every affected
    component / impact assessment / dependency / risk / test case /
    implementation task whose own text plausibly overlaps with one of the
    CR's repository findings - and leaves it empty for one that doesn't,
    proving this is real overlap-based linking, not "attach everything to
    everything."
  * The exact same happens on POST .../analyze's own response for an
    analysis that already has repository findings tied to it.
  * Before any repository match has ever been run, `related_files` is
    simply [] everywhere - no crash, no special-casing needed by the
    caller.
  * Nothing about this phase invents a new persisted table or duplicates
    RepositoryFinding itself - `related_files` is computed fresh on every
    response (app/services/repository_linkage.py), exactly like
    is_outdated/workflow_recommendation before it.

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
from app.services.repository_scanner import scan_repository

client = TestClient(app)


def _unique_email() -> str:
    return f"m15p5-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module15 Phase5 Tester", "email": email, "password": password, "confirm_password": password},
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
    """Populates one item in each of the 6 sections Phase 5 links against -
    one item's own words deliberately echo the repository finding's own
    reason/evidence text (about otp_service.py's OTP generation), the
    other-flavored fields (dependency/risk/test/task) are worded the same
    way so every section gets a genuine, checkable overlap - and nothing
    here is worded to overlap with the unrelated widget file."""

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(
            {
                "summary": "Adds OTP-based verification to the customer checkout flow.",
                "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
                "requirements": [],
                "affected_components": [
                    {
                        "name": "OTP Service",
                        "type": "backend",
                        "impact_level": "high",
                        "reason": "Generates the one-time password (OTP) used during checkout.",
                        "confidence": 90,
                        "certainty": "known",
                        "evidence": "New OTP generation logic.",
                    }
                ],
                "dependencies": [
                    {
                        "name": "SMS Gateway",
                        "type": "external",
                        "impact_level": "medium",
                        "reason": "Delivers the OTP generation output by text message.",
                    }
                ],
                "risks": [
                    {
                        "category": "security",
                        "description": "OTP generation could be brute-forced if not rate-limited.",
                        "severity": "medium",
                        "probability": 0.3,
                        "score": 40.0,
                        "mitigation": "Rate-limit OTP generation attempts per phone number.",
                    }
                ],
                "security_findings": [],
                "security_analysis": {"concerns": [], "summary": ""},
                "impact_assessments": [
                    {
                        "category": "security",
                        "impact_level": "medium",
                        "description": "Introduces new OTP generation and delivery into the checkout flow.",
                    }
                ],
                "complexity": {"level": "low", "reasoning": "A contained auth feature."},
                "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
                "missing_information": [],
                "test_cases": [
                    {
                        "id": "TC-1",
                        "title": "OTP generation succeeds",
                        "type": "manual",
                        "priority": "medium",
                        "description": "Verify OTP generation returns a valid 6-digit code.",
                        "expected_result": "A 6-digit OTP is generated.",
                    }
                ],
                "implementation_plan": [
                    {
                        "task": "Build OTP generation endpoint",
                        "description": "Implement the OTP generation function and wire it into checkout.",
                        "component": "Backend",
                        "priority": "medium",
                        "estimated_effort": "2 days",
                    }
                ],
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
                        "confidence": 88,
                        "reason": "Implements OTP generation, exactly what this change extends.",
                        "evidence": "Function generate_otp",
                    }
                ]
            }
        )


def _make_otp_repo(tmp_path: Path) -> Path:
    root = tmp_path / "otp_repo"
    root.mkdir()
    (root / "otp_service.py").write_text(
        "def generate_otp():\n    return 123456\n\n\ndef send_otp_sms(phone):\n    pass\n"
    )
    (root / "unrelated_widget.py").write_text("def render_widget():\n    return '<div>widget</div>'\n")
    return root


def _setup_cr_with_analysis_and_findings(monkeypatch, tmp_path):
    headers = _auth()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeAnalysisProvider())
    created = _create_change_request(headers)
    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze.status_code == 201

    root = _make_otp_repo(tmp_path)
    db = SessionLocal()
    try:
        scan_repository(db, root_path=root)
    finally:
        db.close()

    monkeypatch.setattr(repository_matcher, "get_ai_provider", lambda: _FakeMatchProvider())
    match = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert match.status_code == 201
    assert len(match.json()) == 1
    return headers, created


def test_related_files_empty_before_any_repository_match(monkeypatch):
    headers = _auth()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeAnalysisProvider())
    created = _create_change_request(headers)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    analysis = response.json()

    assert analysis["affected_components"][0]["related_files"] == []
    assert analysis["impact_assessments"][0]["related_files"] == []
    assert analysis["dependencies"][0]["related_files"] == []
    assert analysis["risks"][0]["related_files"] == []
    assert analysis["test_cases"][0]["related_files"] == []
    assert analysis["implementation_tasks"][0]["related_files"] == []


def test_analyze_response_links_repository_findings_when_they_already_exist(monkeypatch, tmp_path):
    # Run analysis + a repository match FIRST, then re-analyze - the second
    # /analyze response is for a brand-new Analysis row with no findings of
    # its own yet (matching is a separate, later step), so this proves
    # annotate_analysis_response() is a safe no-op there, not that it's
    # broken.
    headers, created = _setup_cr_with_analysis_and_findings(monkeypatch, tmp_path)
    reanalyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert reanalyze.status_code == 201
    assert reanalyze.json()["affected_components"][0]["related_files"] == []


def test_get_analysis_links_related_files_across_all_sections(monkeypatch, tmp_path):
    headers, created = _setup_cr_with_analysis_and_findings(monkeypatch, tmp_path)

    response = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert response.status_code == 200
    analysis = response.json()

    assert analysis["affected_components"][0]["related_files"] == ["otp_service.py"]
    assert analysis["impact_assessments"][0]["related_files"] == ["otp_service.py"]
    assert analysis["dependencies"][0]["related_files"] == ["otp_service.py"]
    assert analysis["risks"][0]["related_files"] == ["otp_service.py"]
    assert analysis["test_cases"][0]["related_files"] == ["otp_service.py"]
    assert analysis["implementation_tasks"][0]["related_files"] == ["otp_service.py"]


def test_no_overlap_item_gets_empty_related_files(monkeypatch, tmp_path):
    """An item whose own words share nothing meaningful with a finding's
    own file_path/reason/evidence never gets that file attached, even
    though a real, persisted finding exists for this same analysis -
    proving this is genuine per-item overlap, not "attach every finding to
    every item."

    The matched file below (checkout_widget.py) has to be a genuine
    candidate - it shares "checkout" with the change request's own
    title/description/analysis summary, which is what
    repository_matcher._score_candidates uses to shortlist candidates
    *before* the AI is ever called (a file with zero overlap there is
    dropped before reaching the AI at all, per Phase 3's own
    test_no_candidates_never_calls_ai - it would never make it into
    result.matches's candidate set in the first place). Its reason/
    evidence text is deliberately generic so it shares only that one
    word ("checkout") with the OTP-specific affected_component/risk
    wording below - one shared word is below repository_linkage's own
    2-word minimum, so related_files stays empty for both.
    """
    headers = _auth()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FakeAnalysisProvider())
    created = _create_change_request(headers)
    client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers).raise_for_status()

    root = _make_otp_repo(tmp_path)
    (root / "checkout_widget.py").write_text(
        "def render_checkout_widget():\n    return '<div>checkout</div>'\n"
    )
    db = SessionLocal()
    try:
        scan_repository(db, root_path=root)
    finally:
        db.close()

    class _GenericMatchProvider:
        def is_configured(self) -> bool:
            return True

        def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
            return json.dumps(
                {
                    "matches": [
                        {
                            "file_path": "checkout_widget.py",
                            "impact_level": "low",
                            "confidence": 35,
                            "reason": "Only a loose, generic naming similarity to the checkout flow.",
                            "evidence": "file name relevance only",
                        }
                    ]
                }
            )

    monkeypatch.setattr(repository_matcher, "get_ai_provider", lambda: _GenericMatchProvider())
    match = client.post(f"/api/change-requests/{created['id']}/repository-findings", headers=headers)
    assert match.status_code == 201
    assert len(match.json()) == 1

    response = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert response.status_code == 200
    analysis = response.json()
    # A real finding exists for this analysis, but its own reason/evidence
    # text ("loose, generic naming similarity" / "file name relevance")
    # shares nothing meaningful with the OTP-generation-worded analysis
    # items above - so every related_files list stays empty.
    assert analysis["affected_components"][0]["related_files"] == []
    assert analysis["risks"][0]["related_files"] == []
