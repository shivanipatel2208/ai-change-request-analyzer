"""Module 19 (Engineering Change Analytics): shared filtering
infrastructure every analytics metric function builds on, plus (as each
phase adds them) the metric functions themselves. Real database queries
only - no invented numbers, no placeholder/demo data (the spec's own "DO
NOT generate fake statistics" instruction, and this project's own standing
"every metric should be traceable to real database records" rule).

Filters (spec section 8: date/status/priority/risk/category/owner) are
pushed down to SQL wherever there's a real column to filter on
(created_at/status/priority/created_by); risk and category have no direct
column of their own - risk comes from the latest Analysis's risk_score,
category from its own free-text field normalized against a fixed
vocabulary - so those two are applied in Python over the already
SQL-filtered result. This mirrors the exact pattern app/api/dashboard.py
already established at this same ~3000-row scale (its own docstring: "no
AI calls ... this only reads what's already in SQLite"), not a new one
invented for this module.

CANONICAL_CATEGORIES/_normalize_category are intentionally duplicated from
dashboard.py rather than imported - a services/ module importing from an
api/ module would invert this project's usual dependency direction, and
duplicating one small, stable helper matches the same "each module owns
its own small helpers" convention app/api/my_work.py already established
for _latest_analysis/_effective_status/_risk_for.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session, selectinload

from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.enums import (
    ApprovalRecommendation,
    ApprovalStatus,
    ApprovalType,
    AssignmentRole,
    ChangeRequestStatus,
    HistoryAction,
    Priority,
)
from app.models.user import User
from app.services.approvals import approval_due_status
from app.services.workflow_rules import APPROVAL_TYPE_LABELS, FIELD_LABELS, STATUS_LABELS, risk_bucket

# Module 19: the app's own bulk-synthetic-data seed script
# (app/database/seed_bulk.py) creates every load-test row under one of 5
# accounts named exactly this way. Excluded from workload/ownership
# breakdowns only (per this module's own planning discussion with the
# user) - never from overall totals, which still count every real row in
# the database, synthetic or not.
BULK_SEED_EMAIL_PATTERN = "loadtest%@alight.com"

# Mirrors app/api/dashboard.py's own CANONICAL_CATEGORIES/_CATEGORY_ALIASES
# exactly - see this module's own docstring for why it's duplicated here
# rather than imported.
CANONICAL_CATEGORIES = [
    "Feature",
    "Bug Fix",
    "Security",
    "Database",
    "API",
    "Infrastructure",
    "Integration",
]

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


def _normalize_category(raw: Optional[str]) -> str:
    if not raw:
        return "Other"
    return _CATEGORY_ALIASES.get(raw.strip().lower(), "Other")


@dataclass
class AnalyticsFilters:
    """One shared filter set (spec section 8) applied consistently across
    every analytics endpoint - a person filtering to "High priority,
    Security category" should see that same slice everywhere on the
    dashboard, not a different interpretation per section."""

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    status: Optional[ChangeRequestStatus] = None
    priority: Optional[Priority] = None
    risk: Optional[str] = None  # "low" | "medium" | "high" | "critical"
    category: Optional[str] = None  # one of CANONICAL_CATEGORIES, or "Other"
    owner_id: Optional[int] = None


def latest_analysis(change_request: ChangeRequest) -> Optional[Analysis]:
    if not change_request.analyses:
        return None
    return max(change_request.analyses, key=lambda a: a.created_at)


def first_analysis(change_request: ChangeRequest) -> Optional[Analysis]:
    if not change_request.analyses:
        return None
    return min(change_request.analyses, key=lambda a: a.created_at)


def risk_for(change_request: ChangeRequest) -> Optional[str]:
    latest = latest_analysis(change_request)
    return risk_bucket(latest.risk_score) if latest else None


def category_for(change_request: ChangeRequest) -> Optional[str]:
    latest = latest_analysis(change_request)
    return _normalize_category(latest.category) if latest else None


def filtered_change_requests(
    db: Session, filters: AnalyticsFilters, *, exclude_bulk_seed_owners: bool = False
) -> list[ChangeRequest]:
    """Every change request matching `filters`, database-filtered on every
    column that actually has one (date range, status, priority, owner);
    risk and category are applied afterward in Python since neither is a
    direct column (see this module's own docstring). Always eager-loads
    `.analyses` - nearly every analytics metric needs the latest one for
    risk/category/confidence, so loading it once here avoids an N+1 in
    every caller.

    `exclude_bulk_seed_owners` is opt-in, used only by the workload/
    ownership metrics - every other section counts the app's own bulk
    synthetic data like any other real row, per this module's own
    "overall totals still include everyone" design note.

    Also eager-loads `.approvals`, `.history`, `.assignments` and each
    analysis's `.clarification_questions` alongside `.analyses` - between
    the executive/workflow, risk, bottleneck, change-analytics and workload
    metrics this module ends up computing, nearly every one of them needs
    at least one of these, so loading them all once here (instead of each
    phase adding its own selectinload) keeps this the one place that
    decides how a change request is fetched for analytics."""
    query = db.query(ChangeRequest).options(
        selectinload(ChangeRequest.analyses).selectinload(Analysis.clarification_questions),
        selectinload(ChangeRequest.approvals).selectinload(Approval.approver),
        selectinload(ChangeRequest.history),
        selectinload(ChangeRequest.assignments).selectinload(ChangeRequestAssignment.user),
        selectinload(ChangeRequest.creator),
    )

    if filters.date_from is not None:
        query = query.filter(ChangeRequest.created_at >= filters.date_from)
    if filters.date_to is not None:
        query = query.filter(ChangeRequest.created_at <= filters.date_to)
    if filters.status is not None:
        query = query.filter(ChangeRequest.status == filters.status)
    if filters.priority is not None:
        query = query.filter(ChangeRequest.priority == filters.priority)
    if filters.owner_id is not None:
        query = query.filter(ChangeRequest.created_by == filters.owner_id)
    if exclude_bulk_seed_owners:
        query = query.join(User, ChangeRequest.created_by == User.id).filter(
            ~User.email.like(BULK_SEED_EMAIL_PATTERN)
        )

    rows = query.order_by(ChangeRequest.created_at.desc()).all()

    if filters.risk is not None:
        rows = [cr for cr in rows if risk_for(cr) == filters.risk]
    if filters.category is not None:
        rows = [cr for cr in rows if category_for(cr) == filters.category]

    return rows


# --- Module 19 Phase 2: Executive Metrics + Workflow Metrics (spec 1/2) ---


def average_hours(durations: Iterable[Optional[timedelta]]) -> Optional[float]:
    """Average of a list of timedeltas, in hours, ignoring every None entry
    (a None means "hasn't reached that milestone yet", never coerced to a
    0-hour duration - doing that would silently pull the average toward
    zero and understate it). Returns None, not 0, when there is nothing to
    average at all, so a caller can render "No data yet" instead of a
    misleading "0.0 hours"."""
    values = [d.total_seconds() / 3600 for d in durations if d is not None]
    if not values:
        return None
    return sum(values) / len(values)


def approval_duration(approval) -> Optional[timedelta]:
    """How long a single approval sat PENDING before it was answered - None
    for one that's still pending (there's no end time yet to measure)."""
    if approval.responded_at is None:
        return None
    return approval.responded_at - approval.requested_at


def time_to_status(change_request: ChangeRequest, target_status: ChangeRequestStatus) -> Optional[timedelta]:
    """How long after creation `change_request` first reached
    `target_status`, per the real STATUS_CHANGED history trail (whose
    new_value stores the human-readable STATUS_LABELS text, not the raw
    enum - see app/services/history.py's own callers) - None if it never
    has. Uses the EARLIEST matching event, so a CR that later moved away
    from that status and came back (e.g. In Progress -> Cancelled is not
    reachable, but Approval Required -> Changes Requested -> Approval
    Required again is) is still timed from the first time it got there,
    not the most recent."""
    label = STATUS_LABELS.get(target_status, target_status.value)
    matching = [
        event.created_at
        for event in change_request.history
        if event.action == HistoryAction.STATUS_CHANGED and event.new_value == label
    ]
    if not matching:
        return None
    return min(matching) - change_request.created_at


# The 6 named Executive-Metrics buckets (spec section 1) are mutually
# exclusive by construction - every ChangeRequestStatus member appears in
# at most one set below. CANCELLED is deliberately not claimed by any of
# them: a cancelled change request is genuinely not "still open", not
# "approved", not "rejected", not "in progress" and not "closed" - forcing
# it into one of those would misrepresent it. It's still counted in
# `total` (this dashboard's own "use actual database data" rule applies to
# the total exactly like everything else), just not double-counted into a
# bucket that doesn't actually describe it.
_OPEN_STATUSES: frozenset[ChangeRequestStatus] = frozenset(
    {
        ChangeRequestStatus.DRAFT,
        ChangeRequestStatus.SUBMITTED,
        ChangeRequestStatus.PENDING_ANALYSIS,
        ChangeRequestStatus.ANALYZED,
        ChangeRequestStatus.IN_REVIEW,
        ChangeRequestStatus.CHANGES_REQUESTED,
    }
)
_IN_PROGRESS_STATUSES: frozenset[ChangeRequestStatus] = frozenset(
    {
        ChangeRequestStatus.IMPLEMENTATION_PLANNED,
        ChangeRequestStatus.IN_PROGRESS,
        ChangeRequestStatus.IMPLEMENTED,
        ChangeRequestStatus.VALIDATED,
    }
)


@dataclass
class ExecutiveMetrics:
    """Spec section 1. `open` counts every pre-approval-pipeline status
    (Draft through Changes Requested); `in_progress` counts every
    post-approval, pre-closure status (Implementation Planned through
    Validated) - see the _OPEN_STATUSES/_IN_PROGRESS_STATUSES comment
    above for why Cancelled sits outside every named bucket."""

    total: int
    open: int
    pending_approval: int
    approved: int
    rejected: int
    in_progress: int
    closed: int


def executive_metrics(rows: list[ChangeRequest]) -> ExecutiveMetrics:
    return ExecutiveMetrics(
        total=len(rows),
        open=sum(1 for cr in rows if cr.status in _OPEN_STATUSES),
        pending_approval=sum(1 for cr in rows if cr.status == ChangeRequestStatus.APPROVAL_REQUIRED),
        approved=sum(1 for cr in rows if cr.status == ChangeRequestStatus.APPROVED),
        rejected=sum(1 for cr in rows if cr.status == ChangeRequestStatus.REJECTED),
        in_progress=sum(1 for cr in rows if cr.status in _IN_PROGRESS_STATUSES),
        closed=sum(1 for cr in rows if cr.status == ChangeRequestStatus.CLOSED),
    )


@dataclass
class WorkflowMetrics:
    """Spec section 2. Every avg_*_hours field is None (never 0) when
    nothing in the filtered set has reached that milestone yet - see
    average_hours()'s own docstring for why. `crs_waiting_for_approval`
    counts change requests with at least one currently-PENDING Approval
    row (regardless of the CR's own `status` column) - a broader, real-time
    view of "who's actually waiting on a decision right now" than
    ExecutiveMetrics.pending_approval, which only reflects the CR's status
    column having been explicitly moved to Approval Required.
    `crs_with_requested_changes` reflects the CR's *current* status - a CR
    already moved on from Changes Requested (e.g. back to Under Review) no
    longer counts here, same as ExecutiveMetrics' own status-based buckets."""

    avg_time_to_analysis_hours: Optional[float]
    avg_approval_time_hours: Optional[float]
    avg_time_to_implementation_hours: Optional[float]
    avg_time_to_closure_hours: Optional[float]
    crs_waiting_for_approval: int
    crs_with_requested_changes: int


def workflow_metrics(rows: list[ChangeRequest]) -> WorkflowMetrics:
    analysis_durations = []
    for cr in rows:
        fa = first_analysis(cr)
        if fa is not None:
            analysis_durations.append(fa.created_at - cr.created_at)

    approval_durations = [approval_duration(a) for cr in rows for a in cr.approvals]
    implementation_durations = [time_to_status(cr, ChangeRequestStatus.IN_PROGRESS) for cr in rows]
    closure_durations = [time_to_status(cr, ChangeRequestStatus.CLOSED) for cr in rows]

    return WorkflowMetrics(
        avg_time_to_analysis_hours=average_hours(analysis_durations),
        avg_approval_time_hours=average_hours(approval_durations),
        avg_time_to_implementation_hours=average_hours(implementation_durations),
        avg_time_to_closure_hours=average_hours(closure_durations),
        crs_waiting_for_approval=sum(
            1 for cr in rows if any(a.status == ApprovalStatus.PENDING for a in cr.approvals)
        ),
        crs_with_requested_changes=sum(
            1 for cr in rows if cr.status == ChangeRequestStatus.CHANGES_REQUESTED
        ),
    )


# --- Module 19 Phase 3: Risk Analytics + Approval Bottlenecks (spec 3/4) --

RISK_BUCKET_LABELS: tuple[str, ...] = ("low", "medium", "high", "critical")


@dataclass
class RiskAnalytics:
    """Spec section 3. `current_distribution` mirrors the existing
    dashboard's own risk_distribution shape (low/medium/high/critical/
    not_analyzed) but computed over this module's own filtered set, not the
    whole database. `over_time` is one row per calendar month (oldest
    first), each counting - among the CRs in the filtered set whose latest
    analysis happened that month - how many landed in each risk bucket.
    This is deliberately "risk profile of change requests analyzed each
    month", not a per-CR history of every risk score it ever had (this app
    only stores each analysis's own risk_score, not a separate time series)
    - the most honest trend this data actually supports."""

    current_distribution: dict[str, int]
    over_time: list[dict]


def risk_analytics(rows: list[ChangeRequest]) -> RiskAnalytics:
    current_distribution = {bucket: 0 for bucket in RISK_BUCKET_LABELS}
    current_distribution["not_analyzed"] = 0

    # month ("YYYY-MM") -> {bucket: count}
    by_month: dict[str, dict[str, int]] = {}

    for cr in rows:
        latest = latest_analysis(cr)
        if latest is None:
            current_distribution["not_analyzed"] += 1
            continue
        bucket = risk_bucket(latest.risk_score)
        current_distribution[bucket] += 1

        month_key = latest.created_at.strftime("%Y-%m")
        month_counts = by_month.setdefault(month_key, {b: 0 for b in RISK_BUCKET_LABELS})
        month_counts[bucket] += 1

    over_time = [
        {"period": month, **counts} for month, counts in sorted(by_month.items(), key=lambda item: item[0])
    ]

    return RiskAnalytics(current_distribution=current_distribution, over_time=over_time)


# Module 19's own planning discussion with the user: this app has no real
# "team" concept anywhere - ApprovalType (Technical/Security/Product/
# Engineering Manager/Director/QA/DBA/Release/General) is the closest
# existing stand-in for "team", used here exactly like workflow_rules.py's
# own approval matrix already treats it. Person-level breakdown is
# deliberately limited to a name and a count - no email, no other account
# details - per the spec's own "do not expose unnecessary sensitive
# information" instruction.
_BOTTLENECK_LABEL_LIMIT = 10  # top N people, so one prolific approver's
# history doesn't turn this into a full account directory


@dataclass
class ApprovalBottlenecks:
    """Spec section 4. `pending_by_type`/`pending_by_person` count only
    currently-PENDING approvals (the actual queue right now);
    `avg_duration_hours_by_type` and `most_common_blockers` look at every
    RESOLVED approval instead (there's nothing to measure duration or an
    outcome for on one that's still pending)."""

    pending_by_type: dict[str, int]
    pending_by_person: list[dict]
    avg_duration_hours_by_type: dict[str, Optional[float]]
    most_common_blockers: list[dict]


def approval_bottlenecks(rows: list[ChangeRequest]) -> ApprovalBottlenecks:
    all_approvals: list[Approval] = [a for cr in rows for a in cr.approvals]
    pending = [a for a in all_approvals if a.status == ApprovalStatus.PENDING]
    resolved = [a for a in all_approvals if a.status != ApprovalStatus.PENDING]

    pending_by_type: dict[str, int] = {}
    for approval in pending:
        label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
        pending_by_type[label] = pending_by_type.get(label, 0) + 1

    pending_by_person_counts: dict[str, int] = {}
    for approval in pending:
        name = approval.approver.name
        pending_by_person_counts[name] = pending_by_person_counts.get(name, 0) + 1
    pending_by_person = [
        {"approver_name": name, "count": count}
        for name, count in sorted(pending_by_person_counts.items(), key=lambda item: item[1], reverse=True)
    ][:_BOTTLENECK_LABEL_LIMIT]

    durations_by_type: dict[str, list[float]] = {}
    for approval in resolved:
        duration = approval_duration(approval)
        if duration is None:
            continue
        label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
        durations_by_type.setdefault(label, []).append(duration.total_seconds() / 3600)
    avg_duration_hours_by_type = {
        label: (sum(values) / len(values)) for label, values in durations_by_type.items()
    }

    blocker_counts: dict[str, int] = {}
    for approval in resolved:
        if approval.status not in (ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED):
            continue
        label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
        blocker_counts[label] = blocker_counts.get(label, 0) + 1
    most_common_blockers = [
        {"approval_type_label": label, "count": count}
        for label, count in sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return ApprovalBottlenecks(
        pending_by_type=pending_by_type,
        pending_by_person=pending_by_person,
        avg_duration_hours_by_type=avg_duration_hours_by_type,
        most_common_blockers=most_common_blockers,
    )


# --- Module 19 Phase 4: Change Analytics + Workload (spec 5/6) -----------

_MOST_CHANGED_FIELDS_LIMIT = 10


@dataclass
class ChangeAnalytics:
    """Spec section 5. `crs_with_multiple_revisions`/`avg_versions_per_cr`
    read ChangeRequest.current_version directly (the same "read this
    column, don't recount ChangeRequestVersion rows" shortcut the rest of
    the app already takes - current_version IS the version count, they're
    kept in lockstep by every edit). `crs_returned_for_clarification` counts
    a CR once if its LATEST analysis has any still-unresolved
    ClarificationQuestion - the same is-it-resolved check
    app/api/my_work.py::_effective_status already uses for its own
    "requires_clarification" bucket, applied here as a count instead of a
    per-CR status label."""

    crs_with_multiple_revisions: int
    avg_versions_per_cr: Optional[float]
    most_changed_fields: list[dict]
    crs_returned_for_clarification: int


def change_analytics(rows: list[ChangeRequest]) -> ChangeAnalytics:
    versions = [cr.current_version or 1 for cr in rows]
    crs_with_multiple_revisions = sum(1 for v in versions if v > 1)
    avg_versions_per_cr = (sum(versions) / len(versions)) if versions else None

    field_counts: dict[str, int] = {}
    for cr in rows:
        for event in cr.history:
            if event.action != HistoryAction.FIELD_CHANGED or not event.field_name:
                continue
            label = FIELD_LABELS.get(event.field_name, event.field_name)
            field_counts[label] = field_counts.get(label, 0) + 1
    most_changed_fields = [
        {"field_label": label, "count": count}
        for label, count in sorted(field_counts.items(), key=lambda item: item[1], reverse=True)
    ][:_MOST_CHANGED_FIELDS_LIMIT]

    crs_returned_for_clarification = 0
    for cr in rows:
        latest = latest_analysis(cr)
        if latest is not None and any(not q.resolved for q in latest.clarification_questions):
            crs_returned_for_clarification += 1

    return ChangeAnalytics(
        crs_with_multiple_revisions=crs_with_multiple_revisions,
        avg_versions_per_cr=avg_versions_per_cr,
        most_changed_fields=most_changed_fields,
        crs_returned_for_clarification=crs_returned_for_clarification,
    )


# Which assignment roles count as "reviewing" for workload purposes -
# mirrors app/api/my_work.py::REVIEW_ROLES exactly (Reviewer/Technical
# Lead/Security Reviewer/Owner) rather than inventing a second definition
# of "who reviews" for this module.
_REVIEW_ROLES: frozenset[AssignmentRole] = frozenset(
    {
        AssignmentRole.REVIEWER,
        AssignmentRole.TECHNICAL_LEAD,
        AssignmentRole.SECURITY_REVIEWER,
        AssignmentRole.OWNER,
    }
)


@dataclass
class WorkloadAnalytics:
    """Spec section 6. `crs_per_owner` is the one per-person breakdown the
    spec actually asks for here ("CRs per owner"); `pending_reviews`/
    `pending_approvals`/`overdue_tasks` are plain totals across the
    filtered set - the spec's own wording for those three has no "per
    owner/person" qualifier, unlike Approval Bottlenecks' own
    pending_by_person (Phase 3), which does. Callers should pass
    `exclude_bulk_seed_owners=True` to filtered_change_requests() before
    computing this - see that function's own docstring for why."""

    crs_per_owner: list[dict]
    pending_reviews: int
    pending_approvals: int
    overdue_tasks: int


def workload_analytics(rows: list[ChangeRequest]) -> WorkloadAnalytics:
    owner_counts: dict[str, int] = {}
    for cr in rows:
        owner_counts[cr.creator.name] = owner_counts.get(cr.creator.name, 0) + 1
    crs_per_owner = [
        {"owner_name": name, "count": count}
        for name, count in sorted(owner_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    pending_reviews = sum(
        1 for cr in rows for a in cr.assignments if a.role in _REVIEW_ROLES
    )
    all_approvals = [a for cr in rows for a in cr.approvals]
    pending_approvals = sum(1 for a in all_approvals if a.status == ApprovalStatus.PENDING)
    overdue_tasks = sum(
        1
        for a in all_approvals
        if a.status == ApprovalStatus.PENDING and approval_due_status(a) == "overdue"
    )

    return WorkloadAnalytics(
        crs_per_owner=crs_per_owner,
        pending_reviews=pending_reviews,
        pending_approvals=pending_approvals,
        overdue_tasks=overdue_tasks,
    )


# --- Module 19 Phase 5: AI Analytics (spec 7) -----------------------------

_AI_RECOMMENDED_APPROVAL_DECISIONS: frozenset[ApprovalRecommendation] = frozenset(
    {ApprovalRecommendation.APPROVE, ApprovalRecommendation.APPROVE_WITH_CONDITIONS}
)


@dataclass
class AIAnalyticsMetrics:
    """Spec section 7 - deliberately called "AI recommendation statistics"
    everywhere in this module's API/docs, never "AI accuracy": this app has
    no ground-truth record of whether an AI recommendation was actually
    *right* in hindsight (nothing here compares an AI recommendation to a
    real-world outcome), so nothing computed below claims or implies an
    accuracy rate - only counts of what the AI actually said and did.

    Every field is computed over every Analysis row belonging to a change
    request in the filtered set (not just each CR's latest one) - "Number
    of analyses" and "Average confidence" are both about analysis RUNS, not
    change requests, so they use the same granularity throughout.
    `re_analysis_rate` is the one exception (necessarily per-CR: "did this
    CR get re-analyzed" isn't a per-analysis question) and is None (not 0)
    when nothing in the filtered set has been analyzed at all - nothing to
    compute a rate over yet."""

    total_analyses: int
    re_analysis_rate: Optional[float]
    average_confidence: Optional[float]
    risk_changes_after_edits: int
    ai_recommended_approvals: int
    ai_analysis_failures: int


def ai_analytics(rows: list[ChangeRequest]) -> AIAnalyticsMetrics:
    all_analyses: list[Analysis] = [a for cr in rows for a in cr.analyses]
    total_analyses = len(all_analyses)

    analyzed_crs = [cr for cr in rows if cr.analyses]
    re_analysis_rate = (
        sum(1 for cr in analyzed_crs if len(cr.analyses) > 1) / len(analyzed_crs)
        if analyzed_crs
        else None
    )

    average_confidence = (sum(a.confidence_score for a in all_analyses) / total_analyses) if total_analyses else None

    # How many times, across every CR's own analysis history in order, did
    # a re-analysis land in a DIFFERENT risk bucket than the one right
    # before it - not just "went up" (see RISK_ESCALATED's own, stricter,
    # notification-worthy definition in workflow_rules.py) but any change
    # at all, since this is a descriptive count, not an alert.
    risk_changes_after_edits = 0
    for cr in rows:
        ordered = sorted(cr.analyses, key=lambda a: a.created_at)
        for previous, current in zip(ordered, ordered[1:]):
            if risk_bucket(previous.risk_score) != risk_bucket(current.risk_score):
                risk_changes_after_edits += 1

    ai_recommended_approvals = sum(
        1 for a in all_analyses if a.recommendation in _AI_RECOMMENDED_APPROVAL_DECISIONS
    )

    ai_analysis_failures = sum(
        1 for cr in rows for event in cr.history if event.action == HistoryAction.AI_ANALYSIS_FAILED
    )

    return AIAnalyticsMetrics(
        total_analyses=total_analyses,
        re_analysis_rate=re_analysis_rate,
        average_confidence=average_confidence,
        risk_changes_after_edits=risk_changes_after_edits,
        ai_recommended_approvals=ai_recommended_approvals,
        ai_analysis_failures=ai_analysis_failures,
    )
