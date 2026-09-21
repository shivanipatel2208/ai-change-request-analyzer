"""Module 16 Phase 7 - dedicated security pass for Project Knowledge Base
& RAG, mirroring test_module15_phase7_security.py's own approach (a
dedicated audit, not just incidental coverage from earlier phases):

  * Raw embedding vectors - the one genuinely sensitive-shaped internal
    value this module ever computes - never leak through ANY API response
    (document read, chunk list, search results, or CR-analysis evidence),
    even once a document has actually been embedded.
  * Every knowledge-base endpoint requires authentication - no anonymous
    read or write access to uploaded documents, search, or the knowledge
    base's own management actions (embed/reprocess/archive/unarchive).
  * A filename crafted to escape the storage directory (path traversal)
    can never write outside backend/data/knowledge_documents/ - upload
    always resolves to a flat, sanitized filename under that one folder,
    regardless of what the browser sent as the original filename.
  * An archived document's chunks - even ones that would otherwise be a
    perfect keyword/embedding match - are never retrieved into a real
    CR analysis's "Relevant Documentation" grounding context. Archiving
    is a genuine access boundary for retrieval, not just a list-filter.
  * Every response schema this module defines (KnowledgeDocumentRead,
    KnowledgeChunkRead, KnowledgeSearchResult, KnowledgeEvidenceRead) is
    locked to its documented field set - a future change to any of them
    can't silently start returning something new (like the raw embedding,
    or a server filesystem path) without a test having to be updated to
    notice it.

Role-based restriction (who may upload/delete vs who may only view) is
NOT added here - per this module's own spec section 9 and api/knowledge.py's
own docstring, "any authenticated user" remains the deliberate starting
point for this hackathon, the same scope Module 15's own repository
endpoints shipped with (see PROJECT_REPORT.md's Known Limitations for
both modules). This pass verifies the boundaries that DO exist -
authentication, embedding-vector secrecy, path safety, and archive-as-
retrieval-boundary - are real and enforced in code, not just assumed.

Run with (from backend/):  python -m pytest ../tests
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
from app.schemas.knowledge_chunk import KnowledgeChunkRead
from app.schemas.knowledge_document import KnowledgeDocumentRead
from app.schemas.knowledge_evidence import KnowledgeEvidenceRead
from app.schemas.knowledge_search import KnowledgeSearchResult
from app.services.knowledge_documents import _storage_root

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p7-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Phase7 Tester", "email": email, "password": password, "confirm_password": password},
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


class _FixedAnalysisProvider:
    def is_configured(self) -> bool:
        return True

    def complete(self, prompt, *, system=None, max_tokens=1024, timeout=None):
        return json.dumps(_VALID_ANALYSIS_JSON)


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


def test_embedding_vector_never_leaks_through_any_response(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    doc = _upload(headers, "OTP Guide.md", b"# OTP\n\nOTP codes expire after five minutes.\n").json()
    embed_response = client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)
    assert embed_response.status_code == 200
    assert "embedding" not in embed_response.text

    get_response = client.get(f"/api/knowledge/documents/{doc['id']}", headers=headers)
    assert "embedding" not in get_response.text

    chunks_response = client.get(f"/api/knowledge/documents/{doc['id']}/chunks", headers=headers)
    assert "embedding" not in chunks_response.text

    search_response = client.get("/api/knowledge/search?q=otp", headers=headers)
    assert search_response.status_code == 200
    assert "embedding" not in search_response.text


def test_every_knowledge_endpoint_requires_authentication(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()
    doc = _upload(headers, "Auth Boundary Guide.txt", b"OTP guidance for the auth-boundary test.").json()

    # No Authorization header on any of them - each must be a clean 401/403,
    # never a 200 or an unhandled error.
    unauthenticated_calls = [
        ("GET", "/api/knowledge/documents"),
        ("GET", f"/api/knowledge/documents/{doc['id']}"),
        ("GET", f"/api/knowledge/documents/{doc['id']}/chunks"),
        ("GET", "/api/knowledge/search?q=otp"),
        ("POST", f"/api/knowledge/documents/{doc['id']}/embed"),
        ("POST", f"/api/knowledge/documents/{doc['id']}/reprocess"),
        ("POST", f"/api/knowledge/documents/{doc['id']}/archive"),
        ("POST", f"/api/knowledge/documents/{doc['id']}/unarchive"),
    ]
    for method, path in unauthenticated_calls:
        response = client.request(method, path)
        assert response.status_code in (401, 403), f"{method} {path} should require auth, got {response.status_code}"

    # Uploading with no auth header must also be rejected, not silently accepted.
    upload_response = client.post(
        "/api/knowledge/documents",
        files={"file": ("no-auth.txt", io.BytesIO(b"should be rejected"), "text/plain")},
    )
    assert upload_response.status_code in (401, 403)


def test_path_traversal_filename_cannot_escape_storage_directory(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    headers = _auth()

    malicious_names = [
        "../../../etc/passwd.txt",
        "..\\..\\windows\\win.ini.txt",
        "/etc/cron.d/evil.txt",
    ]
    storage_root = _storage_root().resolve()

    for name in malicious_names:
        response = _upload(headers, name, b"content from a path-traversal attempt")
        assert response.status_code == 201, f"upload with filename {name!r} should still succeed safely"
        # KnowledgeDocumentRead never exposes the server-side stored_filename
        # or path (see test_response_schemas_locked_to_their_documented_
        # field_sets below) - so the check here is on the storage directory
        # itself: every file it now holds must resolve inside storage_root,
        # flat, no subdirectories created by a traversal attempt.
        entries = list(storage_root.rglob("*"))
        for entry in entries:
            resolved = entry.resolve()
            assert storage_root in resolved.parents or resolved == storage_root, (
                f"a file for upload {name!r} escaped the storage root: {resolved}"
            )
            # Never a subdirectory - every stored file sits flat in storage_root.
            if entry.is_file():
                assert entry.parent == storage_root


def test_archived_documents_excluded_from_cr_analysis_retrieval(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "get_ai_provider", lambda: _FakeEmbeddingProvider())
    monkeypatch.setattr(analysis_engine, "get_ai_provider", lambda: _FixedAnalysisProvider())
    headers = _auth()

    doc = _upload(headers, "OTP Archived Guide.md", b"# OTP\n\nOTP rate limiting details for Alight.com.\n").json()
    client.post(f"/api/knowledge/documents/{doc['id']}/embed", headers=headers)
    archive_response = client.post(f"/api/knowledge/documents/{doc['id']}/archive", headers=headers)
    assert archive_response.status_code == 200

    created = _create_change_request(headers)
    analyze_response = client.post(f"/api/change-requests/{created['id']}/analyze", headers=headers)
    assert analyze_response.status_code == 201
    body = analyze_response.json()

    # A perfect keyword/embedding match, but the document is archived - it
    # must never surface as evidence, regardless of how relevant its text is.
    # (Asserting the evidence list is entirely empty would be too strong a
    # claim here: this suite's tests all share one SQLite database for the
    # whole run - test_module16_phase4.py and test_module16_phase6.py both
    # embed their own "OTP"-related documents using this same simple 1-
    # dimensional keyword scheme, and this test reuses _create_change_
    # request's default "Add OTP authentication..." title, so a *different*,
    # non-archived document from an earlier test file can legitimately also
    # match and appear here. What must be true - the only thing this test is
    # actually about - is that THIS document, once archived, is never among
    # them.)
    assert not any(e["document_id"] == doc["id"] for e in body["knowledge_evidence"])


def test_response_schemas_locked_to_their_documented_field_sets():
    assert set(KnowledgeDocumentRead.model_fields.keys()) == {
        "id",
        "title",
        "original_filename",
        "extension",
        "size_bytes",
        "status",
        "error_message",
        "chunk_count",
        "archived",
        "uploaded_by",
        "uploaded_at",
        "processed_at",
    }
    assert set(KnowledgeChunkRead.model_fields.keys()) == {
        "id",
        "document_id",
        "chunk_index",
        "section_label",
        "content",
        "char_count",
        "is_embedded",
    }
    assert set(KnowledgeSearchResult.model_fields.keys()) == {
        "score",
        "chunk_id",
        "document_id",
        "document_title",
        "section_label",
        "content",
    }
    assert set(KnowledgeEvidenceRead.model_fields.keys()) == {
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
    # None of the four schemas ever names the raw vector or a server
    # filesystem path - the two internal shapes this module must never
    # expose - under any field name.
    for schema in (KnowledgeDocumentRead, KnowledgeChunkRead, KnowledgeSearchResult, KnowledgeEvidenceRead):
        fields = set(schema.model_fields.keys())
        assert "embedding" not in fields
        assert "stored_filename" not in fields
        assert not any("path" in f for f in fields)
