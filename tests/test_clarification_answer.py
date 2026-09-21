"""Verifies the clarification-question answer feature (a human supplying the
missing information the AI itself asked for, right on the Missing
Information tab):

  * PATCH .../clarification-questions/{id}/answer - sets answer_text/
    answered_by/answered_at and always marks the question resolved=True.
    Open to anyone who can comment on the change request (Capability.
    COMMENTS) - not gated to a reviewer role, since supplying a known fact
    isn't the same as passing judgment on the AI's findings (contrast with
    review_requirement/update_security_finding_status in
    test_module14_phase6.py, which ARE gated that way). Records
    HistoryAction.CLARIFICATION_ANSWERED on the change request's audit
    history. A blank/whitespace-only answer is rejected with 422. Can be
    called again on an already-resolved question to correct the answer.

The real AI provider is never called here - same monkeypatched
_FakeProvider pattern as the other test_module14_*.py files.

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
    return f"clarify-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> tuple:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Clarification Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_change_request(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add bulk export to admin dashboard",
        "description": "Let Alight.com admins export the full customer list as a CSV from the dashboard.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Admin Dashboard",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class _FakeProvider:
    def __init__(self, response_text):
        self._text = response_text

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return self._text


def _patch_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: provider)


def _minimal_response(**overrides) -> dict:
    base = {
        "summary": "Adds a CSV export button to the admin dashboard.",
        "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New export capability."},
        "requirements": [
            {
                "category": "functional",
                "description": "Admins can export the full customer list as a CSV file.",
                "priority": "medium",
                "certainty": "known",
                "confidence": 90.0,
                "evidence": "The request explicitly asks for a CSV export.",
            }
        ],
        "affected_components": [],
        "dependencies": [],
        "risks": [],
        "security_findings": [],
        "security_analysis": {"concerns": [], "summary": ""},
        "complexity": {"level": "low", "reasoning": "A straightforward export feature."},
        "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 developer-days"},
        # The one clarification question every test in this file exercises.
        "missing_information": [
            {
                "question": "What specific UI changes are required for the password setup process?",
                "priority": "important",
                "reason": "Directly impacts frontend implementation.",
            }
        ],
        "test_cases": [],
        "implementation_plan": [],
        "recommendation": {"decision": "requires_clarification", "reasoning": "Needs one open question answered."},
    }
    base.update(overrides)
    return base


def _analyze(headers, cr_id):
    response = client.post(f"/api/change-requests/{cr_id}/analyze", headers=headers)
    assert response.status_code == 201
    return client.get(f"/api/change-requests/{cr_id}/analysis", headers=headers).json()


def _setup_analysis(monkeypatch, headers, cr_id):
    _patch_provider(monkeypatch, _FakeProvider(json.dumps(_minimal_response())))
    return _analyze(headers, cr_id)


def test_answer_clarification_question_round_trip(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    question = detail["clarification_questions"][0]
    assert question["resolved"] is False
    assert question["answer_text"] is None

    response = client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "The password setup screen gains a 'Set password' button and a confirm-password field."},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["answer_text"] == "The password setup screen gains a 'Set password' button and a confirm-password field."
    assert body["answered_by"] is not None
    assert body["answered_at"] is not None
    # The AI's own question/priority/reason are untouched by answering it.
    assert body["question"] == question["question"]
    assert body["priority"] == question["priority"]
    assert body["reason"] == question["reason"]


def test_answer_clarification_question_rejects_blank_answer(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    question = detail["clarification_questions"][0]

    response = client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "   "},
        headers=headers,
    )
    assert response.status_code == 422


def test_answer_clarification_question_wrong_change_request_404s(monkeypatch):
    headers, _ = _auth()
    created_a = _create_change_request(headers, title="CR A")
    created_b = _create_change_request(headers, title="CR B")
    detail_a = _setup_analysis(monkeypatch, headers, created_a["id"])
    question = detail_a["clarification_questions"][0]

    response = client.patch(
        f"/api/change-requests/{created_b['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "This does not belong to CR B."},
        headers=headers,
    )
    assert response.status_code == 404


def test_answer_clarification_question_open_to_any_commenter_not_just_reviewers(monkeypatch):
    """Deliberately NOT gated like review_requirement/update_security_finding_status
    (see test_module14_phase6.py) - any authenticated user who can comment on
    the change request can supply the missing information, since it's often
    the requester (not a designated reviewer) who actually knows the answer."""
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    question = detail["clarification_questions"][0]

    other_headers, _ = _auth()
    response = client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "Answered by someone other than the CR's own creator."},
        headers=other_headers,
    )
    assert response.status_code == 200
    assert response.json()["resolved"] is True


def test_answer_clarification_question_can_be_corrected(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    question = detail["clarification_questions"][0]

    client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "First draft of the answer."},
        headers=headers,
    ).raise_for_status()

    response = client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "Corrected, more complete answer."},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "Corrected, more complete answer."
    assert body["resolved"] is True


def test_answer_clarification_question_records_history(monkeypatch):
    headers, _ = _auth()
    created = _create_change_request(headers)
    detail = _setup_analysis(monkeypatch, headers, created["id"])
    question = detail["clarification_questions"][0]

    client.patch(
        f"/api/change-requests/{created['id']}/clarification-questions/{question['id']}/answer",
        json={"answer": "The answer, for the history record."},
        headers=headers,
    ).raise_for_status()

    history = client.get(f"/api/change-requests/{created['id']}/history", headers=headers).json()
    matching = [h for h in history if h["action"] == "clarification_answered"]
    assert len(matching) == 1
    assert matching[0]["new_value"] == "The answer, for the history record."
    assert matching[0]["field_name"] == question["question"]
