"""Change request creation, listing, filtering, detail, and AI-analysis
endpoints (Modules 4, 5, and 6).

Create / list (search/filter/sort) / get-one-with-detail (Modules 4-5) stay
read-only with respect to AI: the "category" / "risk" / "complexity" /
"effective_status" values they compute are derived from whatever analyses
already exist - they never call the AI provider themselves. The Module 6
section at the bottom of this file (analyze / get-analysis) is the only
place that does. No repository/RAG analysis yet - that's a later module.

Every route requires a logged-in user (Depends(get_current_user)).
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import check_capability, get_current_user
from app.database.session import get_db
from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.approval_rule import ApprovalRule
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.change_request_history import ChangeRequestHistory
from app.models.change_request_version import ChangeRequestVersion
from app.models.clarification_question import ClarificationQuestion
from app.models.comment import ChangeRequestComment
from app.models.enums import (
    ApprovalStatus,
    Capability,
    ChangeRequestStatus,
    HistoryAction,
    NotificationType,
    Priority,
    ReviewStatus,
)
from app.models.implementation_task import ImplementationTask
from app.models.repository_finding import RepositoryFinding
from app.models.repository_scan import RepositoryScan
from app.models.requirement import Requirement
from app.models.security_finding import SecurityFinding
from app.models.test_case import TestCase
from app.models.user import User
from app.services import approvals as approvals_service
from app.services import comments as comments_service
from app.services import history as history_service
from app.services import notify as notify_service
from app.services.analysis_delta import compare_analyses
from app.services.mentions import extract_mentioned_users
from app.services import repository_linkage
from app.services import traceability_linkage
from app.services.repository_matcher import RepositoryMatchError, run_repository_match
from app.services.workflow_rules import build_snapshot, risk_bucket
from app.schemas.analysis import AnalysisDeltaResponse, AnalysisRead, AnalysisSummaryRead
from app.schemas.approval import ApprovalRead, ApprovalRequestCreate, ApprovalRespond, RecommendedApprovalType
from app.schemas.assignment import AssignmentCreate, ChangeRequestAssignmentRead
from app.schemas.clarification_question import ClarificationQuestionAnswer, ClarificationQuestionRead
from app.schemas.comment import CommentCreate, CommentRead, CommentResolve
from app.schemas.implementation_task import ImplementationTaskRead, ImplementationTaskUpdate
from app.schemas.repository_finding import RepositoryFindingRead
from app.schemas.requirement import RequirementRead, RequirementReviewUpdate
from app.schemas.security_finding import SecurityFindingRead, SecurityFindingStatusUpdate
from app.schemas.test_case import TestCaseRead, TestCaseUpdate
from app.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestDetail,
    ChangeRequestHistoryRead,
    ChangeRequestListItem,
    ChangeRequestListResponse,
    ChangeRequestRead,
    ChangeRequestUpdate,
    ChangeRequestUpdateResponse,
    ChangeRequestVersionDetail,
    ChangeRequestVersionRead,
    ReportableVersionRead,
    ChangeStatusRequest,
    FieldComparisonRead,
    LatestAnalysisRead,
    StatusTransitionOption,
    VersionCompareResponse,
)
from app.services import workflow_rules
from app.services.analysis_engine import AnalysisError, run_analysis
from app.services.report_generator import (
    ReportGenerationError,
    ReportVersionError,
    generate_report_pdf,
    resolve_report_context,
)
from app.services import report_registry
from app.schemas.report import ReportListItem, ReportListResponse
from app.services.versioning import apply_change_request_update, compare_snapshots

router = APIRouter(prefix="/api/change-requests", tags=["change-requests"])

# Same category vocabulary/normalization and risk buckets as the dashboard
# (app/api/dashboard.py) - kept as a separate copy rather than a shared
# import so this module can't accidentally change dashboard behavior.
CANONICAL_CATEGORIES = ["Feature", "Bug Fix", "Security", "Database", "API", "Infrastructure", "Integration"]

_CATEGORY_ALIASES = {
    "feature": "Feature",
    "new feature": "Feature",
    "enhancement": "Feature",
    "bug fix": "Bug Fix",
    "bugfix": "Bug Fix",
    "bug": "Bug Fix",
    "fix": "Bug Fix",
    "security": "Security",
    "database": "Database",
    "db": "Database",
    "api": "API",
    "infrastructure": "Infrastructure",
    "infra": "Infrastructure",
    "integration": "Integration",
}

# The status vocabulary the "Filter by status" dropdown offers. Most of
# these are derived, not stored - see _effective_status() below. "analyzing"
# has no real backing yet (no AI pipeline exists to be "in progress" -
# that's a later module), so filtering by it will always return zero rows
# today; it's included so the filter is ready for when that module lands.
EFFECTIVE_STATUS_VALUES = {
    "draft",
    "pending_analysis",
    "analyzing",
    "requires_clarification",
    "completed",
    "approved",
}


def _normalize_category(raw: Optional[str]) -> str:
    if not raw:
        return "Other"
    return _CATEGORY_ALIASES.get(raw.strip().lower(), "Other")


def _latest_analysis(change_request: ChangeRequest) -> Optional[Analysis]:
    if not change_request.analyses:
        return None
    return max(change_request.analyses, key=lambda a: a.created_at)


def _load_approval_rules(db: Session) -> list[ApprovalRule]:
    """Module 21: every ApprovalRule row (enabled and disabled alike -
    workflow_rules.required_approval_types itself skips disabled ones),
    loaded once per request and handed to that pure rule-logic function -
    same "caller owns the query" convention as every other permission
    helper in workflow_rules.py."""
    return db.query(ApprovalRule).all()


def _effective_status(change_request: ChangeRequest, latest: Optional[Analysis]) -> str:
    """Human-facing status: raw DB status plus what analysis state (if any)
    already exists. Never stored - computed fresh every time from real rows."""
    if change_request.status == ChangeRequestStatus.APPROVED:
        return "approved"
    if change_request.status == ChangeRequestStatus.DRAFT:
        return "draft"
    if latest is None:
        return "pending_analysis"
    if any(not question.resolved for question in latest.clarification_questions):
        return "requires_clarification"
    return "completed"


@router.post("", response_model=ChangeRequestRead, status_code=status.HTTP_201_CREATED)
def create_change_request(
    payload: ChangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequest:
    check_capability(db, current_user, Capability.CR_CREATE)

    change_request = ChangeRequest(
        title=payload.title,
        description=payload.description,
        business_objective=payload.business_objective,
        priority=payload.priority,
        requested_by=payload.requested_by,
        target_system=payload.target_system,
        desired_deadline=payload.desired_deadline,
        business_impact=payload.business_impact,
        technical_impact=payload.technical_impact,
        customer_impact=payload.customer_impact,
        environment=payload.environment,
        dependencies_note=payload.dependencies_note,
        compliance_requirements=payload.compliance_requirements,
        tags=json.dumps(payload.tags) if payload.tags else None,
        status=ChangeRequestStatus.PENDING_ANALYSIS,
        created_by=current_user.id,
        current_version=1,
    )
    db.add(change_request)
    db.flush()

    db.add(
        ChangeRequestVersion(
            change_request_id=change_request.id,
            version_number=1,
            changed_by=current_user.id,
            change_summary="Change request created.",
            snapshot=build_snapshot(change_request),
        )
    )
    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.CREATED,
        user_id=current_user.id,
        version_number=1,
    )

    db.commit()
    db.refresh(change_request)
    return change_request


@router.get("", response_model=ChangeRequestListResponse)
def list_change_requests(
    search: Optional[str] = Query(
        None, description="Matches title, description, requested by, target system, or ticket number (e.g. '#3021')."
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description=f"One of: {', '.join(sorted(EFFECTIVE_STATUS_VALUES))}.",
    ),
    priority: Optional[Priority] = Query(None),
    assigned_to_me: bool = Query(
        False, description="Module 12 Phase 6: only change requests the current user is assigned to, in any role."
    ),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestListResponse:
    if status_filter is not None and status_filter not in EFFECTIVE_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(EFFECTIVE_STATUS_VALUES))}.",
        )

    query = db.query(ChangeRequest).options(
        selectinload(ChangeRequest.analyses).selectinload(Analysis.clarification_questions)
    )

    if search:
        raw = search.strip()
        pattern = f"%{raw}%"
        filters = [
            ChangeRequest.title.ilike(pattern),
            ChangeRequest.description.ilike(pattern),
            ChangeRequest.requested_by.ilike(pattern),
            ChangeRequest.target_system.ilike(pattern),
        ]
        # Ticket-number search: "#3021", "3021", or a partial number like
        # "30" all match against the numeric id, in addition to the text
        # fields above - a leading "#" (how the UI displays ids) is
        # stripped before matching.
        ticket_query = raw.lstrip("#").strip()
        if ticket_query:
            filters.append(cast(ChangeRequest.id, String).ilike(f"%{ticket_query}%"))
        query = query.filter(or_(*filters))

    if priority is not None:
        query = query.filter(ChangeRequest.priority == priority)

    if assigned_to_me:
        query = query.filter(
            ChangeRequest.assignments.any(ChangeRequestAssignment.user_id == current_user.id)
        )

    query = query.order_by(
        ChangeRequest.created_at.desc() if sort == "newest" else ChangeRequest.created_at.asc()
    )

    rows: list[ChangeRequestListItem] = []
    for change_request in query.all():
        latest = _latest_analysis(change_request)
        effective = _effective_status(change_request, latest)

        if status_filter is not None and effective != status_filter:
            continue

        rows.append(
            ChangeRequestListItem(
                id=change_request.id,
                title=change_request.title,
                priority=change_request.priority,
                status=change_request.status,
                effective_status=effective,
                category=_normalize_category(latest.category) if latest else None,
                risk=risk_bucket(latest.risk_score) if latest else None,
                complexity=latest.complexity.value if latest else None,
                created_at=change_request.created_at,
                current_version=change_request.current_version or 1,
            )
        )

    total = len(rows)
    page = rows[offset : offset + limit]

    return ChangeRequestListResponse(items=page, total=total, limit=limit, offset=offset)


@router.get("/{change_request_id}", response_model=ChangeRequestDetail)
def get_change_request(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestDetail:
    change_request = (
        db.query(ChangeRequest)
        .options(selectinload(ChangeRequest.analyses).selectinload(Analysis.clarification_questions))
        .filter(ChangeRequest.id == change_request_id)
        .first()
    )
    if change_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change request not found.")

    return _build_detail(change_request)


def _get_change_request_or_404(db: Session, change_request_id: int) -> ChangeRequest:
    change_request = db.get(ChangeRequest, change_request_id)
    if change_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change request not found.")
    return change_request


def _build_detail(change_request: ChangeRequest) -> ChangeRequestDetail:
    """Shared by every endpoint that returns a full ChangeRequestDetail
    (get, update, status change) so the shape can't drift between them."""
    latest = _latest_analysis(change_request)
    return ChangeRequestDetail(
        id=change_request.id,
        title=change_request.title,
        description=change_request.description,
        business_objective=change_request.business_objective,
        priority=change_request.priority,
        requested_by=change_request.requested_by,
        target_system=change_request.target_system,
        desired_deadline=change_request.desired_deadline,
        business_impact=change_request.business_impact,
        technical_impact=change_request.technical_impact,
        customer_impact=change_request.customer_impact,
        environment=change_request.environment,
        dependencies_note=change_request.dependencies_note,
        compliance_requirements=change_request.compliance_requirements,
        tags=change_request.tags,
        status=change_request.status,
        status_label=workflow_rules.STATUS_LABELS.get(change_request.status, change_request.status.value),
        effective_status=_effective_status(change_request, latest),
        created_by=change_request.created_by,
        created_at=change_request.created_at,
        updated_at=change_request.updated_at,
        current_version=change_request.current_version or 1,
        latest_analysis=LatestAnalysisRead.model_validate(latest) if latest else None,
        is_analysis_outdated=workflow_rules.is_analysis_outdated(change_request, latest),
        available_transitions=[
            StatusTransitionOption(
                status=s,
                label=workflow_rules.STATUS_LABELS.get(s, s.value),
                requires_reason=workflow_rules.reason_required(s),
            )
            for s in workflow_rules.available_transitions(change_request.status)
        ],
    )


def _assignment_read(assignment: ChangeRequestAssignment) -> ChangeRequestAssignmentRead:
    return ChangeRequestAssignmentRead(
        id=assignment.id,
        user_id=assignment.user_id,
        user_name=assignment.user.name,
        user_email=assignment.user.email,
        role=assignment.role,
        role_label=workflow_rules.ROLE_LABELS.get(assignment.role, assignment.role.value),
        assigned_by=assignment.assigned_by,
        assigned_by_name=assignment.assigned_by_user.name,
        assigned_at=assignment.assigned_at,
    )


def _approval_read(db: Session, approval: Approval, change_request: ChangeRequest) -> ApprovalRead:
    # Module 13 Phase 4: the analysis this approval was actually requested
    # against (its own cr_version), not necessarily the CR's *current*
    # analysis - matches the architecture-lock rule that every artifact
    # stays tied to the CR version it was produced for.
    relevant_analysis = (
        db.query(Analysis)
        .filter(
            Analysis.change_request_id == change_request.id,
            Analysis.change_request_version == approval.cr_version,
        )
        .order_by(Analysis.created_at.desc())
        .first()
    )
    ai_recommendation_label = None
    overrode = False
    if relevant_analysis is not None:
        ai_recommendation_label = workflow_rules.RECOMMENDATION_LABELS.get(relevant_analysis.recommendation)
        if approval.status in workflow_rules.APPROVAL_RESPONSE_STATUSES:
            overrode = workflow_rules.overrides_ai_recommendation(relevant_analysis.recommendation, approval.status)

    return ApprovalRead(
        id=approval.id,
        change_request_id=approval.change_request_id,
        approval_type=approval.approval_type,
        approval_type_label=workflow_rules.APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value),
        status=approval.status,
        status_label=workflow_rules.APPROVAL_STATUS_LABELS.get(approval.status, approval.status.value),
        approver_id=approval.approver_id,
        approver_name=approval.approver.name,
        approver_email=approval.approver.email,
        requested_by=approval.requested_by,
        requested_by_name=approval.requested_by_user.name,
        requested_at=approval.requested_at,
        responded_at=approval.responded_at,
        comment=approval.comment,
        cr_version=approval.cr_version,
        due_date=approval.due_date,
        due_status=approvals_service.approval_due_status(approval),
        is_outdated=approvals_service.is_approval_outdated(change_request, approval),
        ai_recommendation=ai_recommendation_label,
        overrode_ai_recommendation=overrode,
    )


# --- Module 12: editing, versioning, audit history --------------------


@router.put("/{change_request_id}", response_model=ChangeRequestUpdateResponse)
def update_change_request(
    change_request_id: int,
    payload: ChangeRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestUpdateResponse:
    """Full Change Request editing (spec section 2). Only fields actually
    present in the request body are touched (partial update) - see
    ChangeRequestUpdate's docstring. If anything changed, this creates a
    new version and field-level history events (app/services/versioning.py)
    rather than a vague "updated" log line; if nothing changed (identical
    values re-submitted), no version/history noise is created at all.
    """
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.CR_EDIT)

    if not workflow_rules.can_edit_change_request(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this change request.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    changes = apply_change_request_update(db, change_request, update_data, user=current_user)
    db.commit()
    db.refresh(change_request)

    detail = _build_detail(change_request)

    change_summaries = [
        FieldComparisonRead(
            field=c.field,
            label=c.label,
            old_value=c.old_value,
            new_value=c.new_value,
            status="removed" if c.new_value is None else ("added" if c.old_value is None else "changed"),
        )
        for c in changes
    ]

    return ChangeRequestUpdateResponse(
        change_request=detail,
        changes=change_summaries,
        new_version=change_request.current_version if changes else None,
    )


@router.get("/{change_request_id}/history", response_model=list[ChangeRequestHistoryRead])
def get_change_request_history(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChangeRequestHistory]:
    """The append-only Activity/Audit timeline (spec section 17), newest
    first."""
    _get_change_request_or_404(db, change_request_id)
    return (
        db.query(ChangeRequestHistory)
        .filter(ChangeRequestHistory.change_request_id == change_request_id)
        .order_by(ChangeRequestHistory.created_at.desc(), ChangeRequestHistory.id.desc())
        .all()
    )


@router.get("/{change_request_id}/versions", response_model=list[ChangeRequestVersionRead])
def list_change_request_versions(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChangeRequestVersion]:
    _get_change_request_or_404(db, change_request_id)
    return (
        db.query(ChangeRequestVersion)
        .filter(ChangeRequestVersion.change_request_id == change_request_id)
        .order_by(ChangeRequestVersion.version_number.desc())
        .all()
    )


@router.get("/{change_request_id}/versions/{version_number}", response_model=ChangeRequestVersionDetail)
def get_change_request_version(
    change_request_id: int,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestVersion:
    _get_change_request_or_404(db, change_request_id)
    version = (
        db.query(ChangeRequestVersion)
        .filter(
            ChangeRequestVersion.change_request_id == change_request_id,
            ChangeRequestVersion.version_number == version_number,
        )
        .first()
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version_number} not found.")
    return version


@router.get("/{change_request_id}/compare", response_model=VersionCompareResponse)
def compare_change_request_versions(
    change_request_id: int,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VersionCompareResponse:
    """Field-by-field diff between two versions (spec section 5)."""
    _get_change_request_or_404(db, change_request_id)

    def _get_version(number: int) -> ChangeRequestVersion:
        version = (
            db.query(ChangeRequestVersion)
            .filter(
                ChangeRequestVersion.change_request_id == change_request_id,
                ChangeRequestVersion.version_number == number,
            )
            .first()
        )
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {number} not found.")
        return version

    version_a = _get_version(from_version)
    version_b = _get_version(to_version)
    fields = compare_snapshots(version_a.snapshot, version_b.snapshot)

    return VersionCompareResponse(
        from_version=from_version,
        to_version=to_version,
        fields=[
            FieldComparisonRead(field=f.field, label=f.label, old_value=f.old_value, new_value=f.new_value, status=f.status)
            for f in fields
        ],
    )


# --- Module 12 Phase 3: status workflow + assignments ---------------------


@router.put("/{change_request_id}/status", response_model=ChangeRequestDetail)
def change_status(
    change_request_id: int,
    payload: ChangeStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestDetail:
    """Move a CR to a new status along the workflow lifecycle (spec section
    8). Only a legal next step (app/services/workflow_rules.STATUS_TRANSITIONS)
    is accepted, and moving into a "something went wrong" status (Changes
    Requested / Rejected / Cancelled) requires a non-empty reason - both
    enforced here, not just suggested by the frontend."""
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.STATUS_CHANGE)

    if not workflow_rules.can_manage_workflow(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to change this change request's status.",
        )

    if not workflow_rules.can_transition(change_request.status, payload.status):
        current_label = workflow_rules.STATUS_LABELS.get(change_request.status, change_request.status.value)
        target_label = workflow_rules.STATUS_LABELS.get(payload.status, payload.status.value)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Can't move from {current_label} to {target_label}.",
        )

    # Module 22 (Final Integration, Security & Quality) spec section 5:
    # "prevent approval bypass." Before this check, nothing here ever
    # looked at the Approval table at all - the CR's owner/Technical Lead
    # could tag someone for Security Approval, get no response, and still
    # mark the change request Approved. This only blocks on a still-open
    # ASK (PENDING) - it deliberately does NOT require that any approval
    # was ever requested in the first place, and does NOT keep blocking
    # forever over an old Rejected/Changes Requested approval (the normal
    # recovery path for those is requesting a fresh one, which
    # create_approval_request above already allows even while an old
    # resolved row for the same type/approver exists) - "AI recommends,
    # humans decide" (app/models/approval.py's own docstring) still means
    # a human can approve a CR with zero formal sign-offs on it, or after
    # weighing a past rejection and moving on; they just can't ignore
    # someone they're actively waiting to hear back from.
    if payload.status == ChangeRequestStatus.APPROVED:
        pending_count = (
            db.query(Approval)
            .filter(Approval.change_request_id == change_request_id, Approval.status == ApprovalStatus.PENDING)
            .count()
        )
        if pending_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This change request still has {pending_count} pending approval"
                    f"{'s' if pending_count != 1 else ''} - resolve or cancel "
                    "them before marking it Approved."
                ),
            )

    reason = (payload.reason or "").strip() or None
    if workflow_rules.reason_required(payload.status) and not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A reason is required to move this change request to "
            f"{workflow_rules.STATUS_LABELS.get(payload.status, payload.status.value)}.",
        )

    old_status = change_request.status
    change_request.status = payload.status
    old_label = workflow_rules.STATUS_LABELS.get(old_status, old_status.value)
    new_label = workflow_rules.STATUS_LABELS.get(payload.status, payload.status.value)
    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.STATUS_CHANGED,
        user_id=current_user.id,
        old_value=old_label,
        new_value=new_label,
        reason=reason,
        version_number=change_request.current_version or 1,
    )

    # Module 12 Phase 5: tell everyone with a stake in this CR - the
    # creator plus everyone currently assigned - except whoever just made
    # the change themselves.
    interested_ids = {change_request.created_by} | {a.user_id for a in change_request.assignments}
    interested_ids.discard(current_user.id)
    for user_id in interested_ids:
        notify_service.notify(
            db,
            user_id=user_id,
            type=NotificationType.STATUS_CHANGED,
            title=f"CR-{change_request.id} status changed",
            message=f"{current_user.name} moved \"{change_request.title}\" from {old_label} to {new_label}.",
            change_request_id=change_request.id,
        )

    db.commit()
    db.refresh(change_request)

    return _build_detail(change_request)


@router.get("/{change_request_id}/assignments", response_model=list[ChangeRequestAssignmentRead])
def list_assignments(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChangeRequestAssignmentRead]:
    """Who's responsible for what on this CR (spec section 9) - Requester,
    Owner, Technical Lead, Reviewer(s), Approver(s), Security Reviewer, QA
    Owner, Implementation Owner."""
    _get_change_request_or_404(db, change_request_id)
    rows = (
        db.query(ChangeRequestAssignment)
        .options(
            selectinload(ChangeRequestAssignment.user),
            selectinload(ChangeRequestAssignment.assigned_by_user),
        )
        .filter(ChangeRequestAssignment.change_request_id == change_request_id)
        .order_by(ChangeRequestAssignment.assigned_at)
        .all()
    )
    return [_assignment_read(a) for a in rows]


@router.post(
    "/{change_request_id}/assignments",
    response_model=ChangeRequestAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment(
    change_request_id: int,
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeRequestAssignmentRead:
    """Assign a user to a role on this CR. Only the CR's Owner/Technical
    Lead/creator/Admin can do this (workflow_rules.can_assign_users) - the
    same "CR Owner's job" permission as changing status. REVIEWER and
    APPROVER may have more than one person; assigning the same user to the
    same role twice is rejected as a no-op rather than silently duplicated."""
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.ASSIGNMENT)

    if not workflow_rules.can_assign_users(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to assign users on this change request.",
        )

    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    existing = (
        db.query(ChangeRequestAssignment)
        .filter(
            ChangeRequestAssignment.change_request_id == change_request_id,
            ChangeRequestAssignment.user_id == payload.user_id,
            ChangeRequestAssignment.role == payload.role,
        )
        .first()
    )
    if existing is not None:
        role_label = workflow_rules.ROLE_LABELS.get(payload.role, payload.role.value)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{target_user.name} is already assigned as {role_label} on this change request.",
        )

    assignment = ChangeRequestAssignment(
        change_request_id=change_request_id,
        user_id=payload.user_id,
        role=payload.role,
        assigned_by=current_user.id,
    )
    db.add(assignment)
    db.flush()

    role_label = workflow_rules.ROLE_LABELS.get(payload.role, payload.role.value)
    history_service.record_event(
        db,
        change_request_id=change_request_id,
        action=HistoryAction.ASSIGNED,
        user_id=current_user.id,
        new_value=f"{target_user.name} as {role_label}",
        version_number=change_request.current_version or 1,
    )
    if target_user.id != current_user.id:
        notify_service.notify(
            db,
            user_id=target_user.id,
            type=NotificationType.ASSIGNED,
            title=f"You were assigned to CR-{change_request.id}",
            message=f"{current_user.name} assigned you as {role_label} on \"{change_request.title}\".",
            change_request_id=change_request.id,
        )
    db.commit()
    db.refresh(assignment)

    return _assignment_read(assignment)


@router.delete("/{change_request_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    change_request_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    change_request = _get_change_request_or_404(db, change_request_id)

    if not workflow_rules.can_assign_users(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to change assignments on this change request.",
        )

    assignment = (
        db.query(ChangeRequestAssignment)
        .options(selectinload(ChangeRequestAssignment.user))
        .filter(
            ChangeRequestAssignment.id == assignment_id,
            ChangeRequestAssignment.change_request_id == change_request_id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")

    role_label = workflow_rules.ROLE_LABELS.get(assignment.role, assignment.role.value)
    removed_user_name = assignment.user.name
    db.delete(assignment)
    history_service.record_event(
        db,
        change_request_id=change_request_id,
        action=HistoryAction.UNASSIGNED,
        user_id=current_user.id,
        old_value=f"{removed_user_name} as {role_label}",
        version_number=change_request.current_version or 1,
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Module 12 Phase 4: approvals ------------------------------------------


def _get_approval_or_404(db: Session, change_request_id: int, approval_id: int) -> Approval:
    approval = (
        db.query(Approval)
        .options(selectinload(Approval.approver), selectinload(Approval.requested_by_user))
        .filter(Approval.id == approval_id, Approval.change_request_id == change_request_id)
        .first()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return approval


@router.get("/{change_request_id}/approvals", response_model=list[ApprovalRead])
def list_approvals(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApprovalRead]:
    """Every sign-off requested on this CR (spec section 14), oldest first -
    who was tagged, what kind, and where it stands."""
    change_request = _get_change_request_or_404(db, change_request_id)
    rows = (
        db.query(Approval)
        .options(selectinload(Approval.approver), selectinload(Approval.requested_by_user))
        .filter(Approval.change_request_id == change_request_id)
        .order_by(Approval.requested_at)
        .all()
    )
    return [_approval_read(db, a, change_request) for a in rows]


@router.get("/{change_request_id}/approvals/recommended", response_model=list[RecommendedApprovalType])
def recommended_approvals(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecommendedApprovalType]:
    """An AI-derived suggestion only - "AI recommends, humans decide"
    (spec section 14/29, app/services/workflow_rules.py::
    required_approval_types). Empty until the CR has been analyzed at
    least once; never creates an Approval row by itself.

    Module 22: also flags is_outdated (see RecommendedApprovalType's own
    docstring) whenever this is computed from an analysis that's no
    longer current - the same is_analysis_outdated check the main CR
    detail view already uses for its own warning banner."""
    change_request = _get_change_request_or_404(db, change_request_id)
    latest = _latest_analysis(change_request)
    if latest is None:
        return []
    outdated = workflow_rules.is_analysis_outdated(change_request, latest)
    types = workflow_rules.required_approval_types(change_request, latest, _load_approval_rules(db))
    return [
        RecommendedApprovalType(
            approval_type=t, label=workflow_rules.APPROVAL_TYPE_LABELS.get(t, t.value), is_outdated=outdated
        )
        for t in sorted(types, key=lambda t: t.value)
    ]


@router.post("/{change_request_id}/approvals", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED)
def create_approval_request(
    change_request_id: int,
    payload: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalRead:
    """Tag a real person for a specific kind of sign-off. Only the CR's
    Owner/Technical Lead/creator/Admin can do this
    (workflow_rules.can_request_approval) - the same "CR Owner's job"
    permission as changing status/assigning users. Requesting the same
    type from the same approver while one is already pending is rejected
    as a duplicate, same pattern as create_assignment."""
    change_request = _get_change_request_or_404(db, change_request_id)

    if not workflow_rules.can_request_approval(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to request approvals on this change request.",
        )

    approver = db.get(User, payload.approver_user_id)
    if approver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    existing = (
        db.query(Approval)
        .filter(
            Approval.change_request_id == change_request_id,
            Approval.approver_id == payload.approver_user_id,
            Approval.approval_type == payload.approval_type,
            Approval.status == ApprovalStatus.PENDING,
        )
        .first()
    )
    if existing is not None:
        type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(payload.approval_type, payload.approval_type.value)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{approver.name} already has a pending {type_label} approval request on this change request.",
        )

    approval = approvals_service.request_approval(
        db,
        change_request,
        approval_type=payload.approval_type,
        approver=approver,
        requested_by=current_user,
        comment=payload.comment,
        due_date=payload.due_date,
    )
    if approver.id != current_user.id:
        type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(payload.approval_type, payload.approval_type.value)
        notify_service.notify(
            db,
            user_id=approver.id,
            type=NotificationType.APPROVAL_REQUESTED,
            title=f"{type_label} approval requested on CR-{change_request.id}",
            message=f"{current_user.name} asked you for {type_label} approval on \"{change_request.title}\".",
            change_request_id=change_request.id,
        )
    db.commit()
    db.refresh(approval)

    return _approval_read(db, approval, change_request)


@router.post("/{change_request_id}/approvals/{approval_id}/respond", response_model=ApprovalRead)
def respond_to_approval_request(
    change_request_id: int,
    approval_id: int,
    payload: ApprovalRespond,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalRead:
    """Only the tagged approver may respond - never the CR's owner, an
    admin, or anyone else (app/models/approval.py's own docstring: "never
    by anyone else or by the AI"). A comment is required when rejecting or
    requesting changes, the same "explain what went wrong" rule as moving
    a CR's status."""
    change_request = _get_change_request_or_404(db, change_request_id)
    approval = _get_approval_or_404(db, change_request_id, approval_id)

    if approval.approver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person tagged for this approval can respond to it.",
        )

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This approval has already been responded to.",
        )

    if payload.status not in workflow_rules.APPROVAL_RESPONSE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: approved, rejected, changes_requested.",
        )

    # Module 21 spec section 3: Approval and Rejection are two separate,
    # independently-configurable permissions - approving is
    # Capability.APPROVAL, while rejecting OR requesting changes (both
    # "this isn't good to go yet, and here's why" outcomes) are
    # Capability.REJECTION.
    check_capability(
        db,
        current_user,
        Capability.APPROVAL if payload.status == ApprovalStatus.APPROVED else Capability.REJECTION,
    )

    if payload.status in workflow_rules.APPROVAL_REASON_REQUIRED and not payload.comment:
        target_label = workflow_rules.APPROVAL_STATUS_LABELS.get(payload.status, payload.status.value)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A comment is required to mark this approval as {target_label}.",
        )

    approvals_service.respond_to_approval(
        db,
        change_request,
        approval,
        new_status=payload.status,
        comment=payload.comment,
        responder=current_user,
    )

    type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
    response_notification_type = {
        ApprovalStatus.APPROVED: NotificationType.APPROVED,
        ApprovalStatus.REJECTED: NotificationType.REJECTED,
        ApprovalStatus.CHANGES_REQUESTED: NotificationType.CHANGES_REQUESTED,
    }[payload.status]
    if approval.requested_by != current_user.id:
        status_label = workflow_rules.APPROVAL_STATUS_LABELS.get(payload.status, payload.status.value)
        notify_service.notify(
            db,
            user_id=approval.requested_by,
            type=response_notification_type,
            title=f"{type_label} approval {status_label.lower()} on CR-{change_request.id}",
            message=f"{current_user.name} marked the {type_label} approval you requested as {status_label}.",
            change_request_id=change_request.id,
        )
    db.commit()
    db.refresh(approval)

    return _approval_read(db, approval, change_request)


@router.delete("/{change_request_id}/approvals/{approval_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_approval_request(
    change_request_id: int,
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Withdraw a still-pending approval request (e.g. tagged the wrong
    person) - same permission as requesting one. Soft-cancelled (status ->
    Cancelled) rather than deleted, so it stays on the audit trail."""
    change_request = _get_change_request_or_404(db, change_request_id)
    approval = _get_approval_or_404(db, change_request_id, approval_id)

    if not workflow_rules.can_request_approval(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to cancel approval requests on this change request.",
        )

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a pending approval request can be cancelled.",
        )

    approvals_service.cancel_approval(db, change_request, approval, cancelled_by=current_user)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{change_request_id}/approvals/{approval_id}/remind", status_code=status.HTTP_204_NO_CONTENT)
def remind_approval(
    change_request_id: int,
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """A manual nudge for an approver who hasn't responded yet - same
    permission as requesting the approval in the first place. Doesn't
    change anything about the approval itself, just sends a fresh
    REMINDER notification and logs REMINDER_SENT on the audit trail."""
    change_request = _get_change_request_or_404(db, change_request_id)
    approval = _get_approval_or_404(db, change_request_id, approval_id)

    if not workflow_rules.can_request_approval(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to send reminders on this change request.",
        )

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a pending approval request can be reminded.",
        )

    type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.REMINDER_SENT,
        user_id=current_user.id,
        new_value=f"Reminder sent to {approval.approver.name} for {type_label} approval",
        version_number=change_request.current_version or 1,
    )
    notify_service.notify(
        db,
        user_id=approval.approver_id,
        type=NotificationType.REMINDER,
        title=f"Reminder: {type_label} approval requested on CR-{change_request.id}",
        message=f"{current_user.name} is still waiting on your {type_label} approval for \"{change_request.title}\".",
        change_request_id=change_request.id,
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Module 12 Phase 5: comments -------------------------------------------


def _comment_read(comment: ChangeRequestComment, all_users: list[User]) -> CommentRead:
    mentioned = extract_mentioned_users(comment.body, all_users, exclude_user_id=comment.user_id)
    return CommentRead(
        id=comment.id,
        change_request_id=comment.change_request_id,
        user_id=comment.user_id,
        user_name=comment.user.name,
        parent_id=comment.parent_id,
        body=comment.body,
        resolved=comment.resolved,
        created_at=comment.created_at,
        mentioned_user_ids=[u.id for u in mentioned],
    )


@router.get("/{change_request_id}/comments", response_model=list[CommentRead])
def list_comments(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CommentRead]:
    """The discussion thread on this CR, oldest first - a flat two-level
    thread (top-level comments plus their direct replies), not a nested
    tree (spec: "reply where practical")."""
    _get_change_request_or_404(db, change_request_id)
    rows = (
        db.query(ChangeRequestComment)
        .options(selectinload(ChangeRequestComment.user))
        .filter(ChangeRequestComment.change_request_id == change_request_id)
        .order_by(ChangeRequestComment.created_at)
        .all()
    )
    all_users = db.query(User).all()
    return [_comment_read(c, all_users) for c in rows]


@router.post("/{change_request_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
def create_comment(
    change_request_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentRead:
    """Post a comment (optionally a reply to one existing top-level
    comment). Open to anyone who can see this CR - unlike editing/status/
    approvals, commenting isn't gated to the Owner/Technical Lead/Admin,
    it's how everyone else participates. @mentions in the text and who
    else gets notified are handled by app/services/comments.py."""
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.COMMENTS)

    if payload.parent_id is not None:
        parent = (
            db.query(ChangeRequestComment)
            .filter(
                ChangeRequestComment.id == payload.parent_id,
                ChangeRequestComment.change_request_id == change_request_id,
            )
            .first()
        )
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment being replied to not found.")
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Can't reply to a reply - this thread only goes one level deep.",
            )

    comment = comments_service.create_comment(
        db,
        change_request,
        author=current_user,
        body=payload.body,
        parent_id=payload.parent_id,
    )
    db.commit()
    db.refresh(comment)

    all_users = db.query(User).all()
    return _comment_read(comment, all_users)


@router.put("/{change_request_id}/comments/{comment_id}/resolve", response_model=CommentRead)
def resolve_comment(
    change_request_id: int,
    comment_id: int,
    payload: CommentResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentRead:
    """Mark a comment resolved (or reopen it) - either whoever posted it,
    or whoever manages this CR's workflow, can do this."""
    change_request = _get_change_request_or_404(db, change_request_id)
    comment = (
        db.query(ChangeRequestComment)
        .options(selectinload(ChangeRequestComment.user))
        .filter(ChangeRequestComment.id == comment_id, ChangeRequestComment.change_request_id == change_request_id)
        .first()
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    is_author = comment.user_id == current_user.id
    if not is_author and not workflow_rules.can_manage_workflow(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to resolve this comment.",
        )

    comment.resolved = payload.resolved
    db.commit()
    db.refresh(comment)

    all_users = db.query(User).all()
    return _comment_read(comment, all_users)


@router.delete("/{change_request_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    change_request_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Only the comment's own author (or an Admin) can delete it."""
    change_request = _get_change_request_or_404(db, change_request_id)
    comment = (
        db.query(ChangeRequestComment)
        .filter(ChangeRequestComment.id == comment_id, ChangeRequestComment.change_request_id == change_request_id)
        .first()
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    if comment.user_id != current_user.id and not workflow_rules.is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own comments.",
        )

    db.delete(comment)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Module 6: AI Analysis Engine ------------------------------------
#
# The only two routes that call the AI. Everything above this stays exactly
# as Module 5 left it - list/detail keep reading whatever analyses already
# exist, unaware of how they got there.


_ANALYSIS_RELATIONSHIPS = (
    selectinload(Analysis.requirements),
    selectinload(Analysis.affected_components),
    selectinload(Analysis.dependencies),
    selectinload(Analysis.risks),
    # Module 14 Phase 4/5 - added here for the same eager-loading reason as
    # every relationship above (avoids an N+1 query per analysis fetched);
    # functionally these were already reachable via SQLAlchemy's default
    # lazy-load, just not eager-loaded until now.
    selectinload(Analysis.impact_assessments),
    selectinload(Analysis.security_findings),
    selectinload(Analysis.clarification_questions),
    selectinload(Analysis.test_cases),
    selectinload(Analysis.implementation_tasks),
    # Module 16 (Project Knowledge Base & RAG) Phase 4/5.
    selectinload(Analysis.knowledge_evidence),
)


def _repository_findings_for_analysis(db: Session, analysis_id: int) -> list[RepositoryFinding]:
    """Module 15 Phase 5 (Repository Intelligence - Integration): whatever
    repository findings already exist for this exact analysis - eager-
    loading each finding's own indexed_file since
    RepositoryFinding.file_path (used by repository_linkage.related_files)
    reads it via that relationship. Empty (never 404) when no repository
    scan/match has ever been run for this analysis - the same "empty is a
    valid, honest outcome" rule the matcher and the outdated-check follow."""
    return (
        db.query(RepositoryFinding)
        .options(selectinload(RepositoryFinding.indexed_file))
        .filter(RepositoryFinding.analysis_id == analysis_id)
        .all()
    )


@router.post("/{change_request_id}/analyze", response_model=AnalysisRead, status_code=status.HTTP_201_CREATED)
def analyze_change_request(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysisRead:
    """Run the AI Analysis Engine on a change request and persist the
    result. A request can be analyzed more than once (e.g. after edits) -
    each call adds a new Analysis row rather than overwriting the last one,
    and the list/detail views already show whichever is newest."""
    change_request = _get_change_request_or_404(db, change_request_id)

    # Module 13 Phase 3: captured *before* run_analysis() so we still have
    # whatever was previously "the latest analysis" once a new one exists -
    # used below to detect a materially significant re-analysis.
    previous_analysis = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )

    try:
        analysis = run_analysis(db, change_request)
    except AnalysisError as exc:
        # Module 19 (Engineering Change Analytics): the one place a failed
        # analysis attempt gets recorded at all - same actor_label="AI
        # Analyzer" / no user_id convention as a successful
        # AI_ANALYSIS_COMPLETED event, so the new analytics dashboard's "AI
        # analysis failures" count is real data, not zero-by-omission.
        # Explicit commit here (not just flush) since we're about to raise -
        # get_db's session.close() would otherwise roll this back.
        history_service.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.AI_ANALYSIS_FAILED,
            actor_label="AI Analyzer",
            new_value=str(exc),
            version_number=change_request.current_version or 1,
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # Re-fetch with every relationship eager-loaded so the response includes
    # the full set of requirements/risks/etc. in one query.
    analysis = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.id == analysis.id)
        .one()
    )

    # Module 24 (Reports): a report is never generated as a separate,
    # manual step - the moment an analysis completes for the CR's current
    # version, that's automatically a REPORT_GENERATED event too, so it
    # shows up on the Reports page immediately with no extra click. This is
    # the exact same event/aggregation mechanism app/services/
    # report_registry.py already reads for every other report source (the
    # Analysis Dashboard's own "Download Report" button) - just triggered
    # here instead of on a download/generate action. Always the CR's
    # current, non-historical version, since that's what was just analyzed.
    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.REPORT_GENERATED,
        user_id=current_user.id,
        new_value=f"Version {change_request.current_version or 1}",
        version_number=change_request.current_version or 1,
    )
    db.commit()

    # Module 13 Phase 3: re-analyzing a CR that already had an analysis, and
    # landing somewhere materially different (risk bucket, complexity,
    # recommendation, or recommended approvals all changed) is worth
    # telling people about, the same way editing a CR already notifies
    # people that its old analysis went stale (see the ANALYSIS_OUTDATED
    # block in app/services/versioning.py). Reuses Phase 2's computed diff
    # rather than inventing a second "did this change materially" check.
    interested_ids = {change_request.created_by} | {a.user_id for a in change_request.assignments}
    interested_ids.discard(current_user.id)
    notified_anyone = False

    if previous_analysis is None:
        # Module 18 Phase 2 (Notifications, My Work & Personal Engineering
        # Queue): the very first analysis this change request has ever
        # had - distinct from ANALYSIS_SIGNIFICANTLY_CHANGED/RISK_ESCALATED
        # below, both of which only ever fire on a *re*-analysis (there's
        # nothing to compare a first analysis against). Never fires again
        # for the same CR once it has a previous analysis to compare to.
        for user_id in interested_ids:
            notify_service.notify(
                db,
                user_id=user_id,
                type=NotificationType.ANALYSIS_COMPLETED,
                title=f"CR-{change_request.id} has been analyzed",
                message=f"{current_user.name} ran the AI analysis on \"{change_request.title}\".",
                change_request_id=change_request.id,
            )
            notified_anyone = True
    else:
        delta = compare_analyses(change_request, previous_analysis, analysis, _load_approval_rules(db))
        if delta.is_significant_change:
            reasons_text = " ".join(delta.significant_change_reasons)
            for user_id in interested_ids:
                notify_service.notify(
                    db,
                    user_id=user_id,
                    type=NotificationType.ANALYSIS_SIGNIFICANTLY_CHANGED,
                    title=f"CR-{change_request.id}'s re-analysis changed materially",
                    message=f"{current_user.name} re-analyzed \"{change_request.title}\" - {reasons_text}",
                    change_request_id=change_request.id,
                )
                notified_anyone = True

        # Module 18 Phase 2: risk escalation gets its own, more urgent
        # notification, separate from "something changed" above - fires
        # only when the risk bucket actually got WORSE (never on an
        # improvement, and never just because *something* changed - a
        # complexity or recommendation change alone doesn't escalate risk).
        # Can fire alongside ANALYSIS_SIGNIFICANTLY_CHANGED above (a risk
        # bucket move is itself one of that notification's own reasons) -
        # that's deliberate, not a duplicate: one says "the numbers moved",
        # the other says specifically "and it's now riskier."
        if workflow_rules.risk_bucket_rank(delta.risk_bucket_after) > workflow_rules.risk_bucket_rank(
            delta.risk_bucket_before
        ):
            for user_id in interested_ids:
                notify_service.notify(
                    db,
                    user_id=user_id,
                    type=NotificationType.RISK_ESCALATED,
                    title=f"CR-{change_request.id}'s risk escalated to {delta.risk_bucket_after.capitalize()}",
                    message=(
                        f"{current_user.name}'s re-analysis of \"{change_request.title}\" moved risk from "
                        f"{delta.risk_bucket_before.capitalize()} to {delta.risk_bucket_after.capitalize()}."
                    ),
                    change_request_id=change_request.id,
                )
                notified_anyone = True

    if notified_anyone:
        db.commit()

    response = AnalysisRead.model_validate(analysis)
    response.is_outdated = workflow_rules.is_analysis_outdated(change_request, analysis)
    # Module 16 (Project Knowledge Base & RAG) Phase 4/5: each piece of
    # evidence was retrieved as part of THIS analysis run, so it shares
    # this analysis's own outdated status exactly - see
    # KnowledgeEvidenceRead's own docstring for why there's no separate
    # per-evidence staleness computation.
    for evidence in response.knowledge_evidence:
        evidence.is_outdated = response.is_outdated
    # Module 17 Phase 1 (Test Cases & Implementation Plan 2.0): every test
    # case/task belongs to exactly this one analysis, so both share its
    # version and its outdated status exactly - same "no separate
    # staleness computation" reasoning as knowledge_evidence above.
    for test_case in response.test_cases:
        test_case.analysis_version = analysis.change_request_version
        test_case.is_outdated = response.is_outdated
    for task in response.implementation_tasks:
        task.analysis_version = analysis.change_request_version
        task.is_outdated = response.is_outdated
    # Module 13 Phase 4.
    response.workflow_recommendation = workflow_rules.recommendation_summary(change_request, analysis, _load_approval_rules(db))
    # Module 15 Phase 5: a brand-new analysis has no repository findings of
    # its own yet (matching runs separately, after analysis, against this
    # exact analysis_id) - so this is a no-op right after /analyze, and
    # becomes meaningful once POST .../repository-findings has run for this
    # analysis. Still called unconditionally, same as everywhere else in
    # this app that computes something fresh rather than special-casing
    # "nothing to compute yet."
    repository_linkage.annotate_analysis_response(
        response, _repository_findings_for_analysis(db, analysis.id)
    )
    # Module 17 Phase 4: which Requirement(s)/Risk(s) each test case/task
    # is traceable to - computed the same keyword-overlap way
    # repository_linkage above is, using this same response's own
    # requirements/risks (never a separate query - see this module's own
    # docstring for why an artifact can only ever trace to its own
    # analysis's rows).
    traceability_linkage.annotate_analysis_response(response)
    return response


@router.get("/{change_request_id}/analysis", response_model=AnalysisRead)
def get_latest_analysis(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysisRead:
    """The most recent analysis for a change request, with every child
    table (requirements, affected components, dependencies, risks,
    clarification questions, test cases, implementation tasks) included."""
    change_request = _get_change_request_or_404(db, change_request_id)

    analysis = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This change request hasn't been analyzed yet.",
        )
    response = AnalysisRead.model_validate(analysis)
    # Module 13 Phase 3: this is always "the latest analysis" for this CR
    # (never a historical one from the /analyses or /analysis/compare
    # endpoints), so "outdated" has one unambiguous meaning here: the CR
    # has been edited since this analysis ran.
    response.is_outdated = workflow_rules.is_analysis_outdated(change_request, analysis)
    # Module 16 Phase 4/5: see the identical loop in analyze_change_request
    # above.
    for evidence in response.knowledge_evidence:
        evidence.is_outdated = response.is_outdated
    # Module 17 Phase 1 (Test Cases & Implementation Plan 2.0): every test
    # case/task belongs to exactly this one analysis, so both share its
    # version and its outdated status exactly - same "no separate
    # staleness computation" reasoning as knowledge_evidence above.
    for test_case in response.test_cases:
        test_case.analysis_version = analysis.change_request_version
        test_case.is_outdated = response.is_outdated
    for task in response.implementation_tasks:
        task.analysis_version = analysis.change_request_version
        task.is_outdated = response.is_outdated
    # Module 13 Phase 4.
    response.workflow_recommendation = workflow_rules.recommendation_summary(change_request, analysis, _load_approval_rules(db))
    # Module 15 Phase 5: see the identical call in analyze_change_request
    # above for why this is unconditional.
    repository_linkage.annotate_analysis_response(
        response, _repository_findings_for_analysis(db, analysis.id)
    )
    # Module 17 Phase 4: which Requirement(s)/Risk(s) each test case/task
    # is traceable to - computed the same keyword-overlap way
    # repository_linkage above is, using this same response's own
    # requirements/risks (never a separate query - see this module's own
    # docstring for why an artifact can only ever trace to its own
    # analysis's rows).
    traceability_linkage.annotate_analysis_response(response)
    return response


# --- Module 15 Phase 3: CR -> File Matching (Repository Intelligence) --
#
# "Which source files may actually be affected by this change request?" -
# this module's own headline differentiator. Matches the CR's latest
# analysis against the most recent repository scan; see
# app/services/repository_matcher.py for how the shortlist/AI-call/
# persistence actually works. Deliberately not permission-gated beyond
# plain authentication, same precedent as /analyze itself (generating an
# AI-derived finding isn't a workflow action the way editing/approving/
# assigning are).


def _get_latest_analysis_or_404(db: Session, change_request_id: int) -> Analysis:
    analysis = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This change request hasn't been analyzed yet.",
        )
    return analysis


def _get_latest_repository_scan_or_404(db: Session) -> RepositoryScan:
    scan = db.query(RepositoryScan).order_by(RepositoryScan.started_at.desc()).first()
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repository scan has been run yet - trigger POST /api/repository/scan first.",
        )
    return scan


@router.post(
    "/{change_request_id}/repository-findings",
    response_model=list[RepositoryFindingRead],
    status_code=status.HTTP_201_CREATED,
)
def trigger_repository_match(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RepositoryFindingRead]:
    change_request = _get_change_request_or_404(db, change_request_id)
    analysis = _get_latest_analysis_or_404(db, change_request_id)
    scan = _get_latest_repository_scan_or_404(db)

    try:
        findings = run_repository_match(db, change_request, analysis, scan)
    except RepositoryMatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # Module 15 Phase 4: computed fresh here, same as everywhere else this
    # app computes "is this still current" - practically always False
    # immediately after a fresh match (this analysis/scan pair IS "the
    # latest" the moment these rows were written), but still run through
    # the shared check rather than hardcoded, for the same reason
    # AnalysisRead.is_outdated is recomputed even right after a fresh
    # /analyze call.
    return [
        _finding_with_outdated_info(finding, change_request, latest_analysis_id=analysis.id, latest_scan_id=scan.id)
        for finding in findings
    ]


def _finding_with_outdated_info(
    finding: RepositoryFinding,
    change_request: ChangeRequest,
    *,
    latest_analysis_id: Optional[int],
    latest_scan_id: Optional[int],
) -> RepositoryFindingRead:
    item = RepositoryFindingRead.model_validate(finding)
    item.outdated_reasons = workflow_rules.repository_finding_outdated_reasons(
        change_request,
        finding.change_request_version,
        finding.analysis_id,
        finding.repository_scan_id,
        latest_analysis_id=latest_analysis_id,
        latest_repository_scan_id=latest_scan_id,
    )
    item.is_outdated = bool(item.outdated_reasons)
    return item


@router.get("/{change_request_id}/repository-findings", response_model=list[RepositoryFindingRead])
def list_repository_findings(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RepositoryFindingRead]:
    """Whatever was found the last time a match was run for this change
    request's *current* latest analysis - empty (not 404) if none has
    been run yet, the same "an empty result is a valid, honest answer"
    rule the matcher itself follows. Module 15 Phase 4: each finding also
    reports whether it may be outdated - the change request was edited, a
    newer analysis ran, or a newer repository scan is available - since
    the last time this exact match was generated."""
    change_request = _get_change_request_or_404(db, change_request_id)
    analysis = (
        db.query(Analysis)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if analysis is None:
        return []

    findings = (
        db.query(RepositoryFinding)
        .filter(
            RepositoryFinding.change_request_id == change_request.id,
            RepositoryFinding.analysis_id == analysis.id,
        )
        .order_by(RepositoryFinding.confidence.desc())
        .all()
    )

    latest_scan = db.query(RepositoryScan).order_by(RepositoryScan.started_at.desc()).first()
    latest_scan_id = latest_scan.id if latest_scan is not None else None

    return [
        _finding_with_outdated_info(
            finding, change_request, latest_analysis_id=analysis.id, latest_scan_id=latest_scan_id
        )
        for finding in findings
    ]


# --- Module 14 Phase 6: human review of AI findings -------------------
#
# Two narrow, explicitly-scoped actions - marking a Requirement's review
# status and moving a Security finding's status forward - never a general
# "edit the AI's analysis" capability. Neither endpoint below touches the
# AI's own certainty/confidence/evidence/finding/severity columns; both
# record the change on the change request's audit history (architecture
# lock: "AI may recommend but never perform human approval" - these
# endpoints are exactly the human half of that split).


def _get_requirement_or_404(db: Session, change_request_id: int, requirement_id: int) -> Requirement:
    requirement = (
        db.query(Requirement)
        .join(Analysis, Requirement.analysis_id == Analysis.id)
        .filter(Requirement.id == requirement_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requirement not found on this change request.",
        )
    return requirement


def _get_security_finding_or_404(db: Session, change_request_id: int, finding_id: int) -> SecurityFinding:
    finding = (
        db.query(SecurityFinding)
        .join(Analysis, SecurityFinding.analysis_id == Analysis.id)
        .filter(SecurityFinding.id == finding_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Security finding not found on this change request.",
        )
    return finding


@router.patch("/{change_request_id}/requirements/{requirement_id}/review", response_model=RequirementRead)
def review_requirement(
    change_request_id: int,
    requirement_id: int,
    payload: RequirementReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequirementRead:
    """An authorized human's verdict on this specific AI-extracted
    requirement - Confirmed or Needs Clarification. Never touches this
    row's certainty/confidence/evidence (those stay exactly what the AI
    produced); this is a separate, additive record of what a human then
    did about it. A comment is required for Needs Clarification (same
    "explain what needs fixing" rule ApprovalRespond applies to its own
    negative outcomes) and optional for Confirmed."""
    change_request = _get_change_request_or_404(db, change_request_id)
    requirement = _get_requirement_or_404(db, change_request_id, requirement_id)

    if not workflow_rules.can_review_analysis_findings(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to review requirements on this change request.",
        )

    if payload.review_status == ReviewStatus.NEEDS_CLARIFICATION and not payload.comment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A comment is required to mark a requirement as Needs Clarification.",
        )

    old_value = requirement.review_status.value if requirement.review_status else "unreviewed"

    requirement.review_status = payload.review_status
    requirement.review_comment = payload.comment
    requirement.reviewed_by = current_user.id
    requirement.reviewed_at = datetime.utcnow()

    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.REQUIREMENT_REVIEWED,
        user_id=current_user.id,
        field_name=f"Requirement #{requirement.id}",
        old_value=old_value,
        new_value=payload.review_status.value,
        reason=payload.comment,
        version_number=change_request.current_version or 1,
    )
    db.commit()
    db.refresh(requirement)
    return requirement


def _get_clarification_question_or_404(
    db: Session, change_request_id: int, question_id: int
) -> ClarificationQuestion:
    question = (
        db.query(ClarificationQuestion)
        .join(Analysis, ClarificationQuestion.analysis_id == Analysis.id)
        .filter(ClarificationQuestion.id == question_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clarification question not found on this change request.",
        )
    return question


@router.patch(
    "/{change_request_id}/clarification-questions/{question_id}/answer",
    response_model=ClarificationQuestionRead,
)
def answer_clarification_question(
    change_request_id: int,
    question_id: int,
    payload: ClarificationQuestionAnswer,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClarificationQuestion:
    """Supplies the missing information the AI itself asked for, right on
    the Missing Information tab - open to the same people who can comment
    on this change request (Capability.COMMENTS), not gated to a reviewer
    role, since answering is usually about knowing the answer (often the
    requester), not passing judgment on the analysis. Always marks the
    question resolved: an answer with no explanation would be
    indistinguishable from the question just having been ignored, and
    `resolved` is what the Dashboard's "Requires Clarification" tile and
    this CR's own effective status (_effective_status above) already key
    off of - so this is genuinely the first thing that can ever set it True.
    Can be called again on an already-answered question to correct it."""
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.COMMENTS)
    question = _get_clarification_question_or_404(db, change_request_id, question_id)

    question.answer_text = payload.answer
    question.answered_by = current_user.id
    question.answered_at = datetime.utcnow()
    question.resolved = True

    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.CLARIFICATION_ANSWERED,
        user_id=current_user.id,
        field_name=question.question,
        new_value=payload.answer,
        version_number=change_request.current_version or 1,
    )
    db.commit()
    db.refresh(question)
    return question


@router.patch("/{change_request_id}/security-findings/{finding_id}/status", response_model=SecurityFindingRead)
def update_security_finding_status(
    change_request_id: int,
    finding_id: int,
    payload: SecurityFindingStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SecurityFindingRead:
    """Moves a Security finding's Status - typically forward (Open ->
    Acknowledged -> Resolved), but a human may also reopen or correct one.
    The AI itself can never call this or set Acknowledged/Resolved on its
    own (see SecurityFindingItem.normalize_status) - this endpoint is the
    only place those two values are ever set."""
    change_request = _get_change_request_or_404(db, change_request_id)
    finding = _get_security_finding_or_404(db, change_request_id, finding_id)

    if not workflow_rules.can_review_analysis_findings(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update security findings on this change request.",
        )

    old_value = finding.status.value

    finding.status = payload.status
    finding.review_comment = payload.comment
    finding.reviewed_by = current_user.id
    finding.reviewed_at = datetime.utcnow()

    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.SECURITY_FINDING_STATUS_CHANGED,
        user_id=current_user.id,
        field_name=f"Security Finding #{finding.id} ({finding.category.value})",
        old_value=old_value,
        new_value=payload.status.value,
        reason=payload.comment,
        version_number=change_request.current_version or 1,
    )
    db.commit()
    db.refresh(finding)
    return finding


# --- Module 17 Phase 6: human editing of AI-generated test cases and ---
# --- implementation tasks --------------------------------------------


def _get_test_case_or_404(db: Session, change_request_id: int, test_case_id: int) -> TestCase:
    test_case = (
        db.query(TestCase)
        .join(Analysis, TestCase.analysis_id == Analysis.id)
        .filter(TestCase.id == test_case_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if test_case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found on this change request.",
        )
    return test_case


def _get_implementation_task_or_404(db: Session, change_request_id: int, task_id: int) -> ImplementationTask:
    task = (
        db.query(ImplementationTask)
        .join(Analysis, ImplementationTask.analysis_id == Analysis.id)
        .filter(ImplementationTask.id == task_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Implementation task not found on this change request.",
        )
    return task


def _full_analysis_read(db: Session, change_request: ChangeRequest, analysis: Analysis) -> AnalysisRead:
    """Builds the exact same fully-computed AnalysisRead response
    GET .../analysis returns (analysis_version/is_outdated on every test
    case/task, workflow_recommendation, repository related_files,
    traceability requirement/risk references) - shared by the edit
    endpoints below so an edited row's response carries those same
    computed fields rather than the schema defaults an edit-only code path
    would otherwise leave them at. Mirrors analyze_change_request/
    get_latest_analysis's own identical block above field-for-field on
    purpose - one more reason those computed fields must never be trusted
    from anywhere but this one shared computation."""
    response = AnalysisRead.model_validate(analysis)
    response.is_outdated = workflow_rules.is_analysis_outdated(change_request, analysis)
    for evidence in response.knowledge_evidence:
        evidence.is_outdated = response.is_outdated
    for test_case in response.test_cases:
        test_case.analysis_version = analysis.change_request_version
        test_case.is_outdated = response.is_outdated
    for task in response.implementation_tasks:
        task.analysis_version = analysis.change_request_version
        task.is_outdated = response.is_outdated
    response.workflow_recommendation = workflow_rules.recommendation_summary(change_request, analysis, _load_approval_rules(db))
    repository_linkage.annotate_analysis_response(
        response, _repository_findings_for_analysis(db, analysis.id)
    )
    traceability_linkage.annotate_analysis_response(response)
    return response


def _apply_partial_update(row, updates: dict) -> list[tuple[str, object, object]]:
    """Sets only the fields actually present in `updates` (already filtered
    to exclude_unset by the caller) onto `row`, returning (field, old, new)
    for every field whose value actually changed - a no-op field (the human
    resubmitted the same value) is never reported as a change, so it never
    shows up in the audit trail or resets edited_by/edited_at for nothing."""
    changed: list[tuple[str, object, object]] = []
    for field, new_value in updates.items():
        old_value = getattr(row, field)
        if old_value != new_value:
            changed.append((field, old_value, new_value))
            setattr(row, field, new_value)
    return changed


def _stringify_field_value(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "(none)"
    if hasattr(value, "value"):  # an enum member (Priority, TestType, ...)
        return str(value.value)
    return str(value)


def _change_summary(changed: list[tuple[str, object, object]]) -> tuple[str, str]:
    """(old_value, new_value) strings for the history row - a single
    changed field reads as just that field's own old/new value; several
    changed fields at once are each labeled with their own field name so
    nothing is ambiguous, mirroring apply_change_request_update's own
    "list every field that changed" idea (see versioning.py) just
    formatted per-field rather than as prose."""
    if len(changed) == 1:
        _field, old_value, new_value = changed[0]
        return _stringify_field_value(old_value), _stringify_field_value(new_value)
    old_parts = [f"{field}: {_stringify_field_value(old_value)}" for field, old_value, _new_value in changed]
    new_parts = [f"{field}: {_stringify_field_value(new_value)}" for field, _old_value, new_value in changed]
    return ", ".join(old_parts), ", ".join(new_parts)


@router.patch("/{change_request_id}/test-cases/{test_case_id}", response_model=TestCaseRead)
def update_test_case(
    change_request_id: int,
    test_case_id: int,
    payload: TestCaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestCaseRead:
    """Lets an authorized human correct/refine one AI-generated test case
    in place - Module 17 Phase 6's own "human editing" requirement. Same
    can_review_analysis_findings permission gate Module 14 Phase 6 already
    established for reviewing Requirements/Security findings - never a
    second, parallel editing/permission system. The AI's own prior wording
    is never lost: it's preserved as this edit's own TEST_CASE_EDITED
    history row (old_value), never a second "original" column on the row
    itself (see TestCase.edited_by's own docstring). A no-op submission
    (nothing actually changed) is a cheap read, not an audit-trail entry -
    edited_by/edited_at are only ever set when something real changed."""
    change_request = _get_change_request_or_404(db, change_request_id)
    test_case = _get_test_case_or_404(db, change_request_id, test_case_id)

    if not workflow_rules.can_review_analysis_findings(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit test cases on this change request.",
        )

    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if updates.get("steps") is not None:
        updates["steps"] = json.dumps(updates["steps"])

    changed = _apply_partial_update(test_case, updates)
    analysis_id = test_case.analysis_id

    if changed:
        test_case.edited_by = current_user.id
        test_case.edited_at = datetime.utcnow()
        test_case.edit_reason = payload.reason
        old_value, new_value = _change_summary(changed)
        history_service.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.TEST_CASE_EDITED,
            user_id=current_user.id,
            field_name=f"Test Case {test_case.test_id}",
            old_value=old_value,
            new_value=new_value,
            reason=payload.reason,
            version_number=change_request.current_version or 1,
        )
        db.commit()
        db.refresh(test_case)

    analysis = db.query(Analysis).options(*_ANALYSIS_RELATIONSHIPS).filter(Analysis.id == analysis_id).one()
    response = _full_analysis_read(db, change_request, analysis)
    return next(tc for tc in response.test_cases if tc.id == test_case.id)


@router.patch("/{change_request_id}/implementation-tasks/{task_id}", response_model=ImplementationTaskRead)
def update_implementation_task(
    change_request_id: int,
    task_id: int,
    payload: ImplementationTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImplementationTaskRead:
    """Same reasoning as update_test_case above, applied to
    ImplementationTask - see that endpoint's own docstring."""
    change_request = _get_change_request_or_404(db, change_request_id)
    task = _get_implementation_task_or_404(db, change_request_id, task_id)

    if not workflow_rules.can_review_analysis_findings(current_user, change_request, change_request.assignments):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit implementation tasks on this change request.",
        )

    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    changed = _apply_partial_update(task, updates)
    analysis_id = task.analysis_id

    if changed:
        task.edited_by = current_user.id
        task.edited_at = datetime.utcnow()
        task.edit_reason = payload.reason
        old_value, new_value = _change_summary(changed)
        history_service.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.IMPLEMENTATION_TASK_EDITED,
            user_id=current_user.id,
            field_name=f"Implementation Task #{task.id}",
            old_value=old_value,
            new_value=new_value,
            reason=payload.reason,
            version_number=change_request.current_version or 1,
        )
        db.commit()
        db.refresh(task)

    analysis = db.query(Analysis).options(*_ANALYSIS_RELATIONSHIPS).filter(Analysis.id == analysis_id).one()
    response = _full_analysis_read(db, change_request, analysis)
    return next(t for t in response.implementation_tasks if t.id == task.id)


@router.get("/{change_request_id}/analyses", response_model=list[AnalysisSummaryRead])
def list_analyses(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Analysis]:
    """Every analysis ever run for this change request, newest first - a
    lightweight summary (no child tables) so a caller can see what exists
    and pick two ids to feed into the compare endpoint below."""
    _get_change_request_or_404(db, change_request_id)
    return (
        db.query(Analysis)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .all()
    )


def _get_analysis_or_404(db: Session, change_request_id: int, analysis_id: int) -> Analysis:
    analysis = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.id == analysis_id, Analysis.change_request_id == change_request_id)
        .first()
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis {analysis_id} not found on this change request.",
        )
    return analysis


@router.get("/{change_request_id}/analysis/compare", response_model=AnalysisDeltaResponse)
def compare_change_request_analyses(
    change_request_id: int,
    from_analysis_id: Optional[int] = Query(None, alias="from"),
    to_analysis_id: Optional[int] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysisDeltaResponse:
    """A computed diff between two analyses of the same change request
    (spec sections 5/8 - "material change detection" / "analysis delta").
    Both `from` and `to` are optional: with neither given, this compares
    the two most recent analyses; with only `to` given, `from` defaults to
    whichever analysis immediately precedes it. See
    app/services/analysis_delta.py for what "computed, not AI-written"
    means here."""
    change_request = _get_change_request_or_404(db, change_request_id)

    all_analyses = (
        db.query(Analysis)
        .options(*_ANALYSIS_RELATIONSHIPS)
        .filter(Analysis.change_request_id == change_request_id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    if len(all_analyses) < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This change request has fewer than two analyses - nothing to compare yet.",
        )

    if to_analysis_id is not None:
        analysis_b = _get_analysis_or_404(db, change_request_id, to_analysis_id)
    else:
        analysis_b = all_analyses[0]  # newest

    if from_analysis_id is not None:
        analysis_a = _get_analysis_or_404(db, change_request_id, from_analysis_id)
    else:
        # Whichever analysis was run immediately before analysis_b.
        older = [a for a in all_analyses if a.created_at < analysis_b.created_at]
        if not older:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="There's no earlier analysis to compare this one against.",
            )
        analysis_a = older[0]

    if analysis_a.id == analysis_b.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`from` and `to` must refer to two different analyses.",
        )
    # Always compare in chronological order, regardless of which id the
    # caller passed as `from` vs `to`.
    if analysis_a.created_at > analysis_b.created_at:
        analysis_a, analysis_b = analysis_b, analysis_a

    delta = compare_analyses(change_request, analysis_a, analysis_b, _load_approval_rules(db))

    return AnalysisDeltaResponse(
        from_analysis_id=analysis_a.id,
        to_analysis_id=analysis_b.id,
        from_version=analysis_a.change_request_version,
        to_version=analysis_b.change_request_version,
        fields=[
            FieldComparisonRead(field=f.field, label=f.label, old_value=f.old_value, new_value=f.new_value, status=f.status)
            for f in delta.fields
        ],
        requirements_added=delta.requirements_added,
        requirements_removed=delta.requirements_removed,
        affected_components_added=delta.affected_components_added,
        affected_components_removed=delta.affected_components_removed,
        is_significant_change=delta.is_significant_change,
        significant_change_reasons=delta.significant_change_reasons,
    )


@router.get("/{change_request_id}/report/versions", response_model=list[ReportableVersionRead])
def list_reportable_versions(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReportableVersionRead]:
    """Module 20: what the "generate a report for an earlier version"
    picker renders from - every version this change request has ever had,
    newest first, each flagged with whether it's the current one and
    whether an analysis was ever run against it specifically (a version
    with has_analysis=false can still get a report - see download_report
    below - just one with no AI sections filled in)."""
    change_request = _get_change_request_or_404(db, change_request_id)
    current_version = change_request.current_version or 1

    analyzed_versions = {
        row[0]
        for row in db.query(Analysis.change_request_version)
        .filter(Analysis.change_request_id == change_request_id)
        .distinct()
        .all()
    }

    versions = sorted(change_request.versions, key=lambda v: v.version_number, reverse=True)
    return [
        ReportableVersionRead(
            version_number=v.version_number,
            is_current=v.version_number == current_version,
            change_summary=v.change_summary,
            created_at=v.created_at,
            has_analysis=v.version_number in analyzed_versions,
        )
        for v in versions
    ]


@router.get("/{change_request_id}/report")
def download_report(
    change_request_id: int,
    version: Optional[int] = Query(
        None,
        ge=1,
        description="Generate a report for this specific past version instead of the current one. "
        "Omit for the current version's report.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Module 11's report, made version-aware by Module 20. Never calls the
    AI provider and never creates a new Analysis row (report_generator.py
    only formats what run_analysis already persisted) - the one write this
    endpoint does make is a REPORT_GENERATED audit event on success, so the
    Audit section itself can show who pulled which report and when.

    Without `?version=`, this is "give me the current report": if the
    current version has actually been analyzed, it's built normally; if
    the change request has been edited since its last analysis, this is
    now a 409 (spec section 3 - "do not generate a misleading current
    report") rather than silently mixing today's CR fields with yesterday's
    analysis the way this endpoint used to. The 409 body names the version
    that WAS last analyzed, so the frontend can offer that as an explicit
    historical report instead of a dead end.

    With `?version=N`, this is an explicit historical report for version N
    - always allowed (an authorized user, i.e. anyone who can already view
    this change request - this app has never restricted viewing by role,
    only actions like editing/approving), always clearly labeled
    "HISTORICAL REPORT" in the PDF itself, and built entirely from that
    version's own data - never today's."""
    change_request = _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.REPORTS)

    try:
        context = resolve_report_context(db, change_request, requested_version=version)
    except ReportVersionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not context.is_historical and not context.analysis_matches_version:
        last_analyzed_version = (
            db.query(Analysis.change_request_version)
            .filter(Analysis.change_request_id == change_request_id)
            .order_by(Analysis.created_at.desc())
            .limit(1)
            .scalar()
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Current CR version has not been analyzed.",
                "cr_version": context.report_version,
                "last_analyzed_version": last_analyzed_version,
                "can_reanalyze": True,
            },
        )

    try:
        pdf_bytes = generate_report_pdf(change_request, context, generated_by=current_user.name)
    except ReportGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    kind = "historical-report" if context.is_historical else "analysis-report"

    # HistoryAction.REPORT_GENERATED has existed since Module 12 but was
    # never actually recorded anywhere until now - closing that gap here
    # is exactly what Module 20's own Audit section (spec section 6) needs
    # "report generated" events to show up at all.
    history_service.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.REPORT_GENERATED,
        user_id=current_user.id,
        new_value=f"Version {context.report_version}" + (" (historical)" if context.is_historical else ""),
        version_number=change_request.current_version or 1,
    )
    db.commit()

    filename = f"CR-{change_request.id:04d}-v{context.report_version}-{kind}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{change_request_id}/reports", response_model=ReportListResponse)
def list_reports_for_change_request(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportListResponse:
    """Module 24 (Reports) spec section 19: every report ever generated for
    this one change request (across every version), newest first - the same
    computed view the standalone Reports page reads from (see
    app/services/report_registry.py and app/api/reports.py), just
    pre-filtered to one change request. Powers a "Reports for this CR"
    listing without a second query mechanism."""
    _get_change_request_or_404(db, change_request_id)
    check_capability(db, current_user, Capability.REPORTS)
    rows = report_registry.list_reports_for_change_request(db, change_request_id)
    items = [
        ReportListItem(
            report_id=r.report_id,
            change_request_id=r.change_request_id,
            change_request_code=r.change_request_code,
            change_request_title=r.change_request_title,
            version=r.version,
            is_current_version=r.is_current_version,
            is_historical_pull=r.is_historical_pull,
            cr_status=r.cr_status,
            cr_status_label=r.cr_status_label,
            analysis_version=r.analysis_version,
            has_analysis=r.has_analysis,
            risk_score=r.risk_score,
            risk_bucket=r.risk_bucket_label,
            generated_by_id=r.generated_by_id,
            generated_by_name=r.generated_by_name,
            generated_at=r.generated_at,
            pull_count=r.pull_count,
        )
        for r in rows
    ]
    return ReportListResponse(items=items, total=len(items))
