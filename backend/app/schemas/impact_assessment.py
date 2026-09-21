"""Pydantic read schema for ImpactAssessment - Module 14 Phase 4."""
from typing import List

from pydantic import BaseModel, ConfigDict

from app.models.enums import Certainty, ImpactCategory, ImpactLevel


class ImpactAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    category: ImpactCategory
    impact_level: ImpactLevel
    description: str
    certainty: Certainty
    confidence: float
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: see AffectedComponentRead.related_files for the full rule.
    related_files: List[str] = []
