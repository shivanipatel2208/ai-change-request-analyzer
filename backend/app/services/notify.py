"""Module 12 Phase 5: the one place that creates Notification rows - same
"one gatekeeper" pattern as app/services/history.py for the audit trail, so
there's exactly one place that could ever get a notification's shape wrong.

In-app only (spec: "Do not implement email unless the existing application
already supports it" - it doesn't). Every event listed on
app/models/notification.py's own docstring is raised from here:
assigned to a CR (app/api/change_requests.py::create_assignment), tagged
for approval / reminded (create_approval_request / remind_approval), their
CR's status changed (change_status), their approval was responded to
(respond_to_approval_request), they were @mentioned or someone commented
(app/services/comments.py), their AI analysis went outdated, or a
re-approval is needed (both app/services/versioning.py).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.enums import NotificationType
from app.models.notification import Notification


def notify(
    db: Session,
    *,
    user_id: int,
    type: NotificationType,
    title: str,
    message: str,
    change_request_id: Optional[int] = None,
    approval_id: Optional[int] = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        change_request_id=change_request_id,
        approval_id=approval_id,
    )
    db.add(notification)
    db.flush()
    return notification
