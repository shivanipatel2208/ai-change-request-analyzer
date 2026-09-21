"""Pydantic schemas for the Reports module (Module 24).

Reports are not their own database table - see
app/services/report_registry.py's module docstring for why. Every schema
here is a plain computed view built by hand in app/api/reports.py (and the
one small addition to app/api/change_requests.py), never from_attributes
off a single ORM row, since a "report" is assembled from ChangeRequest +
Analysis + ChangeRequestHistory together.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import ChangeRequestStatus


class ReportListItem(BaseModel):
    report_id: int
    change_request_id: int
    change_request_code: str
    change_request_title: str
    version: int
    is_current_version: bool
    is_historical_pull: bool
    cr_status: ChangeRequestStatus
    cr_status_label: str
    analysis_version: Optional[int] = None
    has_analysis: bool
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    generated_by_id: Optional[int] = None
    generated_by_name: str
    generated_at: datetime
    pull_count: int


class ReportListResponse(BaseModel):
    items: list[ReportListItem]
    total: int


class ReportDetail(ReportListItem):
    """Same fields as a list row - the actual report CONTENT is the PDF
    itself (GET /api/reports/{id}/download), shown embedded on the report
    view page rather than re-implemented a second time as HTML (confirmed
    with the project owner before implementing)."""


class ReportStatsRead(BaseModel):
    total_reports: int
    change_requests_with_reports: int
    recent_reports: int
    outdated_reports: int
