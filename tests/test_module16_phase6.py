"""Verifies the Module 16 Frontend phase's backend support pieces (the
parts of this phase that aren't purely visual and can be tested here):

  * GET /api/knowledge/documents/{id}/chunks reports `is_embedded` per
    chunk correctly - False right after upload/chunk (Phase 2), True for
    every chunk once the document has been embedded (Phase 3) - without
    ever exposing the raw embedding vector itself (already covered by
    test_module16_phase2.py's own schema field-set test, re-affirmed here
    since this test also asserts "embedding" is absent from the response
    JSON).
  * POST .../documents/{id}/archive marks a document archived - it drops
    out of the default GET /api/knowledge/documents list, reappears with
    `?include_archived=true`, and its chunks stay fully intact (never
    deleted).
  * POST .../documents/{id}/unarchive reverses that - the document comes
    back in the default list.
  * An archived document's embedded chunks are excluded from
    GET /api/knowledge/search results (this was already true for
    search_chunks() itself per test_module16_phase3.py; this test
    confirms it holds through the new archive endpoint specifically,
    since that's the only new way a document actually becomes archived).

Every test here uses a fake, deterministic embedding provider, the same
pattern as test_module16_phase3.py and test_module16_phase4.py - no real
network call.

Run with (from backend/):  python -m pytest ../tests
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

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p6-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Frontend-Phase Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(headers, filename, content: bytes):
    return client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


class _FakeEmbeddingProvider:
    def is_configured(self) -> bool:
        return True

    def embed(self, texts, *, timeout=None):
        return [[1.0 if "otp" in t.lower() else 0.0] for t in texts]


def test_chunks_report_is_embedded_false_then_true_without_exposing_vector(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "OTP Notes.txt", b"OTP codes expire after five minutes.").json()
    assert doc["status"] == "ready"

    before = client.get(f"/api/knowledge/documents/{doc['id']}/chunks", headers=headers)
    assert before.status_code == 200
    before_chunks = before.json()
    assert len(before_chunks) >= 1
    assert all(chunk["is_embedded"] is False for chunk in before_chunks)
    assert all("embedding" not in chunk for chunk in before_chunks)

    embed_response = client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)
    assert embed_response.status_code == 200

    after = client.get(f"/api/knowledge/documents/{doc['id']}/chunks", headers=headers)
    assert after.status_code == 200
    after_chunks = after.json()
    assert len(after_chunks) == len(before_chunks)
    assert all(chunk["is_embedded"] is True for chunk in after_chunks)
    assert all("embedding" not in chunk for chunk in after_chunks)


def test_archive_hides_document_from_default_list_but_keeps_chunks(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "Archivable Guide.txt", b"OTP guidance to be archived.").json()

    archive_response = client.post(f"/api/knowledge/documents/{doc['id']}/archive", headers=headers)
    assert archive_response.status_code == 200
    assert archive_response.json()["archived"] is True

    default_list = client.get("/api/knowledge/documents", headers=headers).json()
    assert all(d["id"] != doc["id"] for d in default_list)

    with_archived = client.get("/api/knowledge/documents?include_archived=true", headers=headers).json()
    assert any(d["id"] == doc["id"] and d["archived"] is True for d in with_archived)

    chunks = client.get(f"/api/knowledge/documents/{doc['id']}/chunks", headers=headers)
    assert chunks.status_code == 200
    assert len(chunks.json()) >= 1


def test_unarchive_restores_document_to_default_list(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "Restorable Guide.txt", b"OTP guidance to be restored.").json()
    client.post(f"/api/knowledge/documents/{doc['id']}/archive", headers=headers)

    unarchive_response = client.post(f"/api/knowledge/documents/{doc['id']}/unarchive", headers=headers)
    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["archived"] is False

    default_list = client.get("/api/knowledge/documents", headers=headers).json()
    assert any(d["id"] == doc["id"] for d in default_list)


def test_archived_documents_embedded_chunks_excluded_from_search(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "Searchable OTP Guide.txt", b"OTP rate limiting details.").json()
    client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)

    before_archive = client.get("/api/knowledge/search?q=otp", headers=headers).json()
    assert any(r["document_id"] == doc["id"] for r in before_archive)

    client.post(f"/api/knowledge/documents/{doc['id']}/archive", headers=headers)

    after_archive = client.get("/api/knowledge/search?q=otp", headers=headers).json()
    assert all(r["document_id"] != doc["id"] for r in after_archive)
