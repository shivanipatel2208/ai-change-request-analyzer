"""Pydantic read schema for KnowledgeDocument - Module 16 Phase 1 (Project
Knowledge Base & RAG). Mirrors the shape of app/schemas/repository_scan.py's
RepositoryScanRead - a plain from_attributes read model, no raw file
content ever included (the document's actual text lives on disk / in its
chunks, never in this response, for the same "never expose raw content in
an API response schema" reason Module 15 Phase 7 locked down for
IndexedFileRead)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import KnowledgeDocumentStatus


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    original_filename: str
    extension: str
    size_bytes: int
    status: KnowledgeDocumentStatus
    error_message: Optional[str] = None
    chunk_count: int
    archived: bool
    uploaded_by: Optional[int] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
