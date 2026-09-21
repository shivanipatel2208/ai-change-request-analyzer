"""Module 18 Phase 3 (Notifications, My Work & Personal Engineering
Queue): a personal dashboard - "what's on my plate right now" - built
entirely on top of tables Module 12 (assignments/approvals/notifications)
and this module's own Phase 1/2 additions already own. No new tables, no
parallel notification/assignment system (per the architecture lock) - this
is purely a set of read-only, differently-sliced views over existing data.

Every query below filters at the database level (an AssignmentRole/
ApprovalStatus/user_id condition in the SQL WHERE clause, or an `.any(...)`
correlated-subquery filter on the ORM relationship) rather than loading
every change request or every approval in the system and filtering in
Python - spec section 7's own "keep queries efficient" requirement. The
one exception is the small, already-narrowed result set each query
returns, where a per-row computation (risk bucket, due status, which
roles this one user holds) is cheap because it only ever runs over rows
that already matched the SQL filter.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.enums import ApprovalStatus, AssignmentRole, ChangeRequestStatus, NotificationType
from app.models.notification import Notification
from app.models.user import User
from app.schemas.my_work import (
    ChangesRequestedItem,
    MyApprovalItem,
    MyAssignmentItem,
    MyChangeRequestItem,
    MyReviewItem,
    MyWorkSummary,
)
from app.schemas.notification import NotificationRead
from app.services import approvals as approvals_service
from app.services.workflow_rules import APPROVAL_STATUS_LABELS, APPROVAL_TYPE_LABELS, risk_bucket

router = APIRouter(prefix="/api/my-work", tags=["my-work"])

REVIEW_ROLES = {
    AssignmentRole.REVIEWER,
    AssignmentRole.TECHNICAL_LEAD,
    AssignmentRole.SECURITY_REVIEWER,
    AssignmentRole.OWNER,
}


# --- shared per-row helpers (deliberately duplicated in spirit from
# app/api/change_requests.py's own _latest_analysis/_effective_status -
# each module owns its own small helpers rather than importing another
# module's underscore-prefixed ones, same convention
# repository_linkage.py/traceability_linkage.py already follow) ----------


def _latest_analysis(change_request: ChangeRequest) -> Optional[Analysis]:
    if not change_request.analyses:
        return None
    return max(change_request.analyses, key=lambda a: a.created_at)


def _effective_status(change_request: ChangeRequest, latest: Optional[Analysis]) -> str:
    if change_request.status == ChangeRequestStatus.APPROVED:
        return "approved"
    if change_request.status == ChangeRequestStatus.DRAFT:
        return "draft"
    if latest is None:
        return "pending_analysis"
    if any(not question.resolved for question in latest.clarification_questions):
        return "requires_clarification"
    return "completed"


def _risk_for(change_request: ChangeRequest) -> Optional[str]:
    latest = _latest_analysis(change_request)
    return risk_bucket(latest.risk_score) if latest else None


def _cr_query(db: Session):
    return db.query(ChangeRequest).options(
        selectinload(ChangeRequest.analyses).selectinload(Analysis.clarification_questions),
        selectinload(ChangeRequest.assignments),
    )


@router.get("/summary", response_model=MyWorkSummary)
def my_work_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyWorkSummary:
    """Cheap counts only (see MyWorkSummary's own docstring) - each number
    here is its own small COUNT-style query, not a byproduct of loading
    every row from the section endpoints below."""
    my_change_requests = (
        db.query(ChangeRequest).filter(ChangeRequest.created_by == current_user.id).count()
    )
    my_approvals_pending = (
        db.query(Approval)
        .filter(Approval.approver_id == current_user.id, Approval.status == ApprovalStatus.PENDING)
        .count()
    )
    my_reviews = (
        db.query(ChangeRequest)
        .filter(
            ChangeRequest.assignments.any(
                and_(
                    ChangeRequestAssignment.user_id == current_user.id,
                    ChangeRequestAssignment.role.in_(REVIEW_ROLES),
                )
            )
        )
        .count()
    )
    my_assignments = (
        db.query(ChangeRequest)
        .filter(ChangeRequest.assignments.any(ChangeRequestAssignment.user_id == current_user.id))
        .count()
    )
    changes_requested_from_me = (
        db.query(ChangeRequest)
        .filter(
            ChangeRequest.created_by == current_user.id,
            ChangeRequest.approvals.any(Approval.status == ApprovalStatus.CHANGES_REQUESTED),
        )
        .count()
    )
    unread_mentions = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.type == NotificationType.MENTIONED,
            Notification.is_read.is_(False),
        )
        .count()
    )
    # Overdue is computed (never stored), so this can't be a single SQL
    # COUNT the way the others above are - but it's still scoped at the
    # database level to just this user's own still-PENDING approvals with
    # a due_date at all, the same cheap pre-filter
    # app/services/deadlines.py already uses, before the per-row
    # approval_due_status() check.
    pending_with_due_date = (
        db.query(Approval)
        .filter(
            Approval.approver_id == current_user.id,
            Approval.status == ApprovalStatus.PENDING,
            Approval.due_date.isnot(None),
        )
        .all()
    )
    overdue_approvals = sum(
        1 for a in pending_with_due_date if approvals_service.approval_due_status(a) == "overdue"
    )

    return MyWorkSummary(
        my_change_requests=my_change_requests,
        my_approvals_pending=my_approvals_pending,
        my_reviews=my_reviews,
        my_assignments=my_assignments,
        changes_requested_from_me=changes_requested_from_me,
        unread_mentions=unread_mentions,
        overdue_approvals=overdue_approvals,
    )


@router.get("/change-requests", response_model=list[MyChangeRequestItem])
def my_change_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyChangeRequestItem]:
    """Change requests the current user personally created - filtered at
    the database level (ChangeRequest.created_by == current_user.id), not
    by loading every change request in the system."""
    rows = (
        _cr_query(db)
        .filter(ChangeRequest.created_by == current_user.id)
        .order_by(ChangeRequest.created_at.desc())
        .all()
    )
    return [
        MyChangeRequestItem(
            id=cr.id,
            title=cr.title,
            status=_effective_status(cr, _latest_analysis(cr)),
            priority=cr.priority,
            risk=_risk_for(cr),
            created_at=cr.created_at,
        )
        for cr in rows
    ]


@router.get("/approvals", response_model=list[MyApprovalItem])
def my_approvals(
    status_filter: Optional[str] = Query(
        "pending",
        alias="status",
        description='"pending" (default - the actual queue of things waiting on you), or "all" for every approval you\'ve ever been tagged on.',
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyApprovalItem]:
    """Every sign-off tagged to the current user (spec section 4) -
    filtered at the database level by Approval.approver_id, never by
    loading every approval in the system. Defaults to PENDING only (the
    actual personal queue); pass ?status=all for the full history."""
    query = (
        db.query(Approval)
        .options(
            selectinload(Approval.requested_by_user),
            selectinload(Approval.change_request).selectinload(ChangeRequest.analyses),
        )
        .filter(Approval.approver_id == current_user.id)
    )
    if status_filter != "all":
        query = query.filter(Approval.status == ApprovalStatus.PENDING)

    rows = query.order_by(Approval.requested_at.desc()).all()

    items: list[MyApprovalItem] = []
    for approval in rows:
        change_request = approval.change_request
        items.append(
            MyApprovalItem(
                id=approval.id,
                change_request_id=change_request.id,
                change_request_title=change_request.title,
                approval_type=approval.approval_type,
                approval_type_label=APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value),
                status=approval.status,
                status_label=APPROVAL_STATUS_LABELS.get(approval.status, approval.status.value),
                requested_by_name=approval.requested_by_user.name,
                requested_at=approval.requested_at,
                due_date=approval.due_date,
                due_status=approvals_service.approval_due_status(approval),
                risk=_risk_for(change_request),
            )
        )
    return items


@router.get("/reviews", response_model=list[MyReviewItem])
def my_reviews(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyReviewItem]:
    """Change requests where the current user holds at least one of
    Reviewer/Technical Lead/Security Reviewer/Owner (spec section 5) -
    filtered at the database level via a correlated `.any(...)` on the
    assignments relationship, never by loading every change request."""
    rows = (
        _cr_query(db)
        .filter(
            ChangeRequest.assignments.any(
                and_(
                    ChangeRequestAssignment.user_id == current_user.id,
                    ChangeRequestAssignment.role.in_(REVIEW_ROLES),
                )
            )
        )
        .order_by(ChangeRequest.created_at.desc())
        .all()
    )
    return [
        MyReviewItem(
            change_request_id=cr.id,
            title=cr.title,
            status=_effective_status(cr, _latest_analysis(cr)),
            priority=cr.priority,
            risk=_risk_for(cr),
            roles=sorted(
                (a.role for a in cr.assignments if a.user_id == current_user.id and a.role in REVIEW_ROLES),
                key=lambda r: r.value,
            ),
        )
        for cr in rows
    ]


@router.get("/assignments", response_model=list[MyAssignmentItem])
def my_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyAssignmentItem]:
    """Every change request the current user holds ANY assignment role on
    - broader than /reviews above. Same database-level `.any(...)` filter
    already established by list_change_requests's own assigned_to_me
    query, reused here rather than re-invented."""
    rows = (
        _cr_query(db)
        .filter(ChangeRequest.assignments.any(ChangeRequestAssignment.user_id == current_user.id))
        .order_by(ChangeRequest.created_at.desc())
        .all()
    )
    return [
        MyAssignmentItem(
            change_request_id=cr.id,
            title=cr.title,
            status=_effective_status(cr, _latest_analysis(cr)),
            priority=cr.priority,
            risk=_risk_for(cr),
            roles=sorted(
                (a.role for a in cr.assignments if a.user_id == current_user.id),
                key=lambda r: r.value,
            ),
        )
        for cr in rows
    ]


@router.get("/changes-requested", response_model=list[ChangesRequestedItem])
def changes_requested_from_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChangesRequestedItem]:
    """Change requests the current user OWNS (created) where at least one
    approver has responded Changes Requested - "someone is waiting on ME
    to revise" (confirmed interpretation - see this module's own planning
    discussion). Filtered at the database level by created_by plus a
    correlated `.any(...)` on the approvals relationship.

    Known simplification (disclosed, not a bug): this shows every CR with
    ANY Changes-Requested approval ever recorded, even one from an older
    CR version the owner may have already addressed with a later edit -
    there's no existing "has this feedback been addressed" flag anywhere
    else in this app to check against (a resolved approval's own
    is_outdated is always False, by design - see
    app/services/approvals.py::is_approval_outdated's own docstring)."""
    rows = (
        db.query(ChangeRequest)
        .options(
            selectinload(ChangeRequest.approvals).selectinload(Approval.approver),
        )
        .filter(
            ChangeRequest.created_by == current_user.id,
            ChangeRequest.approvals.any(Approval.status == ApprovalStatus.CHANGES_REQUESTED),
        )
        .order_by(ChangeRequest.created_at.desc())
        .all()
    )

    items: list[ChangesRequestedItem] = []
    for cr in rows:
        changes_requested_approvals = [a for a in cr.approvals if a.status == ApprovalStatus.CHANGES_REQUESTED]
        # A CR can have more than one Changes-Requested approval (e.g. two
        # different approval types both sent back) - one row per approval,
        # newest response first, so nothing is silently collapsed away.
        for approval in sorted(
            changes_requested_approvals, key=lambda a: a.responded_at or a.requested_at, reverse=True
        ):
            items.append(
                ChangesRequestedItem(
                    change_request_id=cr.id,
                    title=cr.title,
                    approval_type=approval.approval_type,
                    approval_type_label=APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value),
                    approver_name=approval.approver.name,
                    responded_at=approval.responded_at,
                    comment=approval.comment,
                )
            )
    return items


@router.get("/mentions", response_model=list[NotificationRead])
def my_mentions(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notification]:
    """Every time the current user was @mentioned (spec section 3's
    "Mentions" section) - reuses the existing Notification row (type=
    MENTIONED) rather than a second, parallel mentions table; mirrors
    app/api/notifications.py::list_notifications's own shape, just
    pre-filtered to this one type."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.type == NotificationType.MENTIONED
    )
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/overdue", response_model=list[MyApprovalItem])
def overdue_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyApprovalItem]:
    """Every still-PENDING approval tagged to the current user whose own
    due_date has already passed (spec section 3's "Overdue Items") - the
    same computed approval_due_status() everything else in this module
    uses, filtered down to exactly "overdue". Today this only ever
    surfaces overdue approvals - the one kind of per-user deadline this
    app tracks (see app/models/approval.py's own due_date docstring)."""
    candidates = (
        db.query(Approval)
        .options(
            selectinload(Approval.requested_by_user),
            selectinload(Approval.change_request).selectinload(ChangeRequest.analyses),
        )
        .filter(
            Approval.approver_id == current_user.id,
            Approval.status == ApprovalStatus.PENDING,
            Approval.due_date.isnot(None),
        )
        .order_by(Approval.due_date.asc())
        .all()
    )

    items: list[MyApprovalItem] = []
    for approval in candidates:
        if approvals_service.approval_due_status(approval) != "overdue":
            continue
        change_request = approval.change_request
        items.append(
            MyApprovalItem(
                id=approval.id,
                change_request_id=change_request.id,
                change_request_title=change_request.title,
                approval_type=approval.approval_type,
                approval_type_label=APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value),
                status=approval.status,
                status_label=APPROVAL_STATUS_LABELS.get(approval.status, approval.status.value),
                requested_by_name=approval.requested_by_user.name,
                requested_at=approval.requested_at,
                due_date=approval.due_date,
                due_status="overdue",
                risk=_risk_for(change_request),
            )
        )
    return items
