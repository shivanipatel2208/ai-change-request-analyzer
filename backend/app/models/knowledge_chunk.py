"""KnowledgeChunk model - Module 16 Phase 1 (Project Knowledge Base &
RAG).

One row per chunk a KnowledgeDocument is split into (Phase 2 does the
actual parsing/chunking - this table just holds the result). `embedding`
is defined now, in Phase 1, but stays unpopulated (nullable) until Phase 3
adds the real AI-embeddings call - declaring the column up front avoids a
second ALTER TABLE later, and it's nullable exactly like every other
"phase 2/3 fills this in" column elsewhere in this app (e.g.
IndexedFile.imports et al from Module 15 Phase 1 -> Phase 2).
"""
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    # 0-based position of this chunk within its document - lets the UI/API
    # show chunks in original document order regardless of insertion order.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # A best-effort heading/section this chunk fell under (e.g. "OTP
    # Authentication"), when the source format has one (markdown headings,
    # PDF section text) - None when the source has no such structure (e.g.
    # a plain .txt file). Used for Phase 5's source-attribution "Section:
    # ..." line from the module spec.
    section_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSON-encoded list[float] - same "one text column, not a new table/
    # extension" pattern already used throughout this app (ChangeRequest.
    # tags, IndexedFile's Phase-2 columns) - populated by Module 16 Phase 3
    # (Embedding + Vector Search). Nullable: every chunk starts without an
    # embedding, and a chunk whose embedding call failed stays this way
    # rather than the whole document being silently marked READY without
    # actually being searchable.
    embedding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<KnowledgeChunk id={self.id} document_id={self.document_id} chunk_index={self.chunk_index}>"
