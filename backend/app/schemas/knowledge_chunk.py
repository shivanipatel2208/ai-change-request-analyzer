"""Pydantic read schema for KnowledgeChunk - Module 16 Phase 2 (Project
Knowledge Base & RAG - Parsing + Chunking). Deliberately excludes
`embedding` itself (an internal JSON-encoded vector, meaningless to
display and not something any caller of this API needs) - only content a
person or the AI-analysis integration (Phase 4) would actually want to
read.

`is_embedded` (Phase 6 - Frontend) is a computed boolean, not a raw
passthrough of the `embedding` column - it answers "has this chunk been
embedded yet?" (for the Knowledge Base page's own status display) without
ever exposing the vector itself. Because it isn't a real attribute on the
KnowledgeChunk model, api/knowledge.py::list_document_chunks builds these
objects explicitly rather than relying on automatic from_attributes
mapping for this one field."""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class KnowledgeChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    section_label: Optional[str] = None
    content: str
    char_count: int
    is_embedded: bool = False
