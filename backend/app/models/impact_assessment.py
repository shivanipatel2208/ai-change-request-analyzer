"""ImpactAssessment model - Module 14 Phase 4.

One structured finding per fixed lens (Business/Technical/Customer/
Operational/Security/Data/Performance - see app.models.enums.ImpactCategory)
for a given analysis. A brand-new table (not an ALTER on an existing one),
so every column here is NOT NULL from day one - unlike `certainty`/
`confidence` on Requirement/AffectedComponent/Risk, there's no pre-existing
data that predates this column to worry about.

Replaces the frontend-only "Business Impact"/"Technical Impact" text that
AnalysisDashboardPage.jsx's OverviewTab used to assemble itself out of
other fields (business-type Requirements, complexity_reasoning, affected
component names) - that text was never a real, AI-assessed judgment about
business/technical impact specifically, just a repackaging of other
findings. This table is real, per-category AI output instead.
"""
from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Certainty, ImpactCategory, ImpactLevel, sa_enum


class ImpactAssessment(Base):
    __tablename__ = "impact_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    category: Mapped[ImpactCategory] = mapped_column(
        sa_enum(ImpactCategory, "impact_assessment_category"), nullable=False
    )
    impact_level: Mapped[ImpactLevel] = mapped_column(
        sa_enum(ImpactLevel, "impact_assessment_level"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Same certainty/confidence pair every other AI finding in this app
    # carries (see Requirement/AffectedComponent/Risk) - NOT NULL here since
    # this table postdates Module 13, so there's no legacy row without them.
    certainty: Mapped[Certainty] = mapped_column(sa_enum(Certainty, "impact_assessment_certainty"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100

    analysis: Mapped["Analysis"] = relationship(back_populates="impact_assessments")

    def __repr__(self) -> str:
        return f"<ImpactAssessment id={self.id} category={self.category}>"
