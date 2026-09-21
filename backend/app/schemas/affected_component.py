"""Pydantic schema for AffectedComponent (read-only for now - populated by the AI module, built later)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import Certainty, ComponentType, ImpactLevel


class AffectedComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    component_name: str
    component_type: ComponentType
    impact_level: ImpactLevel
    reason: str
    confidence: float
    # Module 13 (AI Analysis 2.0) - nullable: rows from before this module
    # ran have no epistemic status recorded.
    certainty: Optional[Certainty] = None
    # Module 14 (Analysis & Impact Intelligence) - nullable, same reason.
    evidence: Optional[str] = None
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: the file_path of any of this CR's own repository findings
    # that plausibly relate to this component. Empty (the default) when no
    # repository scan/match has run yet, or none of it overlaps.
    related_files: List[str] = []
