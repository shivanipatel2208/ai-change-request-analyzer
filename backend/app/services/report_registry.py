"""Module 24 (Reports): a read-only aggregation layer over data that
already exists elsewhere in this app - no new database table, and no
manual "generate" step either.

A REPORT_GENERATED ChangeRequestHistory event, with its new_value
formatted as "Version {N}" or "Version {N} (historical)", is recorded
automatically in exactly two places: the instant an analysis completes for
a change request's current version (app/api/change_requests.py::
analyze_change_request), and the long-standing GET /api/change-requests/
{id}/report endpoint the Analysis Dashboard's "Download Report" button
already used (Module 11/20). Reports are deliberately never generated as a
separate action a person takes (confirmed with the project owner: "the
reports should not be generated separately, once the analysis is complete,
it should reflect in the reports section") - this module only ever reads
that event stream. One (change_request_id, version) pair that has at least
one REPORT_GENERATED event against it is one "report" as far as the
Reports page is concerned. When the same pair has more than one event
(analyzed more than once, downloaded more than once, or both), the most
recent one's actor and timestamp are what the Reports page shows for that
row - every individual event is still visible, in full, on that change
request's own Activity tab; nothing is hidden or discarded, there is just
one row per report on the Reports page rather than one per event.

This is a deliberate architecture choice (confirmed with the project owner
before implementing): it keeps the Module 24 spec's own instruction -
"do not duplicate all of these databases just to create reports" - literally
true. There is no second store anywhere of "which reports exist"; this
module only ever reads ChangeRequestHistory, ChangeRequest, and Analysis,
exactly the tables that already existed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.models.analysis import Analysis
from app.models.change_request import ChangeRequest
from app.models.change_request_history import ChangeRequestHistory
from app.models.enums import ChangeRequestStatus, HistoryAction
from app.services.workflow_rules import STATUS_LABELS, risk_bucket

# Matches the new_value format both REPORT_GENERATED sources write:
# "Version 3" or "Version 3 (historical)".
_VERSION_RE = re.compile(r"Version (\d+)")


@dataclass
class ReportRow:
    """One row of the Reports page - a computed view, never its own
    database row. `report_id` is the id of the most recent
    ChangeRequestHistory REPORT_GENERATED event for this (change request,
    version) pair, used as this "report"'s identity for GET/download."""

    report_id: int
    change_request_id: int
    change_request_code: str
    change_request_title: str
    version: int
    is_current_version: bool
    is_historical_pull: bool
    cr_status: ChangeRequestStatus
    cr_status_label: str
    analysis_version: Optional[int]
    has_analysis: bool
    risk_score: Optional[float]
    risk_bucket_label: Optional[str]
    generated_by_id: Optional[int]
    generated_by_name: str
    generated_at: datetime
    pull_count: int


@dataclass
class ReportStats:
    total_reports: int
    change_requests_with_reports: int
    recent_reports: int
    outdated_reports: int


def _parse_report_version(event: ChangeRequestHistory) -> Optional[int]:
    if not event.new_value:
        return None
    match = _VERSION_RE.search(event.new_value)
    return int(match.group(1)) if match else None


def _all_report_events(db: Session) -> list[ChangeRequestHistory]:
    return (
        db.query(ChangeRequestHistory)
        .options(selectinload(ChangeRequestHistory.user))
        .filter(ChangeRequestHistory.action == HistoryAction.REPORT_GENERATED)
        .order_by(ChangeRequestHistory.created_at.asc())
        .all()
    )


def _build_rows(db: Session) -> list[ReportRow]:
    events = _all_report_events(db)
    if not events:
        return []

    grouped: dict[tuple[int, int], list[ChangeRequestHistory]] = {}
    for event in events:
        version = _parse_report_version(event)
        if version is None:
            # A report pulled before this module existed (or anything
            # otherwise unparseable) - fall back to the CR's version at the
            # time of the event rather than guessing or dropping it.
            version = event.version_number or 1
        grouped.setdefault((event.change_request_id, version), []).append(event)

    cr_ids = {cr_id for cr_id, _ in grouped}
    change_requests = {
        cr.id: cr for cr in db.query(ChangeRequest).filter(ChangeRequest.id.in_(cr_ids)).all()
    }

    analyses = db.query(Analysis).filter(Analysis.change_request_id.in_(cr_ids)).all()
    analysis_index: dict[tuple[int, int], Analysis] = {}
    for analysis in analyses:
        key = (analysis.change_request_id, analysis.change_request_version or 1)
        existing = analysis_index.get(key)
        if existing is None or analysis.created_at > existing.created_at:
            analysis_index[key] = analysis

    rows: list[ReportRow] = []
    for (cr_id, version), pulls in grouped.items():
        change_request = change_requests.get(cr_id)
        if change_request is None:
            # Defensive only - this app never deletes change requests, so
            # every event's change_request_id always resolves to a real row.
            continue
        latest = max(pulls, key=lambda e: e.created_at)
        analysis = analysis_index.get((cr_id, version))
        current_version = change_request.current_version or 1
        bucket = risk_bucket(analysis.risk_score) if analysis is not None else None
        rows.append(
            ReportRow(
                report_id=latest.id,
                change_request_id=cr_id,
                change_request_code=f"CR-{cr_id:04d}",
                change_request_title=change_request.title,
                version=version,
                is_current_version=version == current_version,
                is_historical_pull="(historical)" in (latest.new_value or ""),
                cr_status=change_request.status,
                cr_status_label=STATUS_LABELS.get(change_request.status, change_request.status.value),
                analysis_version=analysis.change_request_version if analysis is not None else None,
                has_analysis=analysis is not None,
                risk_score=analysis.risk_score if analysis is not None else None,
                risk_bucket_label=bucket.capitalize() if bucket else None,
                generated_by_id=latest.user_id,
                generated_by_name=latest.user.name if latest.user else (latest.actor_label or "System"),
                generated_at=latest.created_at,
                pull_count=len(pulls),
            )
        )

    rows.sort(key=lambda r: r.generated_at, reverse=True)
    return rows


def list_reports(
    db: Session,
    *,
    search: Optional[str] = None,
    status: Optional[ChangeRequestStatus] = None,
    risk: Optional[str] = None,
    version: Optional[int] = None,
    generated_by: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[ReportRow]:
    """The Reports page's list/search/filter, all applied in Python over
    the already-small result of _build_rows() - a brute-force approach
    that's genuinely fine at this project's scale (see
    app/services/knowledge_embeddings.py's own search_chunks() for the same
    reasoning elsewhere in this codebase)."""
    rows = _build_rows(db)

    if search:
        needle = search.strip().lower()
        if needle:
            rows = [
                r
                for r in rows
                if needle in r.change_request_title.lower()
                or needle in r.change_request_code.lower()
                or needle in str(r.change_request_id)
            ]
    if status is not None:
        rows = [r for r in rows if r.cr_status == status]
    if risk is not None:
        rows = [r for r in rows if (r.risk_bucket_label or "").lower() == risk.lower()]
    if version is not None:
        rows = [r for r in rows if r.version == version]
    if generated_by is not None:
        rows = [r for r in rows if r.generated_by_id == generated_by]
    if date_from is not None:
        rows = [r for r in rows if r.generated_at.date() >= date_from]
    if date_to is not None:
        rows = [r for r in rows if r.generated_at.date() <= date_to]

    return rows


def list_reports_for_change_request(db: Session, change_request_id: int) -> list[ReportRow]:
    return [r for r in _build_rows(db) if r.change_request_id == change_request_id]


def get_report(db: Session, report_id: int) -> Optional[ReportRow]:
    for row in _build_rows(db):
        if row.report_id == report_id:
            return row
    return None


def compute_stats(db: Session) -> ReportStats:
    rows = _build_rows(db)
    recent_cutoff = datetime.utcnow() - timedelta(days=7)
    return ReportStats(
        total_reports=len(rows),
        change_requests_with_reports=len({r.change_request_id for r in rows}),
        recent_reports=sum(1 for r in rows if r.generated_at >= recent_cutoff),
        outdated_reports=sum(1 for r in rows if not r.is_current_version),
    )
