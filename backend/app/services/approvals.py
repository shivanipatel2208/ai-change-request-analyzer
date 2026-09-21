"""Module 12 Phase 4 (Enterprise Workflow - Approvals): where an AI-derived
recommendation (app/services/workflow_rules.py::required_approval_types)
turns into a real Approval row against a real, tagged person.

"AI recommends, humans decide" (spec section 14/29): nothing in this file
is ever called by the AI Analysis Engine itself - a human always chooses
the approval type and the approver, via the two entry points below. Every
state change here is written through app/services/history.py so it lands
on the same append-only audit trail as everything else in Module 12.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.enums import ApprovalStatus, ApprovalType, HistoryAction
from app.models.user import User
from app.services import history
from app.services.workflow_rules import (
    APPROVAL_STATUS_LABELS,
    APPROVAL_TYPE_LABELS,
    RECOMMENDATION_LABELS,
    overrides_ai_recommendation,
)


def is_approval_outdated(change_request: ChangeRequest, approval: Approval) -> bool:
    """True only for a still-PENDING approval requested against an older CR
    version than the one it's now sitting on - mirrors
    workflow_rules.is_analysis_outdated. A decision an approver already made
    is a historical fact, not something later edits can retroactively make
    "outdated", so this is always False once the approval is resolved."""
    if approval.status != ApprovalStatus.PENDING:
        return False
    cr_version = change_request.current_version or 1
    return approval.cr_version != cr_version


# Module 18 Phase 1: how close to (or past) its own due_date counts as
# "due soon" - a simple, adjustable window (mirrors Module 16's own
# min_score=0.2 cutoff in spirit: a deliberately plain heuristic, not a
# tuned value). Approaching-vs-overdue is a strict boundary at "now";
# "due soon" is anything inside this window that hasn't crossed it yet.
DUE_SOON_WINDOW = timedelta(days=2)


def approval_due_status(approval: Approval, *, now: Optional[datetime] = None) -> Optional[str]:
    """"overdue" / "due_soon" / None (not due soon, or no due_date at all) -
    computed fresh at read time from approval.due_date, never stored, the
    same "never a boolean that can silently go stale" rule
    is_approval_outdated/is_analysis_outdated already follow elsewhere in
    this app. Only ever meaningful for a still-PENDING approval - once an
    approval has actually been decided, its due date no longer means
    anything (mirrors is_approval_outdated's own "only PENDING" rule)."""
    if approval.status != ApprovalStatus.PENDING or approval.due_date is None:
        return None
    now = now or datetime.utcnow()
    if approval.due_date < now:
        return "overdue"
    if approval.due_date <= now + DUE_SOON_WINDOW:
        return "due_soon"
    return None


def request_approval(
    db: Session,
    change_request: ChangeRequest,
    *,
    approval_type: ApprovalType,
    approver: User,
    requested_by: User,
    comment: Optional[str] = None,
    due_date: Optional[datetime] = None,
) -> Approval:
    """Creates the Approval row and records APPROVAL_REQUESTED. Duplicate-
    pending-request checking (same type + approver already PENDING) is the
    API layer's job, same as create_assignment's duplicate check - this
    function just does the write once callers have already decided it's OK.
    due_date (Module 18 Phase 1) is entirely optional - most approvals
    still have none, same as before this module existed."""
    approval = Approval(
        change_request_id=change_request.id,
        approver_id=approver.id,
        approval_type=approval_type,
        status=ApprovalStatus.PENDING,
        requested_by=requested_by.id,
        cr_version=change_request.current_version or 1,
        due_date=due_date,
    )
    db.add(approval)
    db.flush()

    type_label = APPROVAL_TYPE_LABELS.get(approval_type, approval_type.value)
    history.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.APPROVAL_REQUESTED,
        user_id=requested_by.id,
        new_value=f"{type_label} approval requested from {approver.name}",
        reason=comment,
        version_number=change_request.current_version or 1,
    )
    return approval


def respond_to_approval(
    db: Session,
    change_request: ChangeRequest,
    approval: Approval,
    *,
    new_status: ApprovalStatus,
    comment: Optional[str],
    responder: User,
) -> Approval:
    """Moves a PENDING approval to Approved/Rejected/Changes Requested.
    Callers (the API layer) are responsible for checking that `responder`
    is the tagged approver and that `approval.status` is still PENDING -
    this function assumes both are already true."""
    type_label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
    old_label = APPROVAL_STATUS_LABELS.get(approval.status, approval.status.value)
    new_label = APPROVAL_STATUS_LABELS.get(new_status, new_status.value)

    approval.status = new_status
    approval.responded_at = datetime.utcnow()
    approval.comment = comment

    action = {
        ApprovalStatus.APPROVED: HistoryAction.APPROVED,
        ApprovalStatus.REJECTED: HistoryAction.REJECTED,
        ApprovalStatus.CHANGES_REQUESTED: HistoryAction.CHANGES_REQUESTED,
    }[new_status]

    history.record_event(
        db,
        change_request_id=change_request.id,
        action=action,
        user_id=responder.id,
        old_value=f"{type_label} — {old_label}",
        new_value=f"{type_label} — {new_label}",
        reason=comment,
        version_number=change_request.current_version or 1,
    )

    # Module 13 Phase 4 (human-override recording): compare this decision
    # against what the AI itself recommended on the analysis this approval
    # was actually requested against (approval.cr_version - not
    # necessarily the CR's *current* analysis, which may have moved on
    # since). Recorded as its own additional event, never in place of the
    # one above - "AI recommends, humans decide" means disagreeing is
    # never wrong, it should just stay visible on the record.
    relevant_analysis = (
        db.query(Analysis)
        .filter(
            Analysis.change_request_id == change_request.id,
            Analysis.change_request_version == approval.cr_version,
        )
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if relevant_analysis is not None and overrides_ai_recommendation(relevant_analysis.recommendation, new_status):
        rec_label = RECOMMENDATION_LABELS.get(
            relevant_analysis.recommendation,
            relevant_analysis.recommendation.value if relevant_analysis.recommendation else "No recommendation",
        )
        history.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.AI_RECOMMENDATION_OVERRIDDEN,
            user_id=responder.id,
            old_value=f"AI recommended: {rec_label}",
            new_value=f"{responder.name} marked {type_label} as {new_label}",
            reason=comment,
            version_number=change_request.current_version or 1,
        )

    return approval


def cancel_approval(db: Session, change_request: ChangeRequest, approval: Approval, *, cancelled_by: User) -> Approval:
    """Withdraws a still-PENDING approval request (e.g. tagged the wrong
    person). Never used on an already-resolved approval - that's the API
    layer's 409 to raise, not this function's job."""
    type_label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)

    approval.status = ApprovalStatus.CANCELLED
    approval.responded_at = datetime.utcnow()

    history.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.APPROVAL_CANCELLED,
        user_id=cancelled_by.id,
        old_value=f"{type_label} — Pending",
        version_number=change_request.current_version or 1,
    )
    return approval
