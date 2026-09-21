"""ClarificationQuestion model - a question worth answering before the change can be safely approved."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import Priority, sa_enum


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        sa_enum(Priority, "clarification_question_priority"), default=Priority.MEDIUM, nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # A human answering the AI's question directly, right where it's asked -
    # rather than "resolved" being an unreachable dead-end flag nothing ever
    # set. Nullable: None means nobody has answered yet. Answering also sets
    # resolved=True (see app/api/change_requests.py::answer_clarification_
    # question); the two are always kept in sync from that one endpoint, so
    # nothing else needs to check both.
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answered_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    analysis: Mapped["Analysis"] = relationship(back_populates="clarification_questions")

    def __repr__(self) -> str:
        return f"<ClarificationQuestion id={self.id} resolved={self.resolved}>"
