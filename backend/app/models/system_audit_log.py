"""SystemAuditLog model (Module 21) - the system-level counterpart to
ChangeRequestHistory. ChangeRequestHistory is always scoped to one change
request; this table is for admin/configuration actions that belong to no
single change request at all - a role change, an account deactivation, an
edited approval rule, a changed permission or system setting.

Append-only, same as ChangeRequestHistory - see app/services/admin_audit.py,
the only place that's allowed to insert into this table (spec section 6:
"Do not allow normal users to edit audit history").

actor_user_id is nullable for the same reason ChangeRequestHistory.user_id
is: a rare system-generated entry with no human actor would use
actor_label instead, though in practice every Module 21 action so far is
always something an admin did.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import AdminAuditAction, sa_enum


class SystemAuditLog(Base):
    __tablename__ = "system_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[AdminAuditAction] = mapped_column(
        sa_enum(AdminAuditAction, "admin_audit_action"), nullable=False, index=True
    )
    # What this action was about - e.g. target_type="user", target_id="42"
    # for a role change on user #42; target_type="approval_rule",
    # target_id="7" for an edited rule. Loose (plain strings, not a
    # foreign key) on purpose - the target can be a user, a permission
    # row, a rule, or a system setting key, and this log must still be
    # readable even after the target itself is later deleted.
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<SystemAuditLog action={self.action} target={self.target_type}:{self.target_id}>"
