"""ChangeRequestHistory model (Module 12) - the append-only audit trail.

This is the backbone of the "Activity" tab: every meaningful thing that
happens to a change request gets one row here, in enough detail to answer
"who did it, what did they change, when, from what, to what, and why" -
never a vague "Change Request updated." Rows are never edited or deleted
by normal application code (see app/services/history.py, the only place
that's allowed to insert into this table) - that's the "audit data
integrity" requirement (spec section 24).

user_id is nullable to allow one specific system actor: the AI Analyzer
itself recording "AI Analysis Completed" / "AI Analysis Invalidated"
events. When user_id is None, actor_label carries a human-readable name
for that actor (e.g. "AI Analyzer") instead.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import HistoryAction, sa_enum


class ChangeRequestHistory(Base):
    __tablename__ = "change_request_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Set only when user_id is None (a system actor, e.g. "AI Analyzer").
    actor_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[HistoryAction] = mapped_column(sa_enum(HistoryAction, "history_action"), nullable=False, index=True)
    # Set for FIELD_CHANGED events (e.g. "priority", "target_system"); None
    # for events that aren't about one specific field (status changes use
    # their own old/new below with field_name="status", but STATUS_CHANGED
    # is its own action so the timeline can render it with a distinct icon).
    field_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The CR version this event happened at/produced, where relevant (e.g.
    # a FIELD_CHANGED event's new_value belongs to the version it created).
    version_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="history")
    user: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<ChangeRequestHistory cr={self.change_request_id} action={self.action}>"
