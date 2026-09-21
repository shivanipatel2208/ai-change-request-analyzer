"""Dashboard summary endpoint - metrics, risk/category distributions, and a
recent-requests list, all computed live from the database. No AI calls and
no repository analysis here yet (that's a later module); this only reads
what's already in SQLite.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.analysis import Analysis
from app.models.change_request import ChangeRequest
from app.models.enums import ChangeRequestStatus
from app.models.user import User
from app.schemas.dashboard import (
    DashboardDrillDownResponse,
    DashboardMetrics,
    DashboardSummary,
    RecentChangeRequestItem,
)
from app.services.workflow_rules import risk_bucket

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RECENT_LIMIT = 10

# The dashboard's 5 metric tiles, and - for the drill-down endpoint below -
# the predicate that decides whether one _classify_change_request() result
# counts toward that tile. Kept right next to each other so a tile and its
# drill-down filter can never quietly drift apart.
_METRIC_PREDICATES = {
    "total": lambda c: True,
    "pending_analysis": lambda c: c["is_pending_analysis"],
    "high_risk": lambda c: c["is_high_risk"],
    "approved": lambda c: c["is_approved"],
    "requires_clarification": lambda c: c["is_requires_clarification"],
}

# Fixed vocabulary shown in the "change category overview" chart. Analysis.category
# is free-text (AI-generated, later module), so incoming values are normalized
# against this list; anything that doesn't match falls into "Other".
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

def _normalize_category(raw: str | None) -> str:
    if not raw:
        return "Other"
    return _CATEGORY_ALIASES.get(raw.strip().lower(), "Other")


def _latest_analysis(change_request: ChangeRequest) -> Analysis | None:
    if not change_request.analyses:
        return None
    return max(change_request.analyses, key=lambda a: a.created_at)


def _classify_change_request(change_request: ChangeRequest) -> dict:
    """One change request's full classification for dashboard purposes -
    its risk bucket, normalized category, and which of the 5 metric tiles
    it counts toward. Both /summary (the tile numbers) and /drill-down (a
    clicked tile's actual list) are built from this exact same function, so
    a tile's count and its drill-down table can never show different change
    requests than what was actually counted."""
    latest = _latest_analysis(change_request)

    risk_label: str | None = None
    category_label: str | None = None
    is_requires_clarification = False

    if latest is not None:
        risk_label = risk_bucket(latest.risk_score)
        category_label = _normalize_category(latest.category)
        is_requires_clarification = any(not question.resolved for question in latest.clarification_questions)

    return {
        "change_request": change_request,
        "risk_label": risk_label,
        "category_label": category_label,
        "is_pending_analysis": latest is None,
        "is_high_risk": risk_label in ("high", "critical"),
        "is_approved": change_request.status == ChangeRequestStatus.APPROVED,
        "is_requires_clarification": is_requires_clarification,
    }


def _load_classified_change_requests(db: Session) -> list[dict]:
    change_requests = (
        db.query(ChangeRequest)
        .options(
            selectinload(ChangeRequest.analyses).selectinload(Analysis.clarification_questions)
        )
        # Tie-break by id (desc) whenever two rows share the same created_at.
        # created_at can have coarser resolution than how fast rows actually
        # get inserted (e.g. a fast test run, or two change requests filed
        # in the same second), and without a tiebreaker SQL doesn't promise
        # any particular order among ties - so "most recent first" wouldn't
        # reliably mean "most recently inserted first." id always increases
        # with insertion order, so this makes the ordering fully
        # deterministic, which both /summary's "recent" list and
        # /drill-down's pagination depend on to never skip or repeat a row.
        .order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc())
        .all()
    )
    return [_classify_change_request(cr) for cr in change_requests]


def _to_recent_item(classified: dict) -> RecentChangeRequestItem:
    change_request = classified["change_request"]
    return RecentChangeRequestItem(
        id=change_request.id,
        title=change_request.title,
        category=classified["category_label"],
        risk=classified["risk_label"],
        status=change_request.status.value,
        created_at=change_request.created_at,
    )


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummary:
    classified = _load_classified_change_requests(db)

    risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0, "not_analyzed": 0}
    category_breakdown = {category: 0 for category in CANONICAL_CATEGORIES}
    category_breakdown["Other"] = 0

    pending_analysis = 0
    high_risk = 0
    approved = 0
    requires_clarification = 0

    for entry in classified:
        if entry["is_pending_analysis"]:
            pending_analysis += 1
            risk_distribution["not_analyzed"] += 1
        else:
            risk_distribution[entry["risk_label"]] += 1
            category_breakdown[entry["category_label"]] += 1
            if entry["is_high_risk"]:
                high_risk += 1
            if entry["is_requires_clarification"]:
                requires_clarification += 1
        if entry["is_approved"]:
            approved += 1

    return DashboardSummary(
        metrics=DashboardMetrics(
            total_change_requests=len(classified),
            pending_analysis=pending_analysis,
            high_risk_changes=high_risk,
            approved_changes=approved,
            requires_clarification=requires_clarification,
        ),
        risk_distribution=risk_distribution,
        category_breakdown=category_breakdown,
        recent_change_requests=[_to_recent_item(entry) for entry in classified[:RECENT_LIMIT]],
    )


@router.get("/drill-down", response_model=DashboardDrillDownResponse)
def get_dashboard_drill_down(
    metric: str = Query(
        ...,
        description="Which dashboard tile was clicked.",
        pattern="^(total|pending_analysis|high_risk|approved|requires_clarification)$",
    ),
    date_from: Optional[date] = Query(None, description="Only change requests created on/after this date."),
    date_to: Optional[date] = Query(None, description="Only change requests created on/before this date."),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardDrillDownResponse:
    """Every change request behind one clicked dashboard tile, shown in the
    popup's table - never a separate/duplicated count, always the exact
    same classification /summary's own numbers come from (see
    _classify_change_request). date_from/date_to filter by the change
    request's created date (the same "Created" column the table already
    shows); page/page_size (capped at 10 - the popup never shows more than
    10 rows at once) paginate whatever's left after that filter."""
    predicate = _METRIC_PREDICATES.get(metric)
    if predicate is None:
        # Defensive only - the Query(pattern=...) above already rejects
        # anything else before this endpoint runs.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown dashboard metric.")

    classified = _load_classified_change_requests(db)
    matching = [entry for entry in classified if predicate(entry)]

    if date_from is not None:
        matching = [entry for entry in matching if entry["change_request"].created_at.date() >= date_from]
    if date_to is not None:
        matching = [entry for entry in matching if entry["change_request"].created_at.date() <= date_to]

    total = len(matching)
    start = (page - 1) * page_size
    page_entries = matching[start : start + page_size]
    items = [_to_recent_item(entry) for entry in page_entries]
    return DashboardDrillDownResponse(metric=metric, items=items, total=total, page=page, page_size=page_size)
