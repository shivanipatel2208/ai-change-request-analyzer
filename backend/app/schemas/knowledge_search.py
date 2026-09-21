"""Pydantic read schema for one knowledge-base search result - Module 16
Phase 3 (Project Knowledge Base & RAG - Embedding + Vector Search).

Not from_attributes - app/services/knowledge_embeddings.py::search_chunks
returns plain dicts (each carrying a computed similarity `score` alongside
chunk/document data), not ORM objects, so Pydantic validates them as
ordinary dicts here."""
from typing import Optional

from pydantic import BaseModel


class KnowledgeSearchResult(BaseModel):
    score: float
    chunk_id: int
    document_id: int
    document_title: str
    section_label: Optional[str] = None
    content: str
