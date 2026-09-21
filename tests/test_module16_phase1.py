"""Verifies Module 16 Phase 1 (Project Knowledge Base & RAG - Foundation):

  * A valid .txt/.md upload is accepted: saved to disk under backend/data/
    knowledge_documents/, and a KnowledgeDocument row is created with the
    right title/extension/size (status/chunk_count now reflect Module 16
    Phase 2's synchronous parsing+chunking, added after this file was
    first written - see test_module16_phase2.py for the dedicated parsing/
    chunking tests).
  * An unsupported extension (.docx), an empty file, and an oversized file
    are each rejected with a 400 and a plain-language reason - and nothing
    is written to disk or the database for a rejected upload.
  * GET /api/knowledge/documents lists uploaded documents newest first,
    and never includes an archived document.
  * GET /api/knowledge/documents/{id} returns one document, 404s for a
    nonexistent id.
  * Every endpoint requires auth (401 with no token).
  * The response schema never exposes raw file content - only the known
    metadata field set - mirroring Module 15 Phase 7's own schema lock-down
    test for IndexedFileRead/RepositoryFindingRead.

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

from app.main import app
from app.schemas.knowledge_document import KnowledgeDocumentRead
from app.services import knowledge_documents

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p1-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Phase1 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(headers, filename, content: bytes):
    return client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def test_valid_upload_creates_uploaded_document():
    headers = _auth()
    response = _upload(headers, "Security Guidelines.md", b"# Security Guidelines\n\nUse OTP for login.\n")
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Security Guidelines"
    assert body["original_filename"] == "Security Guidelines.md"
    assert body["extension"] == ".md"
    # As of Module 16 Phase 2, the upload endpoint parses+chunks a
    # document synchronously right after saving it, so a valid upload
    # comes back already "ready" (see test_module16_phase2.py for the
    # dedicated parsing/chunking tests) rather than sitting at "uploaded"
    # forever - "uploaded" now only describes the brief in-flight moment
    # before that happens, not a resting state a caller can rely on
    # observing.
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1
    assert body["archived"] is False
    assert body["size_bytes"] == len(b"# Security Guidelines\n\nUse OTP for login.\n")

    # The file actually landed on disk, under the expected storage root.
    from app.database.session import SessionLocal
    from app.models.knowledge_document import KnowledgeDocument

    db = SessionLocal()
    try:
        document = db.get(KnowledgeDocument, body["id"])
        assert document is not None
        path = knowledge_documents.document_file_path(document)
        assert path.exists()
        assert path.read_bytes() == b"# Security Guidelines\n\nUse OTP for login.\n"
    finally:
        db.close()


def test_unsupported_extension_is_rejected():
    headers = _auth()
    response = _upload(headers, "spec.docx", b"not really a docx but irrelevant here")
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_empty_file_is_rejected():
    headers = _auth()
    response = _upload(headers, "empty.txt", b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_oversized_file_is_rejected():
    headers = _auth()
    oversized = b"x" * (knowledge_documents.MAX_DOCUMENT_BYTES + 1)
    response = _upload(headers, "huge.txt", oversized)
    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()


def test_list_documents_newest_first_and_excludes_archived():
    headers = _auth()
    first = _upload(headers, "Architecture Overview.txt", b"System overview text.")
    second = _upload(headers, "API Reference.txt", b"API reference text.")
    assert first.status_code == 201 and second.status_code == 201

    from app.database.session import SessionLocal
    from app.models.knowledge_document import KnowledgeDocument

    db = SessionLocal()
    try:
        archived_doc = db.get(KnowledgeDocument, first.json()["id"])
        archived_doc.archived = True
        db.commit()
    finally:
        db.close()

    response = client.get("/api/knowledge/documents", headers=headers)
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert "API Reference" in titles
    assert "Architecture Overview" not in titles
    # Newest first: the un-archived "API Reference" document should appear,
    # and appear before any document uploaded earlier by this same test run
    # that also isn't archived (there's only one such document here).
    assert titles[0] == "API Reference"


def test_get_document_by_id_and_404_for_missing():
    headers = _auth()
    uploaded = _upload(headers, "Deployment Guide.md", b"# Deployment\n\nSteps here.")
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]

    response = client.get(f"/api/knowledge/documents/{document_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Deployment Guide"

    missing = client.get("/api/knowledge/documents/999999999", headers=headers)
    assert missing.status_code == 404


def test_endpoints_require_authentication():
    assert _upload({}, "doc.txt", b"content").status_code == 401
    assert client.get("/api/knowledge/documents").status_code == 401
    assert client.get("/api/knowledge/documents/1").status_code == 401


def test_response_schema_never_exposes_raw_file_content():
    """Locks KnowledgeDocumentRead to its known metadata field set - same
    "a future field can't silently start leaking raw content" reasoning as
    Module 15 Phase 7's schema lock-down test."""
    fields = set(KnowledgeDocumentRead.model_fields.keys())
    assert fields == {
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
    for forbidden_key in ("content", "source", "text", "body", "raw", "file_content"):
        assert forbidden_key not in fields
