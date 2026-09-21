"""Module 18 Phase 1 (Notifications, My Work & Personal Engineering Queue):
turns a PENDING approval's own due_date into a real DEADLINE_APPROACHING
notification - without a background job scheduler (per this project's own
"keep architecture minimal" rule, no Docker/Redis/Kubernetes cron runner is
being added just for this).

Instead, this is a lazy, opportunistic check: check_and_notify_approaching_
deadlines() is called from the notification-inbox endpoints themselves
(app/api/notifications.py), which the frontend already polls every 30
seconds for the unread-count badge - so a deadline is noticed the next
time its own approver's notifications are read, same responsiveness as
everything else in this app's notification system, with zero new moving
parts.

Scoped to exactly one user's own PENDING approvals (never a full-table
scan across every user in the system) - cheap enough to run on every
notification read. Fires at most once, ever, per Approval - idempotency is
enforced by checking for an existing DEADLINE_APPROACHING notification
carrying that exact approval_id (see Notification.approval_id's own
docstring) before creating a new one, so a due-soon approval that later
becomes overdue is never re-notified a second time for the same deadline.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.approval import Approval
from app.models.enums import ApprovalStatus, NotificationType
from app.models.notification import Notification
from app.models.user import User
from app.services import notify as notify_service
from app.services.approvals import DUE_SOON_WINDOW, approval_due_status
from app.services.workflow_rules import APPROVAL_TYPE_LABELS


def check_and_notify_approaching_deadlines(db: Session, user: User) -> None:
    """Looks only at `user`'s own still-PENDING approvals with a due_date
    that's already within the "due soon" window (or already overdue), and
    creates one DEADLINE_APPROACHING notification per approval that
    doesn't already have one. Callers are responsible for committing - see
    app/api/notifications.py."""
    now = datetime.utcnow()
    candidates = (
        db.query(Approval)
        .filter(
            Approval.approver_id == user.id,
            Approval.status == ApprovalStatus.PENDING,
            Approval.due_date.isnot(None),
            Approval.due_date <= now + DUE_SOON_WINDOW,
        )
        .all()
    )
    if not candidates:
        return

    for approval in candidates:
        # approval_due_status re-checks PENDING/due_date itself - the query
        # above is just a cheap pre-filter to avoid loading every approval
        # this user has ever been tagged on.
        if approval_due_status(approval, now=now) is None:
            continue

        already_notified = (
            db.query(Notification)
            .filter(
                Notification.type == NotificationType.DEADLINE_APPROACHING,
                Notification.approval_id == approval.id,
            )
            .first()
        )
        if already_notified is not None:
            continue

        type_label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
        due_status = approval_due_status(approval, now=now)
        if due_status == "overdue":
            title = f"{type_label} approval on CR-{approval.change_request_id} is overdue"
            message = f"Your {type_label} approval was due {approval.due_date.strftime('%b %d, %Y')} and is still pending."
        else:
            title = f"{type_label} approval on CR-{approval.change_request_id} is due soon"
            message = f"Your {type_label} approval is due {approval.due_date.strftime('%b %d, %Y')}."

        notify_service.notify(
            db,
            user_id=user.id,
            type=NotificationType.DEADLINE_APPROACHING,
            title=title,
            message=message,
            change_request_id=approval.change_request_id,
            approval_id=approval.id,
        )
