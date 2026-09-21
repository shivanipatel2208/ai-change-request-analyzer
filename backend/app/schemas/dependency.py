"""Pydantic schema for Dependency (read-only for now - populated by the AI module, built later)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import DependencyRelationship, DependencyType, ImpactLevel, Severity


class DependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    dependency_name: str
    dependency_type: DependencyType
    impact_level: ImpactLevel
    reason: str
    # Module 14 (Analysis & Impact Intelligence) - both nullable: rows from
    # before this module ran have neither recorded.
    relationship_type: Optional[DependencyRelationship] = None
    risk_severity: Optional[Severity] = None
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: see AffectedComponentRead.related_files for the full rule.
    related_files: List[str] = []
