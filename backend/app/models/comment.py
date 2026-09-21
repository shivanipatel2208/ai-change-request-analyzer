"""ChangeRequestComment model (Module 12) - discussion thread on a change
request. Supports one level of replies via parent_id (spec: "Reply where
practical" - a flat two-level thread is practical here, a full nested tree
is not needed) and @mentions are parsed out of `body` at write time by
app/services/mentions.py, which is also what creates the resulting
notifications - nothing about mentions is stored structurally beyond the
plain text itself.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ChangeRequestComment(Base):
    __tablename__ = "change_request_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("change_request_comments.id"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="comments")
    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<ChangeRequestComment cr={self.change_request_id} user={self.user_id}>"
