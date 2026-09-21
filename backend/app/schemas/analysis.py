"""Pydantic schema for Analysis and its related AI-derived tables.

Read-only for now - nothing creates Analysis rows yet (that's the AI
module, built later). Defining the shape now means the API layer can
serialize these tables as soon as something starts writing to them.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import ApprovalRecommendation, ComplexityLevel, ConfidenceLevel
from app.schemas.affected_component import AffectedComponentRead
from app.schemas.change_request import FieldComparisonRead
from app.schemas.clarification_question import ClarificationQuestionRead
from app.schemas.dependency import DependencyRead
from app.schemas.implementation_task import ImplementationTaskRead
from app.schemas.impact_assessment import ImpactAssessmentRead
from app.schemas.knowledge_evidence import KnowledgeEvidenceRead
from app.schemas.requirement import RequirementRead
from app.schemas.risk import RiskRead
from app.schemas.security_finding import SecurityFindingRead
from app.schemas.test_case import TestCaseRead


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_request_id: int
    summary: str
    category: str
    complexity: ComplexityLevel
    risk_score: float
    confidence_score: float
    recommendation: Optional[ApprovalRecommendation] = None
    created_at: datetime

    # Module 6 - narrative AI output that doesn't have its own table.
    # security_analysis is stored as a JSON string; left as-is here (the
    # frontend can parse it, or a later module can give it its own schema).
    classification_reason: Optional[str] = None
    complexity_reasoning: Optional[str] = None
    security_analysis: Optional[str] = None
    effort_estimate: Optional[str] = None
    recommendation_reasoning: Optional[str] = None

    requirements: List[RequirementRead] = []
    affected_components: List[AffectedComponentRead] = []
    dependencies: List[DependencyRead] = []
    risks: List[RiskRead] = []
    # Module 14 Phase 4
    impact_assessments: List[ImpactAssessmentRead] = []
    # Module 14 Phase 5
    security_findings: List[SecurityFindingRead] = []
    clarification_questions: List[ClarificationQuestionRead] = []
    test_cases: List[TestCaseRead] = []
    implementation_tasks: List[ImplementationTaskRead] = []
    # Module 16 (Project Knowledge Base & RAG) Phase 4/5 - the knowledge-
    # base chunks (if any) retrieved and given to the AI as grounding
    # context for this analysis. is_outdated on each entry is set by the
    # API layer to match this analysis's own is_outdated below (see
    # KnowledgeEvidenceRead's own docstring for why there's only one
    # staleness axis here).
    knowledge_evidence: List[KnowledgeEvidenceRead] = []

    # Module 13 (AI Analysis 2.0) - which CR version this analysis ran
    # against (None only for the handful of pre-Module-12 rows init_db
    # hasn't backfilled yet on a database that's never been started up
    # since - see app/database/init_db.py::_backfill_workflow_data).
    change_request_version: Optional[int] = None

    # Module 13 Phase 3: computed fresh by the endpoint (never stored -
    # same rule as ChangeRequestDetail.is_analysis_outdated), true when the
    # change request has been edited since this was the CR's *latest*
    # analysis. Endpoints that return an existing analysis (GET
    # .../analysis, POST .../analyze) set this explicitly after building
    # the response; it defaults to False so nothing breaks if a caller
    # forgets to set it or feeds this schema a plain historical row.
    is_outdated: bool = False

    # Module 13 Phase 4: a single computed (not AI-written) sentence
    # combining `recommendation` with what it actually takes to move this
    # change request forward - see
    # app/services/workflow_rules.py::recommendation_summary. Same
    # "computed, never stored" rule as is_outdated above.
    workflow_recommendation: Optional[str] = None

    # Module 14 (Analysis & Impact Intelligence) - both nullable: rows from
    # before this module ran have neither recorded.
    complexity_confidence: Optional[ConfidenceLevel] = None
    effort_confidence: Optional[ConfidenceLevel] = None


class AnalysisSummaryRead(BaseModel):
    """Module 13 Phase 2: a lightweight, one-line-per-analysis summary for
    GET /{id}/analyses - lets a caller (the frontend's future analysis
    history picker, or a person poking at the API directly) discover which
    analysis ids exist and pick two to compare, without pulling every
    child table for every past analysis."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    change_request_version: Optional[int] = None
    created_at: datetime
    category: str
    complexity: ComplexityLevel
    risk_score: float
    confidence_score: float
    recommendation: Optional[ApprovalRecommendation] = None


class AnalysisDeltaResponse(BaseModel):
    """Module 13 Phase 2: a computed (not AI-written) diff between two
    analyses for the same change request - see
    app/services/analysis_delta.py for why computed was chosen over an
    AI-written explanation, and for the honest limitation on the
    added/removed lists below (text-matched, not semantically matched)."""

    from_analysis_id: int
    to_analysis_id: int
    from_version: Optional[int] = None
    to_version: Optional[int] = None
    fields: List[FieldComparisonRead]
    requirements_added: List[str]
    requirements_removed: List[str]
    affected_components_added: List[str]
    affected_components_removed: List[str]
    is_significant_change: bool
    significant_change_reasons: List[str]
