"""Response schemas for the dashboard summary endpoint.

Everything here is derived from real rows in the database at request time -
there is no hardcoded/sample data baked into these schemas or the endpoint
that fills them.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class DashboardMetrics(BaseModel):
    total_change_requests: int
    pending_analysis: int
    high_risk_changes: int
    approved_changes: int
    requires_clarification: int


class RecentChangeRequestItem(BaseModel):
    id: int
    title: str
    category: Optional[str] = None  # None = not analyzed yet
    risk: Optional[str] = None  # "low" | "medium" | "high" | "critical" | None
    status: str
    created_at: datetime


class DashboardSummary(BaseModel):
    metrics: DashboardMetrics
    # Keys: low, medium, high, critical, not_analyzed -> count of change requests
    risk_distribution: Dict[str, int]
    # Keys: the fixed category list (Feature, Bug Fix, Security, Database, API,
    # Infrastructure, Integration) plus "Other" -> count of change requests
    category_breakdown: Dict[str, int]
    recent_change_requests: List[RecentChangeRequestItem]


class DashboardDrillDownResponse(BaseModel):
    """The change requests behind one clicked dashboard tile, shown as a
    popup (see app/api/dashboard.py's own /dashboard/drill-down). Reuses
    RecentChangeRequestItem - same row shape the "Recent Change Requests"
    table already renders - rather than a second item schema, and is built
    from the exact same per-CR classification the summary endpoint's
    counts come from, so a tile's *unfiltered* count and this endpoint's
    with-no-date-filter total can never disagree.

    `total` is the count AFTER any date_from/date_to filter (so pagination
    reflects what's actually being paged through), which is why it isn't
    guaranteed to equal the tile's own number once a date range is applied
    - that's the filter working as intended, not a mismatch."""

    metric: str
    items: List[RecentChangeRequestItem]
    total: int
    page: int
    page_size: int
