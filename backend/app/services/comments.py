"""Module 12 Phase 5: posting a comment - creates the row, records it on
the audit trail, and figures out who to notify. One comment notifies each
recipient exactly once: someone explicitly @mentioned gets the more
specific MENTIONED notification; the CR's creator and everyone currently
assigned to it (its "interested parties") get a plain COMMENT_ADDED one
instead, unless they were already covered by a mention. The author never
notifies themselves.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.comment import ChangeRequestComment
from app.models.enums import HistoryAction, NotificationType
from app.models.user import User
from app.services import history
from app.services import notify as notify_service
from app.services.mentions import extract_mentioned_users

_PREVIEW_LIMIT = 200


def _preview(body: str) -> str:
    body = body.strip()
    return body if len(body) <= _PREVIEW_LIMIT else body[: _PREVIEW_LIMIT - 3] + "..."


def create_comment(
    db: Session,
    change_request: ChangeRequest,
    *,
    author: User,
    body: str,
    parent_id: Optional[int] = None,
) -> ChangeRequestComment:
    comment = ChangeRequestComment(
        change_request_id=change_request.id,
        user_id=author.id,
        parent_id=parent_id,
        body=body,
    )
    db.add(comment)
    db.flush()

    preview = _preview(body)
    history.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.COMMENT_ADDED,
        user_id=author.id,
        new_value=preview,
        version_number=change_request.current_version or 1,
    )

    all_users = db.query(User).all()
    mentioned = extract_mentioned_users(body, all_users, exclude_user_id=author.id)
    mentioned_ids = {u.id for u in mentioned}

    for user in mentioned:
        history.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.MENTIONED,
            user_id=author.id,
            new_value=f"{user.name} was mentioned",
            version_number=change_request.current_version or 1,
        )
        notify_service.notify(
            db,
            user_id=user.id,
            type=NotificationType.MENTIONED,
            title=f"You were mentioned on CR-{change_request.id}",
            message=f"{author.name} mentioned you: “{preview}”",
            change_request_id=change_request.id,
        )

    interested_ids = {change_request.created_by} | {a.user_id for a in change_request.assignments}
    interested_ids.discard(author.id)
    for user_id in interested_ids - mentioned_ids:
        notify_service.notify(
            db,
            user_id=user_id,
            type=NotificationType.COMMENT_ADDED,
            title=f"New comment on CR-{change_request.id}",
            message=f"{author.name} commented: “{preview}”",
            change_request_id=change_request.id,
        )

    return comment
