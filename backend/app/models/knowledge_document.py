"""KnowledgeDocument model - Module 16 Phase 1 (Project Knowledge Base &
RAG).

One row per uploaded knowledge-source document (architecture docs, API
docs, engineering guidelines, security policies, etc - see the module's
own spec section 1). This table is brand new (no pre-existing rows from an
earlier phase), so its columns can be NOT NULL from day one wherever the
value is always knowable at upload time - only genuinely optional fields
(error_message, processed_at) are nullable, following the same "new table
vs ALTER-added column" distinction already established for
RepositoryScan/IndexedFile in Module 15.

Deliberately separate from IndexedFile/RepositoryFinding (Module 15) - a
knowledge document is project *documentation* a human uploaded, not a
*source file* the app discovered by scanning a repository. Nothing here
duplicates or replaces Repository Intelligence; the two systems both feed
CR analysis but from different kinds of material (see
app/services/knowledge_documents.py's own docstring for the storage
layout, and why backend/data/knowledge_documents/ living under the same
data/ folder that Module 15's own scanner already ignores means uploaded
knowledge documents can never be accidentally re-indexed as source code).
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import KnowledgeDocumentStatus, sa_enum


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A human-readable title - defaults to the original filename at upload
    # time (see knowledge_documents.py::save_uploaded_document) but kept as
    # its own column rather than always deriving it, so a later phase could
    # let someone rename a document without touching the file on disk.
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # The actual filename on disk under backend/data/knowledge_documents/ -
    # UUID-suffixed to avoid collisions between two uploads that happen to
    # share a name (see _safe_stem in the service module). Never shown to
    # the user directly; original_filename/title are what the UI displays.
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Lowercase, includes the leading dot (".pdf", ".md", ".txt") - matches
    # the ALLOWED_EXTENSIONS the upload endpoint validates against.
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        sa_enum(KnowledgeDocumentStatus, "knowledge_document_status"),
        nullable=False,
        default=KnowledgeDocumentStatus.UPLOADED,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Denormalized count of this document's own chunks, kept in sync by
    # whatever phase actually creates them (Phase 2) - lets the Knowledge
    # Base UI (Phase 6) show "12 chunks" without a separate COUNT query.
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Soft-delete/hide, not a hard delete - matches the module spec's
    # "Delete/archive if supported" wording and this app's existing
    # preference for keeping history (nothing in this codebase hard-
    # deletes a change request either). An archived document is excluded
    # from retrieval and from the default document list, but its row (and
    # any analysis that already cited it) still exists.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
    )
    uploader: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} title={self.title!r} status={self.status}>"
