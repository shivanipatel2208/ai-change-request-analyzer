"""Verifies Module 17 Phase 4 (Test Cases & Implementation Plan 2.0 -
Traceability):

  * app/services/traceability_linkage.py's keyword-overlap matching itself
    (requirement_references/risk_references), the same kind of unit-level
    coverage repository_linkage's own test file gives its own tokenizer/
    overlap functions.
  * A real POST /analyze call ends up with requirement_references/
    risk_references correctly populated on test cases, and
    requirement_references on implementation tasks - proving the wiring in
    app/api/change_requests.py (both the fresh-analysis and
    get_latest_analysis code paths) actually calls this module, not just
    that the module works in isolation.
  * The references are genuinely computed, not AI-generated: a made-up
    "REQ-999"/"RISK-999" in the AI's own raw text never appears in a
    response's real reference lists, since nothing here ever trusts an
    AI-supplied ID (the fixed provider used below doesn't even have the
    opportunity to supply one - TestCaseItem/ImplementationTaskItem have
    no such field - but the point is proven positively: only real,
    persisted Requirement/Risk ids from *this* analysis ever appear).
  * An analysis with no requirements and no risks at all leaves every
    reference list at its empty-list default rather than erroring.
  * Both API code paths (a fresh POST /analyze, and a later GET
    /analysis for the same change request) return the identical
    reference lists - the computation is deterministic and re-derived
    the same way every time, not accidentally order-dependent.

Every test here uses a fake, monkeypatched AI provider (analysis_engine.
get_ai_provider) - no real network call, matching this app's established
testing pattern.

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
from app.schemas.requirement import RequirementRead
from app.schemas.risk import RiskRead
from app.services.traceability_linkage import requirement_references, risk_references

client = TestClient(app)


def _unique_email() -> str:
    return f"m17p4-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module17 Phase4 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_change_request(headers, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication for customers",
        "description": "Let Alight.com customers verify identity with a one-time password before checkout.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Customer Portal",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


_ANALYSIS_JSON_WITH_REQUIREMENTS_AND_RISKS = {
    "summary": "Adds OTP-based verification to checkout.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
    "requirements": [
        {
            "category": "functional",
            "description": "Customers must receive a one-time password by SMS to verify their identity during checkout.",
            "priority": "high",
        },
        {
            "category": "non_functional",
            "description": "Refund processing must remain unaffected by this change.",
            "priority": "low",
        },
    ],
    "affected_components": [],
    "dependencies": [],
    "risks": [
        {
            "category": "security",
            "description": "An attacker could brute-force the one-time password within its validity window.",
            "severity": "high",
            "probability": 0.4,
            "score": 60,
            "mitigation": "Rate-limit OTP verification attempts.",
        }
    ],
    "security_findings": [],
    "security_analysis": {"concerns": [], "summary": ""},
    "impact_assessments": [],
    "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
    "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
    "missing_information": [],
    "test_cases": [
        {
            "id": "TC-001",
            "title": "OTP brute-force attempts are rate-limited",
            "type": "security",
            "priority": "high",
            "description": "Attempt to brute-force the one-time password sent by SMS during checkout verification.",
            "expected_result": "Further attempts are blocked after repeated failures.",
        },
        {
            "id": "TC-002",
            "title": "Existing refund flow remains unaffected",
            "type": "regression",
            "priority": "medium",
            "description": "Process a refund and confirm nothing about refund processing changed.",
            "expected_result": "The refund transaction proceeds exactly as it did previously.",
        },
    ],
    "implementation_plan": [
        {
            "task": "Rate-limit the OTP verification endpoint",
            "description": "Add a rate limit to the one-time password SMS verification endpoint.",
            "component": "Backend",
            "priority": "high",
            "estimated_effort": "1 day",
            "dependencies": None,
        }
    ],
    "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
}

_ANALYSIS_JSON_NO_REQUIREMENTS_OR_RISKS = {
    **_ANALYSIS_JSON_WITH_REQUIREMENTS_AND_RISKS,
    "requirements": [],
    "risks": [],
}


class _FixedProvider:
    def __init__(self, analysis_json):
        self._analysis_json = analysis_json

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(self._analysis_json)


def test_requirement_and_risk_references_populate_end_to_end(monkeypatch):
    monkeypatch.setattr(
        analysis_engine, "get_ai_provider", lambda: _FixedProvider(_ANALYSIS_JSON_WITH_REQUIREMENTS_AND_RISKS)
    )
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    otp_requirement_id = next(
        r["id"] for r in body["requirements"] if "one-time password by SMS" in r["description"]
    )
    refund_requirement_id = next(r["id"] for r in body["requirements"] if "Refund processing" in r["description"])
    brute_force_risk_id = body["risks"][0]["id"]

    test_cases = {tc["test_id"]: tc for tc in body["test_cases"]}
    assert test_cases["TC-001"]["requirement_references"] == [f"REQ-{otp_requirement_id}"]
    assert test_cases["TC-001"]["risk_references"] == [f"RISK-{brute_force_risk_id}"]
    assert test_cases["TC-002"]["requirement_references"] == [f"REQ-{refund_requirement_id}"]
    assert test_cases["TC-002"]["risk_references"] == []

    task = body["implementation_tasks"][0]
    assert task["requirement_references"] == [f"REQ-{otp_requirement_id}"]


def test_no_requirements_or_risks_leaves_references_empty(monkeypatch):
    monkeypatch.setattr(
        analysis_engine, "get_ai_provider", lambda: _FixedProvider(_ANALYSIS_JSON_NO_REQUIREMENTS_OR_RISKS)
    )
    headers = _auth()
    created = _create_change_request(headers)

    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    for test_case in body["test_cases"]:
        assert test_case["requirement_references"] == []
        assert test_case["risk_references"] == []
    for task in body["implementation_tasks"]:
        assert task["requirement_references"] == []


def test_get_latest_analysis_returns_identical_references(monkeypatch):
    monkeypatch.setattr(
        analysis_engine, "get_ai_provider", lambda: _FixedProvider(_ANALYSIS_JSON_WITH_REQUIREMENTS_AND_RISKS)
    )
    headers = _auth()
    created = _create_change_request(headers)

    analyze_response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze_response.status_code == 201
    fresh_refs = [
        (tc["test_id"], tc["requirement_references"], tc["risk_references"])
        for tc in analyze_response.json()["test_cases"]
    ]

    latest_response = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert latest_response.status_code == 200
    latest_refs = [
        (tc["test_id"], tc["requirement_references"], tc["risk_references"])
        for tc in latest_response.json()["test_cases"]
    ]

    assert fresh_refs == latest_refs


def test_traceability_linkage_functions_never_cite_a_fabricated_id():
    requirements = [
        RequirementRead(
            id=42,
            analysis_id=1,
            requirement_type="functional",
            description="Customers must verify their identity with a one-time password.",
            priority="high",
        )
    ]
    risks = [
        RiskRead(
            id=7,
            analysis_id=1,
            category="security",
            description="One-time password brute-forcing risk.",
            severity="high",
            probability=0.4,
            score=60,
            mitigation="Rate-limit attempts.",
        )
    ]

    matched_reqs = requirement_references("Verify a one-time password during checkout", requirements)
    assert matched_reqs == ["REQ-42"]

    matched_risks = risk_references("Brute-forcing a one-time password should be blocked", risks)
    assert matched_risks == ["RISK-7"]

    # Nothing shares enough real overlap with an unrelated topic - an
    # honest empty list, never a guess.
    assert requirement_references("Completely unrelated billing invoice export feature", requirements) == []
    assert risk_references("Completely unrelated billing invoice export feature", risks) == []
