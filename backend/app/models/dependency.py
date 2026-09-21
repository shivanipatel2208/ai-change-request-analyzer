"""Dependency model - something this change depends on (a service, library, another component, etc.)."""
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import DependencyRelationship, DependencyType, ImpactLevel, Severity, sa_enum


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    dependency_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dependency_type: Mapped[DependencyType] = mapped_column(
        sa_enum(DependencyType, "dependency_type"), nullable=False
    )
    impact_level: Mapped[ImpactLevel] = mapped_column(
        sa_enum(ImpactLevel, "dependency_impact_level"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Module 14 (Analysis & Impact Intelligence) - both nullable: rows from
    # before this module ran have neither recorded.
    relationship_type: Mapped[Optional[DependencyRelationship]] = mapped_column(
        sa_enum(DependencyRelationship, "dependency_relationship_type"), nullable=True
    )
    risk_severity: Mapped[Optional[Severity]] = mapped_column(
        sa_enum(Severity, "dependency_risk_severity"), nullable=True
    )

    analysis: Mapped["Analysis"] = relationship(back_populates="dependencies")

    def __repr__(self) -> str:
        return f"<Dependency id={self.id} name={self.dependency_name!r}>"
