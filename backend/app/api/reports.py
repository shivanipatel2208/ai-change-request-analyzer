"""Module 24: Reports section.

An aggregation layer over data that already exists (see
app/services/report_registry.py) - no new database table, no second
PDF-building system, and no second audit mechanism. Every endpoint here is
read-only: a report is never generated through this router. A
REPORT_GENERATED history event - the same event this module's whole
Reports view is built from - is recorded automatically in exactly two
places, both pre-existing: app/api/change_requests.py's own
`analyze_change_request` (the instant an analysis completes for a change
request's current version) and its long-standing `download_report`
endpoint (the Analysis Dashboard's "Download Report" button). Reports are
explicitly NOT something a person generates as a separate step (confirmed
with the project owner) - they simply appear here once an analysis exists,
and this router only ever reads that.

Every endpoint requires a logged-in user with the existing REPORTS
capability - the same permission check the Analysis Dashboard's own
report download has always used (app/services/permissions.py). This app
has never restricted which change requests a logged-in user can VIEW (see
report_generator.py's own docstring) - only actions like editing or
approving - so Reports follows that same, already-established rule rather
than inventing a new visibility restriction just for this module.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import check_capability, get_current_user
from app.database.session import get_db
from app.models.change_request import ChangeRequest
from app.models.enums import Capability, ChangeRequestStatus
from app.models.user import User
from app.schemas.report import ReportDetail, ReportListItem, ReportListResponse, ReportStatsRead
from app.services import report_registry
from app.services.report_generator import (
    ReportGenerationError,
    ReportVersionError,
    generate_report_pdf,
    resolve_report_context,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_change_request_or_404(db: Session, change_request_id: int) -> ChangeRequest:
    # Same trivial lookup app/api/change_requests.py's own (private, so not
    # imported across modules) helper does - not worth a shared import for
    # four lines with no business logic in them.
    change_request = db.get(ChangeRequest, change_request_id)
    if change_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change request not found.")
    return change_request


def _to_item(row: report_registry.ReportRow) -> ReportListItem:
    return ReportListItem(
        report_id=row.report_id,
        change_request_id=row.change_request_id,
        change_request_code=row.change_request_code,
        change_request_title=row.change_request_title,
        version=row.version,
        is_current_version=row.is_current_version,
        is_historical_pull=row.is_historical_pull,
        cr_status=row.cr_status,
        cr_status_label=row.cr_status_label,
        analysis_version=row.analysis_version,
        has_analysis=row.has_analysis,
        risk_score=row.risk_score,
        risk_bucket=row.risk_bucket_label,
        generated_by_id=row.generated_by_id,
        generated_by_name=row.generated_by_name,
        generated_at=row.generated_at,
        pull_count=row.pull_count,
    )


@router.get("", response_model=ReportListResponse)
def list_reports(
    search: Optional[str] = Query(None, description="Matches CR id, CR code (e.g. CR-0042), or CR title."),
    status_filter: Optional[ChangeRequestStatus] = Query(None, alias="status"),
    risk: Optional[str] = Query(None, description="low / medium / high / critical"),
    version: Optional[int] = Query(None, ge=1),
    generated_by: Optional[int] = Query(None, description="User id of whoever generated the report."),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportListResponse:
    check_capability(db, current_user, Capability.REPORTS)
    rows = report_registry.list_reports(
        db,
        search=search,
        status=status_filter,
        risk=risk,
        version=version,
        generated_by=generated_by,
        date_from=date_from,
        date_to=date_to,
    )
    items = [_to_item(r) for r in rows]
    return ReportListResponse(items=items, total=len(items))


@router.get("/stats", response_model=ReportStatsRead)
def report_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportStatsRead:
    check_capability(db, current_user, Capability.REPORTS)
    stats = report_registry.compute_stats(db)
    return ReportStatsRead(
        total_reports=stats.total_reports,
        change_requests_with_reports=stats.change_requests_with_reports,
        recent_reports=stats.recent_reports,
        outdated_reports=stats.outdated_reports,
    )


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportDetail:
    check_capability(db, current_user, Capability.REPORTS)
    row = report_registry.get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return ReportDetail(**_to_item(row).model_dump())


@router.get("/{report_id}/download")
def download_report_by_id(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Re-serves the PDF for an already-generated report row. Never stores
    PDF bytes (see report_registry's module docstring) - this rebuilds them
    fresh, every time, from the exact same version-consistent data
    resolve_report_context always uses, so what's downloaded here can never
    drift from what a fresh "Download Report" click would produce. Does NOT
    record a new REPORT_GENERATED event: that already happened automatically
    (see app/api/change_requests.py::analyze_change_request, or the Analysis
    Dashboard's own existing download button) - re-opening an existing
    report is not a new "pull" for audit purposes, it's the same one."""
    check_capability(db, current_user, Capability.REPORTS)
    row = report_registry.get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    change_request = _get_change_request_or_404(db, row.change_request_id)
    try:
        context = resolve_report_context(db, change_request, requested_version=row.version)
    except ReportVersionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        pdf_bytes = generate_report_pdf(change_request, context, generated_by=row.generated_by_name)
    except ReportGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    kind = "historical-report" if context.is_historical else "analysis-report"
    filename = f"{row.change_request_code}-v{context.report_version}-{kind}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
