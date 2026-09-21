"""Risk model - one identified risk for the change."""
from typing import Optional

from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Certainty, RiskCategory, Severity, sa_enum


class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    category: Mapped[RiskCategory] = mapped_column(sa_enum(RiskCategory, "risk_category"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(sa_enum(Severity, "risk_severity"), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0-1.0 - likelihood this risk occurs
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100 combined risk score
    mitigation: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Module 13 (AI Analysis 2.0) ------------------------------------
    # Distinct from `probability`: probability is "how likely is this risk
    # to materialize", confidence is "how sure is the AI about this
    # assessment at all" - a risk can be rated low-probability with high
    # confidence, or high-probability with low confidence. Nullable for the
    # same reason as the other Module 13 additions (pre-existing rows).
    certainty: Mapped[Optional[Certainty]] = mapped_column(sa_enum(Certainty, "risk_certainty"), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="risks")

    def __repr__(self) -> str:
        return f"<Risk id={self.id} category={self.category} severity={self.severity}>"
