"""Module 11: Report Generation, made version-aware by Module 20.

Builds a professional PDF from an EXISTING ChangeRequest + (usually) an
Analysis, for engineering manager / CAB review. This module never calls an
AI provider and never creates an Analysis row - it only reads and formats
data that Module 6's analysis engine already generated and persisted, plus
version/approval/history data Module 12 already tracks.

Module 20's core rule (spec section 7): "Do not mix Version 3 CR data with
Version 4 analysis." Before this module, a report always read the CR's
LIVE field values alongside whatever the latest analysis happened to be -
if the CR had been edited since that analysis ran, the report silently
combined data from two different versions (the outdated-analysis banner
told the reader "you might be looking at old analysis," but the CR fields
displayed were still always today's, not the version the analysis
actually ran against). resolve_report_context() below is what fixes that:
it resolves BOTH the change request fields AND the analysis to one single,
consistent version before generate_report_pdf ever touches them - either
the live current version (normal case) or a past version reconstructed
from that version's ChangeRequestVersion.snapshot (a historical report,
clearly labeled as such - never presented as "current"). The API layer
(app/api/change_requests.py::download_report) is what turns "current
version has no matching analysis" into a 409 instead of letting this
module quietly build a misleading report.

Every string that came from the AI (summary, reasoning, descriptions,
mitigations, ...) is routed through `_sanitize()` before being handed to
fpdf2: the AI providers can and do produce Unicode punctuation (smart
quotes, em dashes, ellipses, the odd emoji) that the PDF's core fonts
can't encode. Rather than letting one such character blow up report
generation for an otherwise-fine analysis, common Unicode punctuation is
transliterated to its ASCII equivalent and anything else unmappable is
replaced rather than raising - "handle PDF generation errors gracefully"
starts here, not just in the try/except at the API layer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

from fpdf import FPDF
from sqlalchemy.orm import Session, selectinload

from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_history import ChangeRequestHistory
from app.models.change_request_version import ChangeRequestVersion
from app.models.enums import ApprovalStatus, HistoryAction
from app.services.workflow_rules import (
    APPROVAL_STATUS_LABELS,
    APPROVAL_TYPE_LABELS,
    FIELD_LABELS,
    STATUS_LABELS,
)

PAGE_MARGIN = 18
ACCENT_COLOR = (67, 56, 202)  # the app's #4338ca purple
TEXT_COLOR = (16, 24, 40)
MUTED_COLOR = (102, 112, 133)
BORDER_COLOR = (208, 213, 221)
HISTORICAL_COLOR = (30, 64, 175)  # a neutral blue - "labeled", not "warning"
HISTORICAL_FILL = (239, 246, 255)
WARNING_COLOR = (146, 64, 14)
WARNING_FILL = (255, 244, 229)
RISK_COLORS = {
    "low": (5, 150, 105),
    "medium": (202, 138, 4),
    "high": (217, 119, 6),
    "critical": (220, 38, 38),
}


class ReportGenerationError(Exception):
    """Raised when the PDF can't be built. Caught by the API layer and
    turned into a clean error response instead of a raw traceback."""


class ReportVersionError(Exception):
    """Raised when a requested version number doesn't exist for this
    change request - never below 1, never above the CR's current
    version."""


_UNICODE_REPLACEMENTS = {
    "‘": "'",
    "’": "'",
    "‚": ",",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
    " ": " ",
    "•": "-",
    "→": "->",
    "←": "<-",
}


def _sanitize(value) -> str:
    """Every AI-written string passes through here before reaching fpdf2's
    core (non-Unicode) fonts. Known "smart" punctuation is transliterated
    to ASCII; anything else outside Latin-1 is replaced rather than
    crashing the whole report over a single stray character."""
    if value is None:
        return ""
    text = str(value)
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _title_case(value: Optional[str]) -> str:
    if not value:
        return "-"
    return _sanitize(value).replace("_", " ").title()


def _fmt_date(value) -> str:
    if value is None:
        return "Not provided"
    try:
        return value.strftime("%B %d, %Y")
    except AttributeError:
        return _sanitize(value)


def _fmt_datetime(value) -> str:
    if value is None:
        return "-"
    try:
        return value.strftime("%B %d, %Y %H:%M UTC")
    except AttributeError:
        return _sanitize(value)


def _enum_value(member) -> Optional[str]:
    return member.value if member is not None else None


def _priority_label(value) -> str:
    """Priority arrives as a real Priority enum member when read straight
    off a live ChangeRequest, but as a plain string once it's come back out
    of a ChangeRequestVersion.snapshot (see workflow_rules.normalize_field_
    value) - this reads either shape the same way."""
    if value is None:
        return "-"
    raw = value.value if hasattr(value, "value") else value
    return _title_case(raw)


# --- Version-aware field/context resolution (Module 20) -------------------
#
# ResolvedFields is the single shape generate_report_pdf renders from - it
# never reads change_request.title/.description/... directly, so it can't
# accidentally mix a historical version's CR data with the live row's.


@dataclass
class ResolvedFields:
    title: str
    description: str
    business_objective: Optional[str]
    priority_label: str
    requested_by: Optional[str]
    target_system: Optional[str]
    desired_deadline: Optional[date]
    business_impact: Optional[str]
    technical_impact: Optional[str]
    customer_impact: Optional[str]
    environment: Optional[str]
    dependencies_note: Optional[str]
    compliance_requirements: Optional[str]


def _resolve_fields_live(change_request: ChangeRequest) -> ResolvedFields:
    return ResolvedFields(
        title=change_request.title,
        description=change_request.description,
        business_objective=change_request.business_objective,
        priority_label=_priority_label(change_request.priority),
        requested_by=change_request.requested_by,
        target_system=change_request.target_system,
        desired_deadline=change_request.desired_deadline,
        business_impact=change_request.business_impact,
        technical_impact=change_request.technical_impact,
        customer_impact=change_request.customer_impact,
        environment=change_request.environment,
        dependencies_note=change_request.dependencies_note,
        compliance_requirements=change_request.compliance_requirements,
    )


def _resolve_fields_from_snapshot(snapshot_json: str, *, fallback: ResolvedFields) -> ResolvedFields:
    """`fallback` (the live row's fields) only ever backfills title/
    description - the two fields a report can't sensibly render blank -
    for the edge case of a Version 1 snapshot backfilled by init_db before
    every column existed. Every other field is read strictly from the
    snapshot: if it wasn't set as of that version, it wasn't set, and the
    report should say so rather than silently borrowing today's value."""
    try:
        data = json.loads(snapshot_json) if snapshot_json else {}
    except (TypeError, ValueError):
        data = {}

    deadline = None
    deadline_raw = data.get("desired_deadline")
    if deadline_raw:
        try:
            deadline = date.fromisoformat(deadline_raw)
        except (TypeError, ValueError):
            deadline = None

    return ResolvedFields(
        title=data.get("title") or fallback.title,
        description=data.get("description") or fallback.description,
        business_objective=data.get("business_objective"),
        priority_label=_priority_label(data.get("priority")),
        requested_by=data.get("requested_by"),
        target_system=data.get("target_system"),
        desired_deadline=deadline,
        business_impact=data.get("business_impact"),
        technical_impact=data.get("technical_impact"),
        customer_impact=data.get("customer_impact"),
        environment=data.get("environment"),
        dependencies_note=data.get("dependencies_note"),
        compliance_requirements=data.get("compliance_requirements"),
    )


# Mirrors app/api/change_requests.py::_ANALYSIS_RELATIONSHIPS - duplicated
# rather than imported (same api/ vs services/ dependency-direction
# convention already used for CANONICAL_CATEGORIES in analytics.py/
# dashboard.py) so this module never depends on the API layer.
_REPORT_ANALYSIS_RELATIONSHIPS = (
    selectinload(Analysis.requirements),
    selectinload(Analysis.affected_components),
    selectinload(Analysis.dependencies),
    selectinload(Analysis.risks),
    selectinload(Analysis.impact_assessments),
    selectinload(Analysis.security_findings),
    selectinload(Analysis.clarification_questions),
    selectinload(Analysis.test_cases),
    selectinload(Analysis.implementation_tasks),
)


@dataclass
class ReportContext:
    """Everything generate_report_pdf needs, already resolved to one
    consistent change-request version - the piece that makes "don't mix
    Version 3 CR data with Version 4 analysis" actually true rather than
    just documented. `report_version` is the version this ENTIRE report
    represents; `analysis` (if not None) is guaranteed to have been run
    against exactly that version - never a newer or older one."""

    report_version: int
    is_historical: bool
    fields: ResolvedFields
    analysis: Optional[Analysis]
    approvals: list[Approval] = field(default_factory=list)
    versions: list[ChangeRequestVersion] = field(default_factory=list)
    history_events: list[ChangeRequestHistory] = field(default_factory=list)

    @property
    def analysis_matches_version(self) -> bool:
        return self.analysis is not None


def resolve_report_context(
    db: Session,
    change_request: ChangeRequest,
    *,
    requested_version: Optional[int] = None,
) -> ReportContext:
    """Resolves which version this report represents (the CR's current
    version by default, or `requested_version` for an explicit historical
    report), then reconstructs every piece of data a report needs - CR
    fields, the analysis (if any) run against exactly that version,
    approvals requested against that version or earlier, the full version
    history, and the audit trail up through that version - from that one
    version, consistently.

    Approvals/history are scoped with "at or before this version" rather
    than "only exactly this version" - an approval or history event from
    an earlier version is still part of this version's story (nothing has
    un-happened), but one from a LATER version hasn't occurred yet as far
    as a report representing an earlier point in time is concerned. For a
    report of the CR's current version this scoping is a no-op (nothing
    in this change request's own history can be dated after its own
    current version), so today's "current report" behavior is unchanged.
    """
    current_version = change_request.current_version or 1
    target_version = requested_version if requested_version is not None else current_version

    if target_version < 1 or target_version > current_version:
        raise ReportVersionError(
            f"Version {target_version} does not exist for this change request "
            f"(current version is {current_version})."
        )

    is_historical = target_version != current_version
    live_fields = _resolve_fields_live(change_request)

    if is_historical:
        version_row = next(
            (v for v in change_request.versions if v.version_number == target_version), None
        )
        if version_row is None:
            # Defensive - versions are created sequentially and never
            # deleted, so every version from 1..current_version should
            # always have a row.
            raise ReportVersionError(f"No version record found for version {target_version}.")
        fields = _resolve_fields_from_snapshot(version_row.snapshot, fallback=live_fields)
    else:
        fields = live_fields

    analysis = (
        db.query(Analysis)
        .options(*_REPORT_ANALYSIS_RELATIONSHIPS)
        .filter(
            Analysis.change_request_id == change_request.id,
            Analysis.change_request_version == target_version,
        )
        .order_by(Analysis.created_at.desc())
        .first()
    )

    approvals = sorted(
        (a for a in change_request.approvals if (a.cr_version or 1) <= target_version),
        key=lambda a: a.requested_at,
    )
    # Same "at or before this version" scoping as approvals/history_events
    # above - a historical report must never show a LATER version's row in
    # its own Change History table. Each ChangeRequestVersion's
    # change_summary embeds the actual old/new field text for that edit
    # (e.g. "Description changed from ... to <the new text>"), so an
    # unfiltered list would leak a future version's field values into an
    # earlier version's report exactly the way spec section 7 forbids.
    versions = sorted(
        (v for v in change_request.versions if v.version_number <= target_version),
        key=lambda v: v.version_number,
    )
    history_events = sorted(
        (h for h in change_request.history if (h.version_number or 1) <= target_version),
        key=lambda h: h.created_at,
    )

    return ReportContext(
        report_version=target_version,
        is_historical=is_historical,
        fields=fields,
        analysis=analysis,
        approvals=approvals,
        versions=versions,
        history_events=history_events,
    )


class _ReportPDF(FPDF):
    def __init__(self, cr_code: str, cr_title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._cr_code = cr_code
        self._cr_title = _sanitize(cr_title)
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(PAGE_MARGIN, 14, PAGE_MARGIN)
        # Computed AFTER set_margins() - the constructor's own default
        # margins (10mm) are not the ones this report actually uses, and
        # computing this too early silently produced a page width ~16mm
        # wider than what's actually printable.
        self._page_width = self.w - self.l_margin - self.r_margin
        self.set_title(f"{cr_code} Analysis Report")

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED_COLOR)
        self.set_xy(self.l_margin, 8)
        self.cell(self._page_width - 20, 5, f"{self._cr_code} - {self._cr_title}", new_x="RIGHT", new_y="TOP")
        self.set_xy(self.w - self.r_margin - 20, 8)
        self.cell(20, 5, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_y(15)
        self.set_draw_color(*BORDER_COLOR)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED_COLOR)
        self.cell(
            self._page_width,
            8,
            "Generated by AI Change Request Analyzer - contains AI-generated analysis, for human review",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def section_heading(self, number: int, title: str):
        if self.get_y() > self.h - 35:
            self.add_page()
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*ACCENT_COLOR)
        self.cell(self._page_width, 8, f"{number}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_draw_color(*ACCENT_COLOR)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 28, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)
        self.set_text_color(*TEXT_COLOR)

    def body_paragraph(self, text: Optional[str], *, empty: str = "No information available."):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*TEXT_COLOR)
        clean = _sanitize(text).strip()
        self.multi_cell(self._page_width, 5.5, clean if clean else empty, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def label_value(self, label: str, value: str):
        self.set_font("Helvetica", "B", 9.5)
        self.set_text_color(*MUTED_COLOR)
        label_w = 42
        self.cell(label_w, 5.8, _sanitize(label), new_x="RIGHT", new_y="TOP")
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*TEXT_COLOR)
        self.multi_cell(
            self._page_width - label_w,
            5.8,
            _sanitize(value) if value else "-",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def item_card(self, title: str, fields: Iterable[tuple[str, str]], body_label: str = None, body_text: str = None):
        """One bordered-ish list entry: a bold title line, label:value
        pairs, optionally one longer body paragraph, then a divider."""
        if self.get_y() > self.h - 30:
            self.add_page()
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*TEXT_COLOR)
        self.multi_cell(self._page_width, 5.5, _sanitize(title), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        for label, value in fields:
            self.set_text_color(*MUTED_COLOR)
            self.write(5, f"{_sanitize(label)}: ")
            self.set_text_color(*TEXT_COLOR)
            self.write(5, f"{_sanitize(value)}   ")
        self.ln(6)
        if body_label:
            self.set_font("Helvetica", "B", 8.5)
            self.set_text_color(*MUTED_COLOR)
            self.cell(self._page_width, 4.5, _sanitize(body_label), new_x="LMARGIN", new_y="NEXT")
        if body_text:
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*TEXT_COLOR)
            self.multi_cell(self._page_width, 5, _sanitize(body_text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)
        self.set_draw_color(*BORDER_COLOR)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def table(self, columns: list[tuple[str, float]], rows: list[list[str]], *, empty: str = "No records."):
        """A simple bordered table: `columns` is [(header, width_fraction),
        ...] with widths as fractions of the page width (so callers never
        have to hand-compute mm). Row cells wrap onto multiple lines when
        needed (multi_cell), and every row in the same table is drawn at
        the same height as its tallest cell so nothing overlaps - the
        "avoid broken tables and overflow" requirement (spec section 8)."""
        if self.get_y() > self.h - 40:
            self.add_page()
        widths = [self._page_width * frac for _, frac in columns]
        line_h = 5

        def _row_height(cells: list[str]) -> float:
            max_lines = 1
            for cell_text, w in zip(cells, widths):
                text = _sanitize(cell_text) or "-"
                # fpdf2 doesn't expose a line-count helper directly, so
                # this counts characters-per-line via get_string_width -
                # good enough for a report table (never pixel-perfect
                # typesetting), and always at least 1 line.
                words = text.split(" ")
                lines = 1
                current = ""
                for word in words:
                    trial = f"{current} {word}".strip()
                    if self.get_string_width(trial) > w - 2 and current:
                        lines += 1
                        current = word
                    else:
                        current = trial
                max_lines = max(max_lines, lines)
            return max_lines * line_h + 2

        # Header row
        self.set_font("Helvetica", "B", 8.5)
        self.set_fill_color(243, 244, 246)
        self.set_text_color(*TEXT_COLOR)
        self.set_draw_color(*BORDER_COLOR)
        y0 = self.get_y()
        x0 = self.l_margin
        for (label, _), w in zip(columns, widths):
            self.set_xy(x0, y0)
            self.cell(w, 7, _sanitize(label), border=1, fill=True, align="L")
            x0 += w
        self.set_xy(self.l_margin, y0 + 7)

        if not rows:
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*MUTED_COLOR)
            self.cell(sum(widths), 8, _sanitize(empty), border=1, new_x="LMARGIN", new_y="NEXT")
            self.ln(2)
            return

        self.set_font("Helvetica", "", 8.5)
        for row_cells in rows:
            if self.get_y() > self.h - 25:
                self.add_page()
                y0 = self.get_y()
                x0 = self.l_margin
                self.set_font("Helvetica", "B", 8.5)
                self.set_fill_color(243, 244, 246)
                for (label, _), w in zip(columns, widths):
                    self.set_xy(x0, y0)
                    self.cell(w, 7, _sanitize(label), border=1, fill=True, align="L")
                    x0 += w
                self.set_xy(self.l_margin, y0 + 7)
                self.set_font("Helvetica", "", 8.5)

            row_h = _row_height(row_cells)
            y0 = self.get_y()
            x0 = self.l_margin
            self.set_text_color(*TEXT_COLOR)
            for cell_text, w in zip(row_cells, widths):
                self.set_xy(x0, y0)
                self.multi_cell(w, line_h, _sanitize(cell_text) if cell_text else "-", border=1)
                x0 += w
            self.set_xy(self.l_margin, y0 + row_h)
        self.ln(3)


def _parse_security_analysis(raw: Optional[str]) -> tuple[str, list[str]]:
    if not raw:
        return "", []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return "", []
    return data.get("summary") or "", list(data.get("concerns") or [])


def generate_report_pdf(
    change_request: ChangeRequest, context: ReportContext, *, generated_by: Optional[str] = None
) -> bytes:
    """Builds the full PDF and returns its raw bytes, entirely from
    `context` (see resolve_report_context) plus a small number of purely
    structural, never-version-specific facts read straight off
    `change_request` (its id, its creator, and its overall creation date -
    none of which a past version could ever have differed on). Every
    version-sensitive value - title, description, priority, and whether an
    analysis exists at all - comes from `context`, never from
    `change_request` directly, so a historical report can never
    accidentally show today's data.

    `generated_by` is the name of whoever clicked "Download Report" - it
    has no bearing on what's IN the report, it's just printed on the
    metadata line so two people looking at two PDFs of the same change
    request can tell them apart."""
    try:
        fields = context.fields
        analysis = context.analysis
        cr_code = f"CR-{change_request.id:04d}"
        pdf = _ReportPDF(cr_code, fields.title)
        pdf.add_page()
        pw = pdf._page_width  # noqa: SLF001 - internal helper, same module

        # --- Cover -----------------------------------------------------
        pdf.ln(18)
        pdf.set_font("Helvetica", "B", 21)
        pdf.set_text_color(*ACCENT_COLOR)
        pdf.multi_cell(pw, 10, "Change Request Analysis Report", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*TEXT_COLOR)
        pdf.multi_cell(pw, 8, f"{cr_code} - {_sanitize(fields.title)}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        if context.is_historical:
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*HISTORICAL_COLOR)
            pdf.multi_cell(
                pw, 6, f"HISTORICAL REPORT - Version {context.report_version}", align="C", new_x="LMARGIN", new_y="NEXT"
            )
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*MUTED_COLOR)
        pdf.multi_cell(
            pw,
            6,
            f"Generated {datetime.utcnow().strftime('%B %d, %Y')} - for engineering manager / CAB review",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(6)

        # --- Report metadata (Module 13 Phase 3, made version-safe by
        # Module 20) --------------------------------------------------
        # Spec section 3: never generate a misleadingly "current" report.
        # By the time this function is called, the API layer has already
        # confirmed either (a) this IS the current version and it DOES
        # have a matching analysis, or (b) this is a deliberately-
        # requested historical report - so the only two states this PDF
        # ever has to render are "current and consistent" or "historical
        # and clearly labeled," never "stale but pretending to be current."
        cr_version = change_request.current_version or 1
        report_version = context.report_version

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED_COLOR)
        meta_bits = [f"Change Request Version {report_version}"]
        if context.is_historical:
            meta_bits.append(f"Current Version is {cr_version}")
        meta_bits.append(
            f"Analysis Version {analysis.change_request_version}" if analysis is not None else "No analysis recorded at this version"
        )
        meta_bits.append(f"Generated {datetime.utcnow().strftime('%B %d, %Y %H:%M')} UTC")
        if generated_by:
            meta_bits.append(f"Generated by {_sanitize(generated_by)}")
        pdf.multi_cell(pw, 5, "  |  ".join(meta_bits), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        if context.is_historical:
            pdf.set_fill_color(*HISTORICAL_FILL)
            pdf.set_draw_color(*HISTORICAL_COLOR)
            pdf.set_text_color(*HISTORICAL_COLOR)
            pdf.set_line_width(0.3)
            pdf.set_font("Helvetica", "B", 9.5)
            note = (
                f"This report represents Version {report_version} of this change request, not its current "
                f"Version {cr_version}. The Change Request fields below reflect Version {report_version} "
                "exactly as it stood then; the analysis (if shown) is the one that ran against that same "
                "version - never a newer or older one."
            )
            pdf.multi_cell(pw, 6, _sanitize(note), align="C", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.set_line_width(0.2)
            pdf.set_text_color(*TEXT_COLOR)
            pdf.ln(4)
        else:
            pdf.ln(4)

        no_analysis_note = (
            f"No analysis was performed against Version {report_version} of this change request - "
            "the sections below that depend on AI analysis are not available for this version."
        )

        # --- 1. Executive Summary --------------------------------------
        pdf.section_heading(1, "Executive Summary")
        if analysis is not None:
            pdf.body_paragraph(analysis.summary)
            pdf.label_value("Risk Score", f"{analysis.risk_score / 10:.1f} / 10")
            pdf.label_value("Complexity", _title_case(_enum_value(analysis.complexity)))
            pdf.label_value("AI Confidence", f"{round(analysis.confidence_score)}%")
            pdf.label_value("Recommendation", _title_case(_enum_value(analysis.recommendation)))
        else:
            pdf.body_paragraph(None, empty=no_analysis_note)

        # --- 2. Change Request -------------------------------------------
        pdf.section_heading(2, "Change Request")
        pdf.label_value("Title", fields.title)
        # Module 23: previously the only way to see this change request is
        # Closed was to read through the Audit table at the end of the
        # report - a one-line headline here means the reader doesn't have
        # to. Always the change request's real, current status (not
        # whatever it was at a historical report's own version), which is
        # exactly why this line lives outside the historical-vs-current
        # fields above.
        pdf.label_value("Current Status", STATUS_LABELS.get(change_request.status, change_request.status.value))
        pdf.label_value("Priority", fields.priority_label)
        pdf.label_value("Requested By", fields.requested_by or "Not provided")
        pdf.label_value("Target System", fields.target_system or "Not provided")
        pdf.label_value("Desired Deadline", _fmt_date(fields.desired_deadline))
        pdf.label_value("Environment", fields.environment or "Not provided")
        pdf.label_value("Created", _fmt_date(change_request.created_at))
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*MUTED_COLOR)
        pdf.cell(pw, 5.5, "Description", new_x="LMARGIN", new_y="NEXT")
        pdf.body_paragraph(fields.description)

        # --- 3. Business Objective --------------------------------------
        pdf.section_heading(3, "Business Objective")
        pdf.body_paragraph(fields.business_objective, empty="No business objective was provided.")

        # --- 4. Business Impact -------------------------------------------
        pdf.section_heading(4, "Business Impact")
        pdf.body_paragraph(fields.business_impact, empty="No business impact was recorded for this change.")
        if fields.customer_impact:
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(pw, 5.5, "Customer Impact", new_x="LMARGIN", new_y="NEXT")
            pdf.body_paragraph(fields.customer_impact)

        # --- 5. Classification -------------------------------------------
        pdf.section_heading(5, "Classification")
        if analysis is not None:
            pdf.label_value("Category", analysis.category or "-")
            pdf.label_value("Confidence", f"{round(analysis.confidence_score)}%")
            pdf.ln(1)
            pdf.body_paragraph(analysis.classification_reason, empty="No classification reasoning was provided.")
        else:
            pdf.body_paragraph(None, empty=no_analysis_note)

        # --- 6. Requirements -----------------------------------------------
        pdf.section_heading(6, "Requirements")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.requirements:
            pdf.body_paragraph(None, empty="No requirements were extracted for this change.")
        else:
            for req in analysis.requirements:
                pdf.item_card(
                    req.description,
                    [
                        ("Type", _title_case(req.requirement_type.value if req.requirement_type else None)),
                        ("Priority", _title_case(_enum_value(req.priority))),
                    ],
                )

        # --- 7. Technical Impact -------------------------------------------
        pdf.section_heading(7, "Technical Impact")
        pdf.body_paragraph(fields.technical_impact, empty="No technical impact was recorded for this change.")
        if analysis is not None and analysis.complexity_reasoning:
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(pw, 5.5, "AI Technical Impact Reasoning", new_x="LMARGIN", new_y="NEXT")
            pdf.body_paragraph(analysis.complexity_reasoning)
        if analysis is not None and analysis.affected_components:
            names = ", ".join(
                f"{c.component_name} ({_title_case(c.component_type.value if c.component_type else None)})"
                for c in analysis.affected_components
            )
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(28, 5.5, "Affects:", new_x="RIGHT", new_y="TOP")
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*TEXT_COLOR)
            pdf.multi_cell(pw - 28, 5.5, _sanitize(names), new_x="LMARGIN", new_y="NEXT")

        # --- 8. Affected Components -----------------------------------------
        pdf.section_heading(8, "Affected Components")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.affected_components:
            pdf.body_paragraph(None, empty="No affected components were identified.")
        else:
            for comp in analysis.affected_components:
                pdf.item_card(
                    f"{comp.component_name} ({_title_case(comp.component_type.value if comp.component_type else None)})",
                    [
                        ("Impact", _title_case(_enum_value(comp.impact_level))),
                        ("Confidence", f"{round(comp.confidence)}%"),
                    ],
                    body_label="Reason",
                    body_text=comp.reason,
                )

        # --- 9. Dependencies -------------------------------------------------
        pdf.section_heading(9, "Dependencies")
        if fields.dependencies_note:
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(pw, 5.5, "Noted by the requester/owner", new_x="LMARGIN", new_y="NEXT")
            pdf.body_paragraph(fields.dependencies_note)
            pdf.ln(1)
        if analysis is None:
            if not fields.dependencies_note:
                pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.dependencies:
            pdf.body_paragraph(None, empty="No dependencies were identified by AI analysis.")
        else:
            for dep in analysis.dependencies:
                pdf.item_card(
                    f"{dep.dependency_name} ({_title_case(dep.dependency_type.value if dep.dependency_type else None)})",
                    [("Impact", _title_case(_enum_value(dep.impact_level)))],
                    body_label="Reason",
                    body_text=dep.reason,
                )

        # --- 10. Security Assessment -----------------------------------------
        pdf.section_heading(10, "Security")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        else:
            summary, concerns = _parse_security_analysis(analysis.security_analysis)
            security_risks = [r for r in analysis.risks if _enum_value(r.category) == "security"]
            if security_risks:
                worst = min(
                    security_risks,
                    key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(_enum_value(r.severity), 9),
                )
                pdf.label_value("Security Risk Level", _title_case(_enum_value(worst.severity)))
            else:
                pdf.body_paragraph(
                    None, empty="The AI didn't score a specific security risk level for this change."
                )
            if summary:
                pdf.ln(1)
                pdf.body_paragraph(summary)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(pw, 5.5, "Potential Concerns", new_x="LMARGIN", new_y="NEXT")
            if concerns:
                for concern in concerns:
                    pdf.set_font("Helvetica", "", 9.5)
                    pdf.set_text_color(*TEXT_COLOR)
                    pdf.multi_cell(pw, 5.2, f"- {_sanitize(concern)}", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.body_paragraph(None, empty="No specific concerns were flagged.")
            mitigations = [r.mitigation for r in security_risks if r.mitigation]
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(pw, 5.5, "Recommended Mitigations", new_x="LMARGIN", new_y="NEXT")
            if mitigations:
                for mitigation in mitigations:
                    pdf.set_font("Helvetica", "", 9.5)
                    pdf.set_text_color(*TEXT_COLOR)
                    pdf.multi_cell(pw, 5.2, f"- {_sanitize(mitigation)}", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.body_paragraph(None, empty="No specific mitigations beyond the concerns above were provided.")

        # --- 11. Risk ---------------------------------------------
        pdf.section_heading(11, "Risk")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        else:
            risk_bucket = _risk_bucket_label(analysis.risk_score)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*MUTED_COLOR)
            pdf.cell(42, 5.8, "Overall Risk Score", new_x="RIGHT", new_y="TOP")
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*RISK_COLORS.get(risk_bucket.lower(), TEXT_COLOR))
            pdf.cell(
                pw - 42,
                5.8,
                _sanitize(f"{analysis.risk_score / 10:.1f} / 10 ({risk_bucket})"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(*TEXT_COLOR)
            pdf.ln(1)
            if not analysis.risks:
                pdf.body_paragraph(None, empty="No risks were identified for this change.")
            for risk in analysis.risks:
                pdf.item_card(
                    f"{_title_case(_enum_value(risk.category))} risk",
                    [
                        ("Severity", _title_case(_enum_value(risk.severity))),
                        ("Probability", f"{round(risk.probability * 100)}%"),
                        ("Score", f"{round(risk.score)}/100"),
                    ],
                    body_label="Explanation",
                    body_text=risk.description,
                )
                if risk.mitigation:
                    pdf.set_font("Helvetica", "B", 8.5)
                    pdf.set_text_color(*MUTED_COLOR)
                    pdf.cell(pw, 4.5, "Mitigation", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*TEXT_COLOR)
                    pdf.multi_cell(pw, 5, _sanitize(risk.mitigation), new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(2)

        # --- 12. Complexity ----------------------------------------------------
        pdf.section_heading(12, "Complexity")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        else:
            pdf.label_value("Level", _title_case(_enum_value(analysis.complexity)))
            pdf.ln(1)
            pdf.body_paragraph(analysis.complexity_reasoning, empty="No complexity reasoning was provided.")

        # --- 13. Effort Estimate -------------------------------------------------
        pdf.section_heading(13, "Effort")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        else:
            pdf.body_paragraph(analysis.effort_estimate, empty="No effort estimate was provided.")

        # --- 14. Missing Information (clarification questions) -----------------
        pdf.section_heading(14, "Missing Information")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.clarification_questions:
            pdf.body_paragraph(None, empty="No open clarification items - nothing blocking this change.")
        else:
            for question in analysis.clarification_questions:
                pdf.item_card(
                    question.question,
                    [
                        ("Priority", _title_case(_enum_value(question.priority))),
                        ("Status", "Resolved" if question.resolved else "Open"),
                    ],
                    body_label="Why it matters",
                    body_text=question.reason,
                )

        # --- 15. Test Strategy ---------------------------------------------------
        pdf.section_heading(15, "Test Strategy")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.test_cases:
            pdf.body_paragraph(None, empty="No test cases were suggested.")
        else:
            for test in analysis.test_cases:
                pdf.item_card(
                    f"{test.test_id} - {test.title}",
                    [
                        ("Type", _title_case(test.test_type.value if test.test_type else None)),
                        ("Priority", _title_case(_enum_value(test.priority))),
                    ],
                    body_label="Description",
                    body_text=test.description,
                )
                if test.expected_result:
                    pdf.set_font("Helvetica", "B", 8.5)
                    pdf.set_text_color(*MUTED_COLOR)
                    pdf.cell(pw, 4.5, "Expected Result", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*TEXT_COLOR)
                    pdf.multi_cell(pw, 5, _sanitize(test.expected_result), new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(2)

        # --- 16. Implementation Plan ------------------------------------------
        pdf.section_heading(16, "Implementation Plan")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        elif not analysis.implementation_tasks:
            pdf.body_paragraph(None, empty="No implementation plan was suggested.")
        else:
            for index, task in enumerate(analysis.implementation_tasks, start=1):
                fields_row = [
                    ("Component", task.component or "Unspecified"),
                    ("Priority", _title_case(_enum_value(task.priority))),
                    ("Estimated Effort", task.estimated_effort or "Insufficient information."),
                ]
                pdf.item_card(f"Step {index}: {task.task}", fields_row, body_label="Description", body_text=task.description)
                if task.dependencies:
                    pdf.set_font("Helvetica", "B", 8.5)
                    pdf.set_text_color(*MUTED_COLOR)
                    pdf.cell(pw, 4.5, "Depends On", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*TEXT_COLOR)
                    pdf.multi_cell(pw, 5, _sanitize(task.dependencies), new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(2)

        # --- 17. Approval Status (Module 20) -----------------------------------
        pdf.section_heading(17, "Approval Status")
        _render_approvals_section(pdf, pw, context.approvals)

        # --- 18. Change History (Module 20) ------------------------------------
        pdf.section_heading(18, "Change History")
        _render_version_history_section(pdf, pw, context.versions, report_version, cr_version)

        # --- 19. Audit (Module 20) ----------------------------------------------
        pdf.section_heading(19, "Audit")
        _render_audit_section(pdf, pw, context.history_events)

        # --- 20. Recommendation ---------------------------------------
        pdf.section_heading(20, "Recommendation")
        if analysis is None:
            pdf.body_paragraph(None, empty=no_analysis_note)
        else:
            pdf.label_value("Recommendation", _title_case(_enum_value(analysis.recommendation)))
            pdf.ln(1)
            pdf.body_paragraph(analysis.recommendation_reasoning, empty="No recommendation reasoning was provided.")

        raw = pdf.output()
        # fpdf2's output() has returned a plain str (classic PyFPDF, needing
        # a latin-1 encode) in some versions and a bytearray in others -
        # handle both rather than assuming one.
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return raw.encode("latin-1")
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any PDF-
        # building failure should surface as a clean, catchable error
        # rather than an unhandled 500 with a raw fpdf2 traceback.
        raise ReportGenerationError(f"Could not build the PDF report: {exc}") from exc


def _risk_bucket_label(risk_score: Optional[float]) -> str:
    """Same low/medium/high/critical cutoffs the rest of the app already
    uses (see app/api/dashboard.py / app/services/analytics.py) - kept as
    its own tiny copy here rather than a cross-import, matching this
    project's established api/ vs services/ duplication convention."""
    if risk_score is None:
        return "Not Analyzed"
    if risk_score >= 75:
        return "Critical"
    if risk_score >= 50:
        return "High"
    if risk_score >= 25:
        return "Medium"
    return "Low"


def _render_approvals_section(pdf: _ReportPDF, pw: float, approvals: list[Approval]) -> None:
    """Spec section 4: required/completed/pending/rejected counts, plus a
    full table with timestamps and approver comments. Approver identity is
    shown by name only - never an email address or other account detail,
    matching the same "don't expose unnecessary sensitive information"
    rule Module 19's Approval Bottlenecks section already follows."""
    if not approvals:
        pdf.body_paragraph(None, empty="No approvals have been requested for this change request.")
        return

    completed_statuses = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED}
    total = len(approvals)
    completed = sum(1 for a in approvals if a.status in completed_statuses)
    pending = sum(1 for a in approvals if a.status == ApprovalStatus.PENDING)
    rejected = sum(1 for a in approvals if a.status == ApprovalStatus.REJECTED)
    approved = sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED)
    changes_requested = sum(1 for a in approvals if a.status == ApprovalStatus.CHANGES_REQUESTED)

    pdf.label_value("Required Approvals", str(total))
    pdf.label_value("Completed", f"{completed} ({approved} approved, {rejected} rejected, {changes_requested} changes requested)")
    pdf.label_value("Pending", str(pending))
    pdf.ln(2)

    rows = []
    for approval in approvals:
        approver_name = approval.approver.name if approval.approver else "Unknown"
        type_label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
        status_label = APPROVAL_STATUS_LABELS.get(approval.status, approval.status.value)
        rows.append(
            [
                type_label,
                approver_name,
                status_label,
                _fmt_datetime(approval.requested_at),
                _fmt_datetime(approval.responded_at) if approval.responded_at else "-",
                approval.comment or "-",
            ]
        )
    pdf.table(
        [
            ("Type", 0.14),
            ("Approver", 0.16),
            ("Status", 0.14),
            ("Requested", 0.18),
            ("Responded", 0.18),
            ("Comment", 0.20),
        ],
        rows,
    )


def _render_version_history_section(
    pdf: _ReportPDF, pw: float, versions: list[ChangeRequestVersion], report_version: int, current_version: int
) -> None:
    """Spec section 5: version/date/changed-by/summary, current version
    clearly marked. `report_version` (not just `current_version`) is also
    flagged, since on a historical report those two can differ."""
    if not versions:
        pdf.body_paragraph(None, empty="No version history recorded.")
        return

    rows = []
    for version_row in versions:
        tags = []
        if version_row.version_number == current_version:
            tags.append("CURRENT")
        if version_row.version_number == report_version and report_version != current_version:
            tags.append("THIS REPORT")
        version_label = f"Version {version_row.version_number}" + (f" ({', '.join(tags)})" if tags else "")
        changed_by_name = version_row.changed_by_user.name if version_row.changed_by_user else "Unknown"
        rows.append(
            [
                version_label,
                _fmt_date(version_row.created_at),
                changed_by_name,
                version_row.change_summary,
            ]
        )
    pdf.table(
        [
            ("Version", 0.18),
            ("Date", 0.16),
            ("Changed By", 0.18),
            ("Summary", 0.48),
        ],
        rows,
    )


# History actions rendered on the report's Audit section, with a short
# human-readable label - deliberately a curated subset of HistoryAction
# covering spec section 6's own list (created / edited / status changes /
# approval decisions / analysis / implementation) rather than every single
# action type this app tracks internally (e.g. MENTIONED, REMINDER_SENT
# are operational noise for a CAB-facing PDF, not workflow milestones).
_AUDIT_ACTION_LABELS: dict[HistoryAction, str] = {
    HistoryAction.CREATED: "Change request created",
    HistoryAction.FIELD_CHANGED: "Field edited",
    HistoryAction.VERSION_CREATED: "New version created",
    HistoryAction.STATUS_CHANGED: "Status changed",
    HistoryAction.ASSIGNED: "Person assigned",
    HistoryAction.UNASSIGNED: "Person unassigned",
    HistoryAction.APPROVAL_REQUESTED: "Approval requested",
    HistoryAction.APPROVED: "Approved",
    HistoryAction.REJECTED: "Rejected",
    HistoryAction.CHANGES_REQUESTED: "Changes requested",
    HistoryAction.APPROVAL_INVALIDATED: "Approval invalidated by later edit",
    HistoryAction.APPROVAL_CANCELLED: "Approval request cancelled",
    HistoryAction.AI_ANALYSIS_COMPLETED: "AI analysis completed",
    HistoryAction.AI_ANALYSIS_INVALIDATED: "AI analysis marked outdated",
    HistoryAction.REPORT_GENERATED: "Report generated",
}


def _render_audit_section(pdf: _ReportPDF, pw: float, history_events: list[ChangeRequestHistory]) -> None:
    """Spec section 6: created / edited / status changes / approval
    decisions / analysis / implementation. Filtered to the curated
    milestone list above - not every internal event type - and actor
    identity is shown by name only (never an email), same rule as the
    Approval Status section above."""
    relevant = [h for h in history_events if h.action in _AUDIT_ACTION_LABELS]
    if not relevant:
        pdf.body_paragraph(None, empty="No audit events recorded.")
        return

    rows = []
    for event in relevant:
        actor = event.user.name if event.user else (event.actor_label or "System")
        label = _AUDIT_ACTION_LABELS.get(event.action, _title_case(event.action.value))
        detail_bits = []
        if event.field_name:
            detail_bits.append(FIELD_LABELS.get(event.field_name, event.field_name.replace("_", " ").title()))
        if event.new_value:
            detail_bits.append(event.new_value if len(event.new_value) < 120 else event.new_value[:117] + "...")
        detail = " - ".join(detail_bits) if detail_bits else "-"
        rows.append([label, actor, _fmt_datetime(event.created_at), detail])
    pdf.table(
        [
            ("Event", 0.20),
            ("By", 0.16),
            ("When", 0.20),
            ("Detail", 0.44),
        ],
        rows,
    )
