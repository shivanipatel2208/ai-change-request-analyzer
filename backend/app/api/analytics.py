"""Module 19 (Engineering Change Analytics): read-only reporting endpoints
built entirely on top of tables Modules 1-18 already own - no new tables,
no invented numbers (spec's own "DO NOT generate fake statistics"). Every
endpoint here shares the same filter set (spec section 8: date range,
status, priority, risk, category, owner) via `_parse_filters` below, so
filtering to e.g. "High priority, Security category" gives a consistent
slice of the data no matter which section of the dashboard is asking.

Grows one endpoint per phase - this file currently has Phase 2's
executive + workflow metrics; later phases add risk analytics, approval
bottlenecks, change analytics, workload, and AI analytics endpoints
alongside it, all built on the same `_parse_filters` dependency and
`app.services.analytics.filtered_change_requests` query helper.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.enums import ChangeRequestStatus, Priority
from app.models.user import User
from app.schemas.analytics import (
    AIAnalyticsRead,
    ApprovalBottlenecksRead,
    ChangeAnalyticsRead,
    ExecutiveMetricsRead,
    ExecutiveWorkflowRead,
    RiskAnalyticsRead,
    WorkflowMetricsRead,
    WorkloadAnalyticsRead,
)
from app.services import analytics as analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_VALID_RISK_BUCKETS = {"low", "medium", "high", "critical"}
_VALID_CATEGORIES = set(analytics_service.CANONICAL_CATEGORIES) | {"Other"}


def _parse_filters(
    date_from: Optional[datetime] = Query(
        None, description="Only change requests created on/after this date (ISO 8601)."
    ),
    date_to: Optional[datetime] = Query(
        None, description="Only change requests created on/before this date (ISO 8601)."
    ),
    status: Optional[ChangeRequestStatus] = Query(None, description="Exact ChangeRequestStatus value."),
    priority: Optional[Priority] = Query(None, description="Exact Priority value."),
    risk: Optional[str] = Query(None, description="One of: low, medium, high, critical."),
    category: Optional[str] = Query(
        None, description="One of the dashboard's canonical categories, or 'Other'."
    ),
    owner_id: Optional[int] = Query(None, description="Only change requests created by this user."),
) -> analytics_service.AnalyticsFilters:
    """The one shared filter parser every analytics endpoint depends on
    (spec section 8) - so "filtered to these criteria" means the exact same
    thing everywhere on the dashboard, not a slightly different
    interpretation per section."""
    if risk is not None and risk not in _VALID_RISK_BUCKETS:
        raise HTTPException(
            status_code=422, detail=f"risk must be one of {sorted(_VALID_RISK_BUCKETS)}"
        )
    if category is not None and category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=422, detail=f"category must be one of {sorted(_VALID_CATEGORIES)}"
        )
    return analytics_service.AnalyticsFilters(
        date_from=date_from,
        date_to=date_to,
        status=status,
        priority=priority,
        risk=risk,
        category=category,
        owner_id=owner_id,
    )


@router.get("/executive", response_model=ExecutiveWorkflowRead)
def get_executive_and_workflow_metrics(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExecutiveWorkflowRead:
    """Spec sections 1 (Executive Metrics) and 2 (Workflow Metrics),
    computed together over the same filtered set of change requests."""
    rows = analytics_service.filtered_change_requests(db, filters)
    executive = analytics_service.executive_metrics(rows)
    workflow = analytics_service.workflow_metrics(rows)
    return ExecutiveWorkflowRead(
        executive=ExecutiveMetricsRead.model_validate(executive),
        workflow=WorkflowMetricsRead.model_validate(workflow),
    )


@router.get("/risk", response_model=RiskAnalyticsRead)
def get_risk_analytics(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RiskAnalyticsRead:
    """Spec section 3 - current risk distribution plus a monthly trend, both
    over the filtered set of change requests."""
    rows = analytics_service.filtered_change_requests(db, filters)
    result = analytics_service.risk_analytics(rows)
    return RiskAnalyticsRead(current_distribution=result.current_distribution, over_time=result.over_time)


@router.get("/approval-bottlenecks", response_model=ApprovalBottlenecksRead)
def get_approval_bottlenecks(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalBottlenecksRead:
    """Spec section 4 - pending approvals by type/person, average approval
    duration by type, and the approval types most often responsible for a
    Rejected/Changes Requested outcome, all over the filtered set of change
    requests. Person-level detail deliberately carries only a name and a
    count - see ApprovalBottlenecksRead's own docstring."""
    rows = analytics_service.filtered_change_requests(db, filters)
    result = analytics_service.approval_bottlenecks(rows)
    return ApprovalBottlenecksRead(
        pending_by_type=result.pending_by_type,
        pending_by_person=result.pending_by_person,
        avg_duration_hours_by_type=result.avg_duration_hours_by_type,
        most_common_blockers=result.most_common_blockers,
    )


@router.get("/change", response_model=ChangeAnalyticsRead)
def get_change_analytics(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChangeAnalyticsRead:
    """Spec section 5 - multi-revision counts, average versions per CR, the
    most frequently edited fields, and CRs still awaiting clarification on
    their latest analysis, over the filtered set of change requests."""
    rows = analytics_service.filtered_change_requests(db, filters)
    result = analytics_service.change_analytics(rows)
    return ChangeAnalyticsRead(
        crs_with_multiple_revisions=result.crs_with_multiple_revisions,
        avg_versions_per_cr=result.avg_versions_per_cr,
        most_changed_fields=result.most_changed_fields,
        crs_returned_for_clarification=result.crs_returned_for_clarification,
    )


@router.get("/workload", response_model=WorkloadAnalyticsRead)
def get_workload_analytics(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkloadAnalyticsRead:
    """Spec section 6 - CRs per owner, plus organization-wide pending
    reviews/approvals/overdue-task totals. Excludes the app's own bulk-seed
    load-test bot accounts (see filtered_change_requests's own
    `exclude_bulk_seed_owners` parameter) - confirmed with the user as the
    one section of this module where that exclusion applies."""
    rows = analytics_service.filtered_change_requests(db, filters, exclude_bulk_seed_owners=True)
    result = analytics_service.workload_analytics(rows)
    return WorkloadAnalyticsRead(
        crs_per_owner=result.crs_per_owner,
        pending_reviews=result.pending_reviews,
        pending_approvals=result.pending_approvals,
        overdue_tasks=result.overdue_tasks,
    )


@router.get("/ai", response_model=AIAnalyticsRead)
def get_ai_analytics(
    filters: analytics_service.AnalyticsFilters = Depends(_parse_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AIAnalyticsRead:
    """Spec section 7 - "AI recommendation statistics" (never "AI
    accuracy" - this app has no ground-truth outcome data to measure
    accuracy against, see AIAnalyticsRead's own docstring), over every
    analysis belonging to a change request in the filtered set."""
    rows = analytics_service.filtered_change_requests(db, filters)
    result = analytics_service.ai_analytics(rows)
    return AIAnalyticsRead.model_validate(result)
