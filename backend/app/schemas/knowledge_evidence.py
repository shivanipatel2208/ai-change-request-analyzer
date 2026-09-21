"""Pydantic read schema for KnowledgeEvidence - Module 16 (Project
Knowledge Base & RAG) Phase 4/5 (CR Analysis Integration + Source
Attribution & Version Awareness).

This is the "Evidence Used" list the module's own spec section 8 asks the
Analysis Dashboard to show - one entry per knowledge-base chunk that was
retrieved and given to the AI as context for a specific analysis.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class KnowledgeEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_title: str
    section_label: Optional[str] = None
    content_snippet: str
    similarity_score: float
    change_request_version: int
    retrieved_at: datetime

    # Computed fresh by the API layer (app/api/change_requests.py), never
    # stored - same rule as AnalysisRead.is_outdated, and in fact always
    # set to exactly that same value: this evidence was retrieved as part
    # of one specific analysis run, so it's outdated exactly when that
    # analysis itself is (the change request has been edited since), never
    # independently.
    is_outdated: bool = False
