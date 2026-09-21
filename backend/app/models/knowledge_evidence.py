"""KnowledgeEvidence model - Module 16 (Project Knowledge Base & RAG),
Phase 4/5 (CR Analysis Integration + Source Attribution & Version
Awareness).

One row per knowledge-base chunk that was retrieved and handed to the AI
as grounding context for one specific Analysis run - the module's own
spec section 4 ("Record evidence") and section 7 ("RAG context should be
associated with the analysis that used it... Record useful metadata:
Document, Chunk, Retrieved, Analysis version").

Deliberately snapshots document_title/section_label/content/score at
retrieval time rather than relying only on a live foreign key to
KnowledgeChunk - a document's chunks are replaced wholesale whenever it's
reprocessed (see app/services/knowledge_chunker.py::process_document,
which deletes every existing chunk before creating a fresh set), so a
chunk id recorded here could otherwise end up pointing at a row that no
longer exists by the time someone looks at a past analysis's evidence.
`chunk_id` is kept anyway as a plain, unenforced column (not a foreign
key) purely as an informational "which chunk, if it still exists" pointer
- every field a reader actually needs to display is snapshotted directly.
`document_id` IS a real foreign key, since KnowledgeDocument rows are
never hard-deleted (only archived) - this mirrors exactly the choice
app/models/repository_finding.py already made for Module 15: store what
was actually true at the time directly, don't assume a live join stays
valid forever.

`change_request_version` is duplicated here from Analysis.change_request_
version (rather than only reachable by joining back to Analysis) for the
same reason RepositoryFinding does the same thing - a reader can tell
"was this evidence retrieved against an outdated version of the change
request" without an extra join. Since evidence is always generated fresh
as part of one specific analysis run (never independently re-retrieved
later, unlike a repository scan which can be re-run on its own), there is
only one staleness axis here - not three like RepositoryFinding's own
version-awareness - so the API layer simply reuses whatever
is_analysis_outdated() already computed for the parent Analysis rather
than a second bespoke computation (see app/api/change_requests.py).
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class KnowledgeEvidence(Base):
    __tablename__ = "knowledge_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    # NOT a foreign key - see module docstring for why (the source chunk
    # may no longer exist by the time this row is read). Purely
    # informational.
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    document_title: Mapped[str] = mapped_column(String(255), nullable=False)
    section_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    change_request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    analysis: Mapped["Analysis"] = relationship(back_populates="knowledge_evidence")
    document: Mapped["KnowledgeDocument"] = relationship()

    def __repr__(self) -> str:
        return f"<KnowledgeEvidence id={self.id} analysis_id={self.analysis_id} document_id={self.document_id}>"
