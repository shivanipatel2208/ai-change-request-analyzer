"""Verifies Module 16 Phase 3 (Project Knowledge Base & RAG - Embedding +
Vector Search):

  * POST .../embed calls the configured AI provider's embed() for every
    chunk of a document and stores each vector - never exposed in any API
    response (KnowledgeChunkRead/KnowledgeDocumentRead both omit it).
  * Embedding a document with no chunks (e.g. one whose parsing failed -
    see test_module16_phase2.py's own "failed document" test) is a clean
    400, not a crash.
  * A provider that isn't configured for embeddings (or at all) fails the
    endpoint cleanly with a 400 and a plain-language reason, rather than a
    bare 500 - the module's own spec asks for this to be testable.
  * GET /api/knowledge/search embeds the query and ranks chunks by cosine
    similarity to it - only chunks that are both embedded AND belong to a
    non-archived document are ever candidates; `top_k` limits how many
    come back.
  * Every test here uses a fake, deterministic embedding provider
    (monkeypatched the same way tests/test_module15_phase4.py and
    test_module15_phase5.py monkeypatch repository_matcher's
    get_ai_provider) - no real network call to OpenRouter, so this suite
    stays fast, free, and reliable regardless of whatever's in the
    developer's own backend/.env.

Run with (from backend/):  pytest ../tests
"""
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

import app.services.knowledge_embeddings as knowledge_embeddings
from app.main import app
from app.schemas.knowledge_search import KnowledgeSearchResult

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p3-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Phase3 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(headers, filename, content: bytes):
    return client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def _keyword_vector(text: str) -> list:
    """A tiny, fully deterministic 3-dimensional "embedding" - one
    dimension per keyword - so a test can assert exact cosine-similarity
    outcomes (1.0 for an exact keyword match, 0.0 for no overlap at all)
    without depending on any real embedding model's actual output."""
    lowered = text.lower()
    return [
        1.0 if "otp" in lowered else 0.0,
        1.0 if "deployment" in lowered else 0.0,
        1.0 if "database" in lowered else 0.0,
    ]


class _FakeEmbeddingProvider:
    def is_configured(self) -> bool:
        return True

    def embed(self, texts, *, timeout=None):
        return [_keyword_vector(t) for t in texts]


class _UnconfiguredEmbeddingProvider:
    def is_configured(self) -> bool:
        return False

    def embed(self, texts, *, timeout=None):
        raise RuntimeError("OpenRouterProvider is not configured - set OPENROUTER_API_KEY in backend/.env")


def test_embed_populates_chunk_embeddings_and_hides_them_from_responses(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()
    uploaded = _upload(headers, "OTP Guide.txt", b"Use OTP for login security.")
    document_id = uploaded.json()["id"]

    response = client.post(f"/api/knowledge/documents/{document_id}/embed", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "embedding" not in body
    assert body["status"] == "ready"

    from app.database.session import SessionLocal
    from app.models.knowledge_document import KnowledgeDocument

    db = SessionLocal()
    try:
        document = db.get(KnowledgeDocument, document_id)
        assert document.chunks[0].embedding is not None
        import json

        assert json.loads(document.chunks[0].embedding) == [1.0, 0.0, 0.0]
    finally:
        db.close()

    chunk_response = client.get(f"/api/knowledge/documents/{document_id}/chunks", headers=headers)
    assert "embedding" not in chunk_response.json()[0]


def test_embed_requires_auth_and_404_for_missing_document(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()
    uploaded = _upload(headers, "Notes.txt", b"Some notes.")
    document_id = uploaded.json()["id"]

    assert client.post(f"/api/knowledge/documents/{document_id}/embed").status_code == 401
    assert client.post("/api/knowledge/documents/999999999/embed", headers=headers).status_code == 404


def test_embed_fails_cleanly_when_provider_unconfigured(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _UnconfiguredEmbeddingProvider())
    headers = _auth()
    uploaded = _upload(headers, "Notes.txt", b"Some notes.")
    document_id = uploaded.json()["id"]

    response = client.post(f"/api/knowledge/documents/{document_id}/embed", headers=headers)
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"].lower()


def test_embed_document_with_no_chunks_returns_400(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()
    # A .pdf extension around content that isn't a real PDF fails parsing
    # (see test_module16_phase2.py) and ends up with zero chunks.
    uploaded = _upload(headers, "Broken.pdf", b"this is not a real pdf")
    document_id = uploaded.json()["id"]
    assert uploaded.json()["status"] == "failed"
    assert uploaded.json()["chunk_count"] == 0

    response = client.post(f"/api/knowledge/documents/{document_id}/embed", headers=headers)
    assert response.status_code == 400
    assert "no chunks" in response.json()["detail"].lower()


def test_search_ranks_by_similarity_and_excludes_unembedded_and_archived_chunks(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    otp_doc = _upload(headers, "OTP Security.txt", b"Use OTP for every login attempt.").json()
    client.post(f"/api/knowledge/documents/{otp_doc['id']}/embed", headers=headers)

    deploy_doc = _upload(headers, "Deployment Steps.txt", b"Deployment steps for the backend service.").json()
    client.post(f"/api/knowledge/documents/{deploy_doc['id']}/embed", headers=headers)

    unembedded_doc = _upload(headers, "Database Notes.txt", b"Database schema notes.").json()
    # Deliberately never embedded - its chunk must never appear in search results.

    archived_doc = _upload(headers, "Old OTP Notes.txt", b"Archived OTP rollout notes.").json()
    client.post(f"/api/knowledge/documents/{archived_doc['id']}/embed", headers=headers)
    from app.database.session import SessionLocal
    from app.models.knowledge_document import KnowledgeDocument

    db = SessionLocal()
    try:
        doc = db.get(KnowledgeDocument, archived_doc["id"])
        doc.archived = True
        db.commit()
    finally:
        db.close()

    response = client.get("/api/knowledge/search", params={"q": "otp"}, headers=headers)
    assert response.status_code == 200
    results = response.json()
    document_ids = {r["document_id"] for r in results}

    assert unembedded_doc["id"] not in document_ids
    assert archived_doc["id"] not in document_ids
    assert otp_doc["id"] in document_ids
    assert deploy_doc["id"] in document_ids

    # Look up each of this test's own documents by id rather than assuming
    # a fixed position - other tests in this same shared database may have
    # already embedded their own "OTP"-flavored documents too, which
    # legitimately tie this test's otp_doc at a perfect 1.0 score (that's
    # correct search behavior, not a bug, so this test must tolerate it
    # rather than assuming otp_doc is the only 1.0 in the whole table).
    results_by_document = {r["document_id"]: r for r in results}
    assert results_by_document[otp_doc["id"]]["score"] == 1.0
    assert results_by_document[deploy_doc["id"]]["score"] == 0.0

    # Ranking itself still has to actually work - every returned score
    # sits in descending order, so a perfect match is never ranked behind
    # an unrelated one, whoever else's documents happen to also be in the
    # table.
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_top_k_limits_results(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()
    for name, text in [
        ("otp1.txt", b"otp otp otp"),
        ("otp2.txt", b"otp again"),
        ("deploy1.txt", b"deployment notes"),
    ]:
        doc = _upload(headers, name, text).json()
        client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)

    response = client.get("/api/knowledge/search", params={"q": "otp", "top_k": 1}, headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_search_requires_authentication():
    assert client.get("/api/knowledge/search", params={"q": "otp"}).status_code == 401


def test_search_result_schema_field_set():
    fields = set(KnowledgeSearchResult.model_fields.keys())
    assert fields == {"score", "chunk_id", "document_id", "document_title", "section_label", "content"}
    assert "embedding" not in fields
