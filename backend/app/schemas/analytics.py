"""Module 19 (Engineering Change Analytics) response shapes. Grows one
section at a time as each phase adds its own endpoint - see
app/services/analytics.py for the dataclasses these are built from and
app/api/analytics.py for the endpoints that return them.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ExecutiveMetricsRead(BaseModel):
    """Spec section 1 - see app/services/analytics.py::ExecutiveMetrics for
    what each bucket means and why Cancelled sits outside all of them."""

    model_config = ConfigDict(from_attributes=True)

    total: int
    open: int
    pending_approval: int
    approved: int
    rejected: int
    in_progress: int
    closed: int


class WorkflowMetricsRead(BaseModel):
    """Spec section 2 - see app/services/analytics.py::WorkflowMetrics.
    Every avg_*_hours field is null, not 0, when nothing in the filtered
    set has reached that milestone yet."""

    model_config = ConfigDict(from_attributes=True)

    avg_time_to_analysis_hours: Optional[float] = None
    avg_approval_time_hours: Optional[float] = None
    avg_time_to_implementation_hours: Optional[float] = None
    avg_time_to_closure_hours: Optional[float] = None
    crs_waiting_for_approval: int
    crs_with_requested_changes: int


class ExecutiveWorkflowRead(BaseModel):
    """GET /api/analytics/executive's response - executive and workflow
    metrics are returned together since the frontend's Phase 6 dashboard
    header shows both at once, computed from the exact same filtered set of
    change requests in the same request."""

    executive: ExecutiveMetricsRead
    workflow: WorkflowMetricsRead


class RiskOverTimePoint(BaseModel):
    """One calendar month's risk-bucket counts, e.g.
    {"period": "2026-03", "low": 2, "medium": 1, "high": 0, "critical": 0}."""

    model_config = ConfigDict(extra="allow")

    period: str
    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0


class RiskAnalyticsRead(BaseModel):
    """GET /api/analytics/risk's response - spec section 3."""

    current_distribution: dict[str, int]
    over_time: list[RiskOverTimePoint]


class PendingByPersonEntry(BaseModel):
    approver_name: str
    count: int


class ApprovalBlockerEntry(BaseModel):
    approval_type_label: str
    count: int


class ApprovalBottlenecksRead(BaseModel):
    """GET /api/analytics/approval-bottlenecks's response - spec section 4.
    Person-level detail is deliberately limited to a name and a count (no
    email or other account details) per the spec's own "do not expose
    unnecessary sensitive information" instruction."""

    pending_by_type: dict[str, int]
    pending_by_person: list[PendingByPersonEntry]
    avg_duration_hours_by_type: dict[str, float]
    most_common_blockers: list[ApprovalBlockerEntry]


class MostChangedFieldEntry(BaseModel):
    field_label: str
    count: int


class ChangeAnalyticsRead(BaseModel):
    """GET /api/analytics/change's response - spec section 5."""

    model_config = ConfigDict(from_attributes=True)

    crs_with_multiple_revisions: int
    avg_versions_per_cr: Optional[float] = None
    most_changed_fields: list[MostChangedFieldEntry]
    crs_returned_for_clarification: int


class CrsPerOwnerEntry(BaseModel):
    owner_name: str
    count: int


class WorkloadAnalyticsRead(BaseModel):
    """GET /api/analytics/workload's response - spec section 6. Excludes
    the app's own bulk-seed load-test bot accounts (see
    app/services/analytics.py::BULK_SEED_EMAIL_PATTERN) - the one section
    of this module where that exclusion applies, per this module's own
    planning discussion with the user."""

    crs_per_owner: list[CrsPerOwnerEntry]
    pending_reviews: int
    pending_approvals: int
    overdue_tasks: int


class AIAnalyticsRead(BaseModel):
    """GET /api/analytics/ai's response - spec section 7, labeled "AI
    recommendation statistics" throughout (never "AI accuracy") since this
    app has no ground-truth outcome data - see
    app/services/analytics.py::AIAnalyticsMetrics for the full rationale."""

    model_config = ConfigDict(from_attributes=True)

    total_analyses: int
    re_analysis_rate: Optional[float] = None
    average_confidence: Optional[float] = None
    risk_changes_after_edits: int
    ai_recommended_approvals: int
    ai_analysis_failures: int
