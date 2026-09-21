"""Verifies Module 16 Phase 2 (Project Knowledge Base & RAG - Parsing +
Chunking):

  * A plain .txt upload becomes exactly one chunk (no natural section
    structure to split on) and the document ends up "ready".
  * A .md upload with headings splits into one chunk per heading, in
    order, each carrying that heading's own text as section_label.
  * A single paragraph longer than MAX_CHUNK_CHARS is hard-split into
    several chunks whose combined length exactly reconstructs the
    original text - nothing dropped, nothing duplicated.
  * A .pdf upload is parsed page-by-page (via pypdf) - each page becomes
    one chunk labeled "Page N" containing that page's own text.
  * A .pdf that isn't actually a valid PDF is marked "failed" with a
    plain-language error_message - proving a parsing failure is a
    recorded state, not a 500 or a silently-dropped upload (the module's
    own spec asks to test "Failed documents").
  * GET .../chunks returns a document's chunks in order and requires
    auth; POST .../reprocess re-runs chunking and requires auth; both
    404 for a document id that doesn't exist.
  * KnowledgeChunkRead never exposes the internal `embedding` field.

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
from app.schemas.knowledge_chunk import KnowledgeChunkRead
from app.services.knowledge_chunker import MAX_CHUNK_CHARS

client = TestClient(app)


def _unique_email() -> str:
    return f"m16p2-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module16 Phase2 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(headers, filename, content: bytes):
    return client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def _make_pdf_bytes(text: str) -> bytes:
    """Builds a real one-page PDF containing `text`, using this project's
    own already-approved PDF library (fpdf2 - see
    app/services/report_generator.py, which builds the Module 6/13 PDF
    reports the same way) so this test needs no new/unapproved
    dependency beyond the pypdf *reader* Phase 2 itself adds."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, text)
    raw = pdf.output()
    return bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw.encode("latin-1")


def test_txt_upload_creates_single_ready_chunk():
    headers = _auth()
    response = _upload(headers, "Deployment Notes.txt", b"Deploy the backend, then the frontend. Done.")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1
    assert body["error_message"] is None
    assert body["processed_at"] is not None

    chunks = client.get(f"/api/knowledge/documents/{body['id']}/chunks", headers=headers).json()
    assert len(chunks) == 1
    assert chunks[0]["section_label"] is None
    assert chunks[0]["content"] == "Deploy the backend, then the frontend. Done."
    assert chunks[0]["chunk_index"] == 0


def test_markdown_upload_splits_by_heading_into_ordered_chunks():
    headers = _auth()
    markdown = (
        "# Introduction\n"
        "This document describes the OTP authentication rollout.\n\n"
        "## OTP Authentication\n"
        "Use a 6-digit OTP delivered by SMS. Rate-limit attempts per phone number.\n\n"
        "## Deployment\n"
        "Ship the backend first, then enable the feature flag.\n"
    )
    response = _upload(headers, "Security Guidelines.md", markdown.encode("utf-8"))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == 3

    chunks = client.get(f"/api/knowledge/documents/{body['id']}/chunks", headers=headers).json()
    assert [c["section_label"] for c in chunks] == ["Introduction", "OTP Authentication", "Deployment"]
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2]
    assert "OTP" in chunks[1]["content"]
    assert "Ship the backend" in chunks[2]["content"]


def test_long_single_paragraph_hard_splits_across_multiple_chunks():
    headers = _auth()
    # One paragraph (no blank lines) at exactly 2x the cap plus a partial
    # third piece - deterministic chunk boundaries: MAX_CHUNK_CHARS,
    # MAX_CHUNK_CHARS, then the 100-character remainder.
    long_text = "A" * (2 * MAX_CHUNK_CHARS + 100)
    response = _upload(headers, "Big Spec.txt", long_text.encode("utf-8"))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == 3

    chunks = client.get(f"/api/knowledge/documents/{body['id']}/chunks", headers=headers).json()
    char_counts = [c["char_count"] for c in chunks]
    assert char_counts == [MAX_CHUNK_CHARS, MAX_CHUNK_CHARS, 100]
    # Nothing dropped, nothing duplicated - the pieces reconstruct the
    # original text exactly.
    assert "".join(c["content"] for c in chunks) == long_text


def test_pdf_upload_extracts_text_and_marks_ready():
    headers = _auth()
    pdf_bytes = _make_pdf_bytes("This deployment guide covers OTP authentication rollout steps.")
    response = _upload(headers, "Deployment Guide.pdf", pdf_bytes)
    assert response.status_code == 201
    body = response.json()
    assert body["extension"] == ".pdf"
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 1

    chunks = client.get(f"/api/knowledge/documents/{body['id']}/chunks", headers=headers).json()
    assert chunks[0]["section_label"] == "Page 1"
    combined = " ".join(c["content"] for c in chunks)
    assert "OTP" in combined


def test_invalid_pdf_content_is_marked_failed_with_error_message():
    headers = _auth()
    # A .pdf extension around content that isn't a real PDF at all - the
    # upload itself is still accepted (extension/size/emptiness are the
    # only upload-time checks), but parsing fails and is recorded as such.
    response = _upload(headers, "Not Actually A PDF.pdf", b"this is plain text, not a pdf file")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0
    assert body["error_message"]


def test_chunks_and_reprocess_endpoints_require_auth_and_404_for_missing_document():
    headers = _auth()
    uploaded = _upload(headers, "Notes.txt", b"Some notes.")
    document_id = uploaded.json()["id"]

    assert client.get(f"/api/knowledge/documents/{document_id}/chunks").status_code == 401
    assert client.post(f"/api/knowledge/documents/{document_id}/reprocess").status_code == 401
    assert client.get("/api/knowledge/documents/999999999/chunks", headers=headers).status_code == 404
    assert client.post("/api/knowledge/documents/999999999/reprocess", headers=headers).status_code == 404


def test_reprocess_recomputes_chunks_for_an_already_ready_document():
    headers = _auth()
    uploaded = _upload(headers, "Notes Again.txt", b"Some notes that will be reprocessed.")
    document_id = uploaded.json()["id"]

    response = client.post(f"/api/knowledge/documents/{document_id}/reprocess", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1

    chunks = client.get(f"/api/knowledge/documents/{document_id}/chunks", headers=headers).json()
    assert len(chunks) == 1
    assert chunks[0]["content"] == "Some notes that will be reprocessed."


def test_chunk_schema_never_exposes_internal_embedding_field():
    fields = set(KnowledgeChunkRead.model_fields.keys())
    assert fields == {
        "id",
        "document_id",
        "chunk_index",
        "section_label",
        "content",
        "char_count",
        "is_embedded",
    }
    assert "embedding" not in fields
