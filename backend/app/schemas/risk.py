"""Pydantic schema for Risk (read-only for now - populated by the AI module, built later)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import Certainty, RiskCategory, Severity


class RiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    category: RiskCategory
    description: str
    severity: Severity
    probability: float
    score: float
    mitigation: str
    # Module 13 (AI Analysis 2.0) - all nullable: rows from before this
    # module ran have no epistemic status recorded.
    certainty: Optional[Certainty] = None
    confidence: Optional[float] = None
    evidence: Optional[str] = None
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: see AffectedComponentRead.related_files for the full rule.
    related_files: List[str] = []
