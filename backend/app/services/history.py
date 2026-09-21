"""Module 12: the only place allowed to write ChangeRequestHistory rows
(spec section 24, "audit data integrity" - append-only). Every other
service/endpoint that needs to record something calls record_event()
rather than constructing a ChangeRequestHistory row directly, so there's
exactly one place that could ever violate append-only-ness to audit.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.change_request_history import ChangeRequestHistory
from app.models.enums import HistoryAction


def record_event(
    db: Session,
    *,
    change_request_id: int,
    action: HistoryAction,
    user_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    field_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
    version_number: Optional[int] = None,
) -> ChangeRequestHistory:
    event = ChangeRequestHistory(
        change_request_id=change_request_id,
        user_id=user_id,
        actor_label=actor_label,
        action=action,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        version_number=version_number,
    )
    db.add(event)
    db.flush()
    return event
