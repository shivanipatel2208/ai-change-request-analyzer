"""TestCase model - a suggested test case for verifying the change."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Priority, TestType, sa_enum


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    test_id: Mapped[str] = mapped_column(String(50), nullable=False)  # human-readable code, e.g. "TC-001"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    test_type: Mapped[TestType] = mapped_column(sa_enum(TestType, "test_case_type"), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        sa_enum(Priority, "test_case_priority"), default=Priority.MEDIUM, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Module 17 Phase 1 (Test Cases & Implementation Plan 2.0) -------
    # Nullable: ALTER-added columns on a table that already has rows from
    # every analysis run before this module existed - same reasoning as
    # Requirement.certainty/confidence/evidence. `steps` is stored as a
    # JSON-encoded list[str] (one step per element, in order) - the same
    # "one text column, not a new table" pattern already used for
    # ChangeRequest.tags and KnowledgeChunk.embedding - parsed back into a
    # real list by TestCaseRead's own field_validator.
    preconditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Module 17 Phase 6 (human editing) -------------------------------
    # Who last edited this test case's own content and when, plus their
    # optional reason - exactly the same "reviewed_by/reviewed_at, no
    # separate boolean flag" pattern Requirement and SecurityFinding already
    # use (NULL edited_by means "the AI's original content, never touched by
    # a human"). Editing updates title/description/etc. in place; the AI's
    # prior wording is never lost because it's permanently preserved as the
    # old_value on the TEST_CASE_EDITED history row this creates - never a
    # second copy kept on this row itself.
    edited_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    edit_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<TestCase id={self.id} test_id={self.test_id!r}>"
