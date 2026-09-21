"""Module 16 Phase 1 (Project Knowledge Base & RAG): validating and
storing an uploaded knowledge-source document.

Files are saved to plain local disk under backend/data/knowledge_documents/
- the same "no unnecessary infrastructure" choice this app has made
everywhere else (SQLite instead of Postgres, no Docker, and per Module 15's
own repository scanner, no separate blob store for indexed source files
either). This also has a useful cross-module safety property: backend/
data/ is already excluded from Module 15's own repository scanner via its
_IGNORED_DIR_NAMES set (which includes "data"), so an uploaded knowledge
document can never accidentally get re-indexed as a project source file by
Repository Intelligence.

This module only handles Phase 1's slice: validate -> save to disk ->
create the KnowledgeDocument row with status UPLOADED. Parsing/chunking
(Phase 2) and embedding (Phase 3) are separate services that pick a
document up from there.
"""
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.models.enums import KnowledgeDocumentStatus

# .txt/.md/.pdf only for now, per this module's own spec section 1
# ("practical technical documents") - deliberately not html/docx/etc,
# matching the "simplest reliable architecture" instruction in spec
# section 2. Extending this set later is a one-line change here plus
# whatever Phase 2 parsing that new format needs.
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}

# 10 MB - generous for a technical doc/spec/policy at hackathon scale,
# small enough that parsing/chunking/embedding it stays fast and cheap.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class KnowledgeDocumentError(Exception):
    """Raised for any reason an upload can't be accepted - unsupported
    extension, empty file, oversized file. The API layer turns this into a
    400 with the message as-is (same pattern as RepositoryScanError in
    Module 15)."""


def _storage_root() -> Path:
    """backend/data/knowledge_documents/ - resolved from this file's own
    location (services -> app -> backend) rather than hardcoded, same
    reasoning as Settings.repository_root_path in core/config.py, so this
    resolves correctly on any machine this app is checked out on. Created
    on first use rather than assumed to exist."""
    root = Path(__file__).resolve().parents[2] / "data" / "knowledge_documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_stem(original_filename: str) -> str:
    """A filesystem-safe stem derived from the original filename, kept
    short and free of path separators - the actual uniqueness guarantee
    comes from the UUID suffix added in save_uploaded_document, this just
    keeps the stored filename recognizable at a glance in the data/
    folder."""
    stem = Path(original_filename).stem.strip()
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    safe = safe.strip("_") or "document"
    return safe[:80]


def save_uploaded_document(
    db: Session,
    *,
    original_filename: str,
    content: bytes,
    uploaded_by: Optional[int],
) -> KnowledgeDocument:
    """Validates and saves one uploaded file, then creates+commits+
    refreshes its KnowledgeDocument row with status UPLOADED (chunking/
    embedding happen later, in Phase 2/3). Raises KnowledgeDocumentError
    for any validation failure - nothing is written to disk or the
    database in that case."""
    if not original_filename or not original_filename.strip():
        raise KnowledgeDocumentError("A filename is required.")

    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise KnowledgeDocumentError(f"Unsupported file type {extension!r} - allowed types: {allowed}.")

    if not content:
        raise KnowledgeDocumentError("The uploaded file is empty.")

    if len(content) > MAX_DOCUMENT_BYTES:
        max_mb = MAX_DOCUMENT_BYTES // (1024 * 1024)
        raise KnowledgeDocumentError(f"The uploaded file is too large - the limit is {max_mb} MB.")

    stored_filename = f"{_safe_stem(original_filename)}_{uuid.uuid4().hex[:12]}{extension}"
    destination = _storage_root() / stored_filename
    destination.write_bytes(content)

    document = KnowledgeDocument(
        title=Path(original_filename).stem.strip() or original_filename,
        original_filename=original_filename,
        stored_filename=stored_filename,
        extension=extension,
        size_bytes=len(content),
        status=KnowledgeDocumentStatus.UPLOADED,
        chunk_count=0,
        archived=False,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def document_file_path(document: KnowledgeDocument) -> Path:
    """The absolute path to a document's stored file on disk - used by
    Phase 2's parsing step, and kept here rather than duplicated so
    storage layout only ever lives in one place."""
    return _storage_root() / document.stored_filename
