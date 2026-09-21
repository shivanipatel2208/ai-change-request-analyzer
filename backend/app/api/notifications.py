"""Module 12 Phase 5: a user's own in-app notification inbox - assigned to
a CR, tagged for approval (or reminded), an approval was responded to, a
CR's status changed, @mentioned or commented on, an AI analysis went
outdated, or a re-approval is needed (see app/models/notification.py and
app/services/notify.py, the only place that creates these rows). Module 18
Phase 1 added risk escalation, analysis completion, and a computed
deadline-approaching check (see app/services/deadlines.py) - same
notification rows, same one gatekeeper, no second system.

Every route is scoped to `current_user` - there is no way to read or mark
another user's notifications through this API.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationRead
from app.services.deadlines import check_and_notify_approaching_deadlines

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notification]:
    # Module 18 Phase 1: a lazy, opportunistic check - see
    # app/services/deadlines.py's own docstring for why this lives here
    # instead of a background scheduler.
    check_and_notify_approaching_deadlines(db, current_user)
    db.commit()

    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # Module 18 Phase 1: same reasoning as list_notifications above - this
    # endpoint is polled every 30s by the frontend's badge, so it's a
    # reliable, frequent hook for a deadline to actually get noticed.
    check_and_notify_approaching_deadlines(db, current_user)
    db.commit()

    count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .count()
    )
    return {"count": count}


@router.put("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Notification:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.put("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return {"updated": updated}
