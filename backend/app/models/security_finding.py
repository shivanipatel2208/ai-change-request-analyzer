"""SecurityFinding model - Module 14 Phase 5.

One structured finding per fixed lens (Authentication/Authorization/Data
Protection/Secrets/API Security/Rate Limiting/Privacy/Audit Logging/
Compliance - see app.models.enums.SecurityCategory) for a given analysis.
Replaces the old flat `Analysis.security_analysis` JSON blob
({"concerns": [...], "summary": "..."}) as the primary security content
going forward - that column is kept (nullable, untouched) purely so
analyses created before this module still render something in the
Security tab, per the "never silently break old data" rule this app
follows throughout.

A brand-new table, so every column here is NOT NULL from day one - same
reasoning as ImpactAssessment (app/models/impact_assessment.py).
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import SecurityCategory, SecurityFindingStatus, Severity, sa_enum


class SecurityFinding(Base):
    __tablename__ = "security_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    category: Mapped[SecurityCategory] = mapped_column(
        sa_enum(SecurityCategory, "security_finding_category"), nullable=False
    )
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(sa_enum(Severity, "security_finding_severity"), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    # AI sets OPEN/NOT_APPLICABLE only; a human moves it to ACKNOWLEDGED/
    # RESOLVED later (Module 14 Phase 6 - not yet built).
    status: Mapped[SecurityFindingStatus] = mapped_column(
        sa_enum(SecurityFindingStatus, "security_finding_status"), nullable=False
    )

    # --- Module 14 Phase 6 (human review) -------------------------------
    # Who last changed `status` and when, plus their optional note -
    # nullable: an ALTER-added column on a table that already has rows
    # from Phase 5 (this app's real, populated database), same reasoning
    # as Requirement.reviewed_by/reviewed_at.
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="security_findings")

    def __repr__(self) -> str:
        return f"<SecurityFinding id={self.id} category={self.category}>"
