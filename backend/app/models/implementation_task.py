"""ImplementationTask model - one task in the suggested implementation plan."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import AssignmentRole, Priority, sa_enum


class ImplementationTask(Base):
    __tablename__ = "implementation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    task: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        sa_enum(Priority, "implementation_task_priority"), default=Priority.MEDIUM, nullable=False
    )
    # Free-form on purpose (e.g. "4h", "2d", "3 story points") - AI-generated
    # estimates don't fit one numeric unit cleanly.
    estimated_effort: Mapped[str] = mapped_column(String(50), nullable=False)
    # Free text / comma-separated references to other tasks this depends on.
    dependencies: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")

    # --- Module 17 Phase 1 (Test Cases & Implementation Plan 2.0) -------
    # Nullable: an ALTER-added column on a table that already has rows from
    # every analysis run before this module existed. Reuses the existing
    # per-CR AssignmentRole vocabulary (Module 12) rather than inventing a
    # second one - this is only ever a *suggestion* of who's suited to a
    # task, never an actual assignment (that stays Module 12's own
    # assignments system, per the architecture lock: no parallel ownership
    # system). None means the AI didn't have enough to suggest one.
    owner_suggestion: Mapped[Optional[AssignmentRole]] = mapped_column(
        sa_enum(AssignmentRole, "implementation_task_owner_suggestion"), nullable=True
    )

    # --- Module 17 Phase 6 (human editing) -------------------------------
    # Same "reviewed_by/reviewed_at, no separate boolean flag" pattern as
    # TestCase.edited_by above and Requirement/SecurityFinding before it.
    edited_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    edit_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="implementation_tasks")

    def __repr__(self) -> str:
        return f"<ImplementationTask id={self.id} task={self.task!r}>"
