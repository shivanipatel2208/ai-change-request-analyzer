"""AffectedComponent model - a system component the change is expected to touch."""
from typing import Optional

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Certainty, ComponentType, ImpactLevel, sa_enum


class AffectedComponent(Base):
    __tablename__ = "affected_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    component_name: Mapped[str] = mapped_column(String(255), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        sa_enum(ComponentType, "affected_component_type"), nullable=False
    )
    impact_level: Mapped[ImpactLevel] = mapped_column(
        sa_enum(ImpactLevel, "affected_component_impact_level"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    # Module 13 (AI Analysis 2.0) - nullable for the same reason as
    # Requirement.certainty above (pre-existing rows predate this column).
    certainty: Mapped[Optional[Certainty]] = mapped_column(
        sa_enum(Certainty, "affected_component_certainty"), nullable=True
    )
    # Module 14 (Analysis & Impact Intelligence) - nullable for the same
    # reason as `certainty` above: pre-existing rows predate this column.
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="affected_components")

    def __repr__(self) -> str:
        return f"<AffectedComponent id={self.id} name={self.component_name!r}>"
