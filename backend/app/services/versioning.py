"""Module 12: turns a CR edit into "what changed, field by field" plus a
new version - the alternative to the forbidden "Change Request updated."
apply_change_request_update() is the one place that:

  1. diffs the incoming payload against the CR's current values (using
     workflow_rules.normalize_field_value so an enum-vs-string or
     date-vs-isoformat mismatch never looks like a false change)
  2. applies only the fields that actually changed
  3. if anything changed: bumps current_version, writes a
     ChangeRequestVersion snapshot, and writes one FIELD_CHANGED history
     event per changed field via app.services.history (never a single
     vague "updated" event)
  4. returns the list of changes made - the API response uses this for
     the "here's what changed" confirmation the edit form shows.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_version import ChangeRequestVersion
from app.models.enums import ApprovalStatus, HistoryAction, NotificationType
from app.models.user import User
from app.services import history
from app.services import notify as notify_service
from app.services.workflow_rules import (
    APPROVAL_TYPE_LABELS,
    EDITABLE_FIELDS,
    FIELD_LABELS,
    build_snapshot,
    normalize_field_value,
)


@dataclass
class FieldChange:
    field: str
    label: str
    old_value: Optional[str]
    new_value: Optional[str]


def _display(value: Any, field: Optional[str] = None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else None
    if field == "priority" and isinstance(value, str):
        return value.replace("_", " ").title()
    return str(value)


def diff_change_request(change_request: ChangeRequest, payload: dict[str, Any]) -> list[FieldChange]:
    """payload is {field_name: new_value} for whichever editable fields the
    client sent (partial-update semantics - a field absent from payload is
    left untouched, so this only reports/applies fields actually present)."""
    changes: list[FieldChange] = []
    for field in EDITABLE_FIELDS:
        if field not in payload:
            continue
        old_norm = normalize_field_value(field, getattr(change_request, field))
        new_norm = normalize_field_value(field, payload[field])
        old_norm = old_norm if old_norm not in (None, "", []) else None
        new_norm = new_norm if new_norm not in (None, "", []) else None
        if old_norm == new_norm:
            continue
        changes.append(
            FieldChange(
                field=field,
                label=FIELD_LABELS[field],
                old_value=_display(old_norm, field),
                new_value=_display(new_norm, field),
            )
        )
    return changes


def _apply_field(change_request: ChangeRequest, field: str, raw_value: Any) -> None:
    if field == "tags":
        setattr(change_request, field, _json.dumps(raw_value) if raw_value else None)
    else:
        setattr(change_request, field, raw_value)


def apply_change_request_update(
    db: Session,
    change_request: ChangeRequest,
    payload: dict[str, Any],
    *,
    user: User,
) -> list[FieldChange]:
    """Applies payload to change_request. If (and only if) something
    actually changed: bumps current_version, records the version snapshot,
    and records field-level history. Returns the changes made (empty if
    the save was a no-op)."""
    changes = diff_change_request(change_request, payload)
    if not changes:
        return changes

    changed_fields = {c.field for c in changes}
    for field in changed_fields:
        _apply_field(change_request, field, payload[field])

    new_version = (change_request.current_version or 1) + 1
    change_request.current_version = new_version
    db.flush()  # so build_snapshot() below sees the fields just set above

    if len(changes) == 1:
        only = changes[0]
        if only.old_value and only.new_value:
            summary = f"{only.label} changed from {only.old_value} to {only.new_value}"
        elif only.new_value:
            summary = f"{only.label} set to {only.new_value}"
        else:
            summary = f"{only.label} cleared"
    else:
        summary = ", ".join(c.label for c in changes) + " updated"

    db.add(
        ChangeRequestVersion(
            change_request_id=change_request.id,
            version_number=new_version,
            changed_by=user.id,
            change_summary=summary,
            snapshot=build_snapshot(change_request),
        )
    )
    history.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.VERSION_CREATED,
        user_id=user.id,
        new_value=f"Version {new_version}",
        version_number=new_version,
    )
    for change in changes:
        history.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.FIELD_CHANGED,
            user_id=user.id,
            field_name=change.field,
            old_value=change.old_value,
            new_value=change.new_value,
            version_number=new_version,
        )

    # Module 12 section 6: editing a CR that already has an analysis makes
    # that analysis outdated - record it on the timeline rather than
    # silently leaving the old analysis looking current (the "is this
    # outdated" banner itself is computed fresh at read time by
    # workflow_rules.is_analysis_outdated; this is just the audit trail
    # entry marking the moment it happened).
    latest_analysis = (
        db.query(Analysis)
        .filter(Analysis.change_request_id == change_request.id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if latest_analysis is not None and (latest_analysis.change_request_version or 1) != new_version:
        history.record_event(
            db,
            change_request_id=change_request.id,
            action=HistoryAction.AI_ANALYSIS_INVALIDATED,
            actor_label="System",
            new_value=f"Analysis from version {latest_analysis.change_request_version or 1} is now outdated",
            version_number=new_version,
        )
        interested_ids = {change_request.created_by} | {a.user_id for a in change_request.assignments}
        interested_ids.discard(user.id)
        for user_id in interested_ids:
            notify_service.notify(
                db,
                user_id=user_id,
                type=NotificationType.ANALYSIS_OUTDATED,
                title=f"CR-{change_request.id}'s AI analysis is outdated",
                message=f"{user.name} edited \"{change_request.title}\" - its last AI analysis no longer reflects the current version.",
                change_request_id=change_request.id,
            )

    # Module 12 Phase 4: the same idea, applied to any approval still
    # awaiting a response - it was requested against an earlier version of
    # this CR, and this edit just moved the CR past it (see
    # app/services/approvals.py::is_approval_outdated, computed fresh at
    # read time; this is just the audit trail entry for the moment it
    # happened). An approval that's already been responded to is a
    # historical fact and is never touched here.
    pending_approvals = (
        db.query(Approval)
        .filter(Approval.change_request_id == change_request.id, Approval.status == ApprovalStatus.PENDING)
        .all()
    )
    for approval in pending_approvals:
        if (approval.cr_version or 1) != new_version:
            type_label = APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
            history.record_event(
                db,
                change_request_id=change_request.id,
                action=HistoryAction.APPROVAL_INVALIDATED,
                actor_label="System",
                new_value=f"{type_label} approval from version {approval.cr_version or 1} is now outdated",
                version_number=new_version,
            )
            if approval.approver_id != user.id:
                notify_service.notify(
                    db,
                    user_id=approval.approver_id,
                    type=NotificationType.REAPPROVAL_REQUIRED,
                    title=f"{type_label} approval on CR-{change_request.id} may need a re-check",
                    message=f"{user.name} edited \"{change_request.title}\" after your {type_label} "
                    f"approval was requested - it may be worth a fresh look.",
                    change_request_id=change_request.id,
                )

    return changes


@dataclass
class FieldComparison:
    field: str
    label: str
    old_value: Optional[str]
    new_value: Optional[str]
    status: str  # "unchanged" | "added" | "removed" | "changed"


def compare_snapshots(snapshot_a: str, snapshot_b: str) -> list[FieldComparison]:
    """Field-by-field diff between two ChangeRequestVersion snapshots, in
    EDITABLE_FIELDS order - what Compare Versions renders. "A clean
    field-by-field comparison is sufficient" (spec section 5) - this isn't
    trying to be a pixel-perfect text diff."""
    data_a: dict[str, Any] = _json.loads(snapshot_a) if snapshot_a else {}
    data_b: dict[str, Any] = _json.loads(snapshot_b) if snapshot_b else {}

    results: list[FieldComparison] = []
    for field in EDITABLE_FIELDS:
        old_norm = normalize_field_value(field, data_a.get(field))
        new_norm = normalize_field_value(field, data_b.get(field))
        old_norm = old_norm if old_norm not in (None, "", []) else None
        new_norm = new_norm if new_norm not in (None, "", []) else None

        if old_norm == new_norm:
            status = "unchanged"
        elif old_norm is None:
            status = "added"
        elif new_norm is None:
            status = "removed"
        else:
            status = "changed"

        results.append(
            FieldComparison(
                field=field,
                label=FIELD_LABELS[field],
                old_value=_display(old_norm, field),
                new_value=_display(new_norm, field),
                status=status,
            )
        )
    return results
