"""ChangeRequest model - the software change request as submitted by a user."""
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import ChangeRequestStatus, Priority, sa_enum


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    business_objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[Priority] = mapped_column(
        sa_enum(Priority, "change_request_priority"), default=Priority.MEDIUM, nullable=False
    )
    status: Mapped[ChangeRequestStatus] = mapped_column(
        sa_enum(ChangeRequestStatus, "change_request_status"),
        default=ChangeRequestStatus.PENDING_ANALYSIS,
        nullable=False,
    )
    # Who the change was requested by. Often the submitter, but not always
    # (e.g. an engineer filing it on behalf of a store manager) - free text
    # on purpose, not every requester has an account here. Nullable so the
    # thousands of rows created before this column existed stay valid; the
    # creation form (Module 4) requires it for anything submitted from now on.
    requested_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Which system/service this change targets, e.g. "POS Backend", "Mobile App".
    target_system: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    desired_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # --- Module 12 (Enterprise Workflow) --------------------------------
    # Nullable (not nullable=False) even though every CR conceptually has a
    # version >= 1: this column was added to an EXISTING table, and the
    # project's home-grown migration (init_db.py::_add_missing_columns)
    # only ALTERs in the column's type, not a NOT NULL/DEFAULT clause - so
    # SQLite would leave every pre-Module-12 row's new column NULL. init_db
    # backfills every existing row to 1 on startup (see
    # _backfill_workflow_data), and application code should still read this
    # as `change_request.current_version or 1` to stay correct even before
    # that backfill has run once.
    current_version: Mapped[Optional[int]] = mapped_column(Integer, default=1, nullable=True)

    # Additional enterprise CR fields requested by Module 12's editing spec
    # (section 2). "Category" is deliberately NOT duplicated here - the app
    # already has a working, AI-derived category (Analysis.category, used
    # throughout the dashboard/list filters); adding a second, manually-
    # editable category on the CR itself would just create two
    # disagreeing sources of truth for the same concept.
    business_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technical_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # e.g. "Production", "Staging" - free text, not an enum: environments
    # vary too much per org to hard-code a fixed list here.
    environment: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Free-text dependency note as stated by the requester/owner - distinct
    # from Analysis.dependencies (the AI-derived, structured Dependency
    # rows on the latest analysis).
    dependencies_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compliance_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-encoded list of strings, e.g. '["payments", "mobile"]' - same
    # "one text column, not a new table" pattern already used for
    # Analysis.security_analysis.
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    creator: Mapped["User"] = relationship(back_populates="change_requests")
    analyses: Mapped[List["Analysis"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan"
    )
    versions: Mapped[List["ChangeRequestVersion"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan", order_by="ChangeRequestVersion.version_number"
    )
    history: Mapped[List["ChangeRequestHistory"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan", order_by="ChangeRequestHistory.created_at"
    )
    assignments: Mapped[List["ChangeRequestAssignment"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan"
    )
    approvals: Mapped[List["Approval"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan"
    )
    comments: Mapped[List["ChangeRequestComment"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan", order_by="ChangeRequestComment.created_at"
    )

    def __repr__(self) -> str:
        return f"<ChangeRequest id={self.id} title={self.title!r}>"
