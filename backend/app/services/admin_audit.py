"""Module 21: the only place allowed to write SystemAuditLog rows - same
"one writer, append-only" convention as app/services/history.py for
ChangeRequestHistory (spec section 6: "do not allow normal users to edit
audit history"). Every admin action that changes a user, a permission, an
approval rule, or a system setting calls record() rather than constructing
a SystemAuditLog row directly.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.enums import AdminAuditAction
from app.models.system_audit_log import SystemAuditLog


def record(
    db: Session,
    *,
    action: AdminAuditAction,
    actor_user_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> SystemAuditLog:
    event = SystemAuditLog(
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(event)
    db.flush()
    return event
