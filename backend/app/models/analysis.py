"""Analysis model - one AI-generated analysis run for a change request.

A change request can be (re-)analyzed more than once (e.g. after it's
edited), so this is one-to-many from ChangeRequest, not one-to-one.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import ApprovalRecommendation, ComplexityLevel, ConfidenceLevel, sa_enum


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Free text on purpose: AI-generated categorization (e.g. "feature",
    # "bugfix", "infrastructure") is open-ended, not a fixed vocabulary the
    # app enforces.
    category: Mapped[str] = mapped_column(Text, nullable=False)
    complexity: Mapped[ComplexityLevel] = mapped_column(
        sa_enum(ComplexityLevel, "analysis_complexity"), nullable=False
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    recommendation: Mapped[Optional[ApprovalRecommendation]] = mapped_column(
        sa_enum(ApprovalRecommendation, "analysis_recommendation"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # --- Module 6 (AI Analysis Engine) ---------------------------------
    # These hold narrative AI output that doesn't have its own relational
    # table (unlike requirements/risks/etc. below, which do). All nullable
    # so existing rows created before this module stay valid.
    classification_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The AI's stated reasoning for the complexity level (Module 7's Overview
    # tab needs this for "technical impact") - was validated but silently
    # dropped during persistence until now.
    complexity_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-encoded {"concerns": [str, ...], "summary": str} - structured
    # enough to be worth keeping as one blob rather than a whole new table.
    security_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Human-readable range, e.g. "Backend: 2-3 days, Frontend: 1-2 days,
    # Testing: 2 days, Total: 5-8 developer-days" - deliberately a string,
    # not a number, per the spec ("a range, not fake precision").
    effort_estimate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Module 14 (Analysis & Impact Intelligence) --------------------
    # A coarse Low/Medium/High confidence in the complexity level and the
    # effort estimate respectively - both nullable: rows from before this
    # module ran have neither recorded. Deliberately separate from
    # `confidence_score` above (that's the AI's confidence in its overall
    # classification, not specifically in these two estimates).
    complexity_confidence: Mapped[Optional[ConfidenceLevel]] = mapped_column(
        sa_enum(ConfidenceLevel, "analysis_complexity_confidence"), nullable=True
    )
    effort_confidence: Mapped[Optional[ConfidenceLevel]] = mapped_column(
        sa_enum(ConfidenceLevel, "analysis_effort_confidence"), nullable=True
    )
    # The full validated AI JSON response, verbatim, for audit/debugging -
    # not surfaced through the API. A safety net in case a future module
    # needs a field that didn't get its own column.
    raw_ai_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Module 12 (Enterprise Workflow) --------------------------------
    # Which ChangeRequest.current_version this analysis was run against.
    # Nullable for the same reason as ChangeRequest.current_version above
    # (ALTER-added column on an existing table); init_db backfills existing
    # rows to 1. "Is the current analysis outdated?" is computed, never
    # stored, by comparing this to the CR's current_version - see
    # app/services/workflow_rules.py::is_analysis_outdated().
    change_request_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="analyses")

    requirements: Mapped[List["Requirement"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    affected_components: Mapped[List["AffectedComponent"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    dependencies: Mapped[List["Dependency"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    risks: Mapped[List["Risk"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    # Module 14 Phase 4
    impact_assessments: Mapped[List["ImpactAssessment"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    # Module 14 Phase 5
    security_findings: Mapped[List["SecurityFinding"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    clarification_questions: Mapped[List["ClarificationQuestion"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    test_cases: Mapped[List["TestCase"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    implementation_tasks: Mapped[List["ImplementationTask"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    # Module 16 (Project Knowledge Base & RAG) Phase 4/5 - which knowledge-
    # base chunks were retrieved and given to the AI as grounding context
    # for this specific analysis run (empty for any analysis run before
    # this module existed, or when the knowledge base had nothing
    # plausibly relevant).
    knowledge_evidence: Mapped[List["KnowledgeEvidence"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Analysis id={self.id} change_request_id={self.change_request_id}>"
