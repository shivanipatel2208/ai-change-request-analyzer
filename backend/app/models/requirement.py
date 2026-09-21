"""Requirement model - one extracted requirement belonging to an analysis."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Certainty, Priority, RequirementType, ReviewStatus, sa_enum


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    requirement_type: Mapped[RequirementType] = mapped_column(
        sa_enum(RequirementType, "requirement_type"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        sa_enum(Priority, "requirement_priority"), default=Priority.MEDIUM, nullable=False
    )

    # --- Module 13 (AI Analysis 2.0) ------------------------------------
    # Nullable: an ALTER-added column on an existing table, same reasoning
    # as ChangeRequest.current_version - rows from before this module ran
    # simply have no epistemic status recorded, and the UI treats that as
    # "not evaluated" rather than guessing one.
    certainty: Mapped[Optional[Certainty]] = mapped_column(
        sa_enum(Certainty, "requirement_certainty"), nullable=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Module 14 Phase 6 (human review) -------------------------------
    # A human reviewer's verdict, entirely separate from `certainty`/
    # `confidence`/`evidence` above - reviewing NEVER touches those AI
    # columns (see ReviewStatus's docstring). All nullable: an ALTER-added
    # column on an already-populated table, and NULL here specifically
    # means "no human has reviewed this yet."
    review_status: Mapped[Optional[ReviewStatus]] = mapped_column(
        sa_enum(ReviewStatus, "requirement_review_status"), nullable=True
    )
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="requirements")

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} type={self.requirement_type}>"
