"""Notification model (Module 12) - lightweight in-app notifications only
(spec: "Do not implement email unless the existing application already
supports it" - it doesn't, so this is in-app only). Created by
app/services/notify.py whenever something happens that a user should know
about: assigned to a CR, tagged for approval, their CR's status changed,
their approval was requested/reminded, they were @mentioned, their AI
analysis went outdated, or a re-approval is needed.

Module 18 Phase 1 (Notifications, My Work & Personal Engineering Queue)
added approval_id: an optional link back to the specific Approval this
notification is about. Nullable, and only ever set today for a
DEADLINE_APPROACHING notification (app/services/deadlines.py) - it's what
lets that check ask "has THIS exact approval already been notified about?"
and never fire twice for the same one, rather than fuzzy-matching on
title/message text. Every other notification type is free to leave it
unset; nothing about them requires it.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import NotificationType, sa_enum


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(sa_enum(NotificationType, "notification_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    change_request_id: Mapped[Optional[int]] = mapped_column(ForeignKey("change_requests.id"), nullable=True)
    # Module 18 Phase 1 - see this model's own docstring above.
    approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("change_request_approvals.id"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<Notification user={self.user_id} type={self.type} read={self.is_read}>"
