"""Verifies Module 16 Phase 4/5 (Project Knowledge Base & RAG - CR
Analysis Integration + Source Attribution & Version Awareness):

  * When the knowledge base has a document genuinely relevant to a change
    request, POST .../analyze retrieves it, injects a "Relevant
    Documentation" section (with Source/Section attribution) into the AI
    prompt, and persists one KnowledgeEvidence row per retrieved chunk -
    returned on the analysis response as `knowledge_evidence`.
  * When nothing in the knowledge base is actually relevant, no
    "Relevant Documentation" section is injected at all, and
    `knowledge_evidence` is simply [] - proving this is genuine relevance
    filtering (min_score), not "always attach the closest thing on file."
  * A knowledge-base problem (the embedding provider itself unavailable)
    never fails the analysis itself - retrieval degrades to [] and the
    core analysis still succeeds, per the module's own "optional
    grounding, not a hard dependency" design.
  * Evidence carries real source-attribution fields (document, section,
    content, similarity score) and becomes "outdated" exactly when its
    parent analysis does (the change request was edited since) - the
    module's own version-awareness requirement.
  * KnowledgeEvidenceRead never exposes anything beyond its documented
    field set.

Every test here uses fake, monkeypatched AI providers for both the
analysis completion call (analysis_engine.get_ai_provider) and the
embedding call (knowledge_embeddings.get_ai_provider) - no real network
call, matching this app's established testing pattern.

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

import app.services.analysis_engine as analysis_engine
import app.services.knowledge_embeddings as knowledge_embeddings
from app.main import app
from app.schemas.knowledge_evidence import KnowledgeEvidenceRead

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p4-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Phase4 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(headers, filename, content: bytes):
    return client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


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


def _keyword_vector(text: str) -> list:
    """A tiny, self-contained deterministic "embedding" scoped to this test
    file only (a different dimensionality than any other test file's own
    fake scheme, so cross-test leftovers can never accidentally score a
    false match - see knowledge_embeddings.py::_cosine_similarity's own
    dimension-mismatch guard)."""
    lowered = text.lower()
    return [1.0 if "otp" in lowered else 0.0]


class _FakeEmbeddingProvider:
    def is_configured(self) -> bool:
        return True

    def embed(self, texts, *, timeout=None):
        return [_keyword_vector(t) for t in texts]


class _UnavailableEmbeddingProvider:
    def is_configured(self) -> bool:
        return False

    def embed(self, texts, *, timeout=None):
        raise RuntimeError("OpenRouterProvider is not configured - set OPENROUTER_API_KEY in backend/.env")


_VALID_ANALYSIS_JSON = {
    "summary": "Adds OTP-based verification to checkout.",
    "classification": {"category": "Feature Enhancement", "confidence": 0.9, "reason": "New auth step."},
    "requirements": [],
    "affected_components": [],
    "dependencies": [],
    "risks": [],
    "security_findings": [],
    "security_analysis": {"concerns": [], "summary": ""},
    "impact_assessments": [],
    "complexity": {"level": "low", "reasoning": "A contained auth feature.", "confidence": "medium"},
    "effort": {"backend": "2 days", "frontend": "1 day", "testing": "1 day", "total": "4 days", "confidence": "medium"},
    "missing_information": [],
    "test_cases": [],
    "implementation_plan": [],
    "recommendation": {"decision": "approve", "reasoning": "Low risk, clear requirement."},
}


class _PromptCheckingAnalysisProvider:
    """Returns a fixed valid analysis, but first records whether the
    prompt it was given actually contained the "Relevant Documentation"
    section - lets a test assert on prompt content without needing a real
    AI call."""

    def __init__(self):
        self.last_prompt: str | None = None

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        self.last_prompt = prompt
        return json.dumps(_VALID_ANALYSIS_JSON)


def test_analyze_injects_documentation_and_persists_knowledge_evidence(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(
        headers,
        "OTP Security Guidelines.md",
        b"# OTP Authentication\n\nRate-limit OTP attempts per phone number and expire codes after 5 minutes.\n",
    ).json()
    assert doc["status"] == "ready"
    embed_response = client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)
    assert embed_response.status_code == 200

    fake_provider = _PromptCheckingAnalysisProvider()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: fake_provider)

    created = _create_change_request(headers)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    assert "Relevant Documentation" in fake_provider.last_prompt
    assert "OTP Security Guidelines" in fake_provider.last_prompt
    assert "Source:" in fake_provider.last_prompt
    assert "Section:" in fake_provider.last_prompt

    evidence = body["knowledge_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["document_id"] == doc["id"]
    assert evidence[0]["document_title"] == "OTP Security Guidelines"
    assert evidence[0]["section_label"] == "OTP Authentication"
    assert evidence[0]["similarity_score"] == 1.0
    assert evidence[0]["change_request_version"] == 1
    assert evidence[0]["is_outdated"] is False
    assert "Rate-limit OTP attempts" in evidence[0]["content_snippet"]


def test_analyze_with_no_relevant_documentation_has_empty_evidence(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    # Even with an embedded document in the system (from another test, or
    # created here), a change request about something entirely unrelated
    # must retrieve nothing - min_score filtering, not "always attach the
    # closest thing on file."
    unrelated_doc = _upload(headers, "OTP Guidelines.md", b"OTP rate limiting guidance.").json()
    client.post(f"/api/knowledge/documents/{unrelated_doc['id']}/embed", headers=headers)

    fake_provider = _PromptCheckingAnalysisProvider()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: fake_provider)

    created = _create_change_request(
        headers,
        title="Repaint the office lobby",
        description="Repaint the lobby walls a lighter shade of grey before the open house.",
    )
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    body = response.json()

    assert body["knowledge_evidence"] == []
    assert "Relevant Documentation" not in fake_provider.last_prompt


def test_analyze_succeeds_even_when_embedding_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _UnavailableEmbeddingProvider())
    fake_provider = _PromptCheckingAnalysisProvider()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: fake_provider)

    headers = _auth()
    created = _create_change_request(headers)
    response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert response.status_code == 201
    assert response.json()["knowledge_evidence"] == []
    assert "Relevant Documentation" not in fake_provider.last_prompt


def test_knowledge_evidence_becomes_outdated_after_change_request_is_edited(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "OTP Policy.md", b"OTP codes must expire after 5 minutes.").json()
    client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)

    fake_provider = _PromptCheckingAnalysisProvider()
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: fake_provider)

    created = _create_change_request(headers)
    analyze = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze.status_code == 201
    assert analyze.json()["knowledge_evidence"][0]["is_outdated"] is False

    edit = client.put(
        f"/api/change-requests/{created['id']}",
        json={"title": "Add OTP authentication for customers at checkout"},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["change_request"]["current_version"] == 2

    latest = client.get(f"/api/change-requests/{created['id']}/analysis", headers=headers)
    assert latest.status_code == 200
    body = latest.json()
    assert body["is_outdated"] is True
    assert body["knowledge_evidence"][0]["is_outdated"] is True
    # The evidence row itself never changes what it recorded - it still
    # says which version it was actually retrieved against.
    assert body["knowledge_evidence"][0]["change_request_version"] == 1


def test_knowledge_evidence_schema_field_set():
    fields = set(KnowledgeEvidenceRead.model_fields.keys())
    assert fields == {
        "id",
        "document_id",
        "document_title",
        "section_label",
        "content_snippet",
        "similarity_score",
        "change_request_version",
        "retrieved_at",
        "is_outdated",
    }
