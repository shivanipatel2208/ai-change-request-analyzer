"""Pydantic schemas for Approval (Module 12 Phase 4).

Mirrors the shape of app/schemas/assignment.py: reads are built manually by
the API layer (not from_attributes) since approver/requester names come
from the related User rows, not directly off the Approval row itself.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import ApprovalStatus, ApprovalType


class ApprovalRequestCreate(BaseModel):
    """POST /{id}/approvals body - tag a real person for a specific kind of
    sign-off. `comment` here is an optional note from the requester (e.g.
    "please double check the OTP rate limiting") - stored on the audit
    trail, not on the Approval row itself (that `comment` column is the
    approver's own response - see app/models/approval.py)."""

    approval_type: ApprovalType
    approver_user_id: int
    comment: Optional[str] = None
    # Module 18 Phase 1: entirely optional - "please respond by ..." - see
    # app/models/approval.py's own docstring for why this is never required
    # or defaulted to anything.
    due_date: Optional[datetime] = None

    @field_validator("comment")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ApprovalRespond(BaseModel):
    """POST /{id}/approvals/{approval_id}/respond body - only the tagged
    approver may call this (see app/api/change_requests.py::respond_to_approval).
    `status` must be one of Approved/Rejected/Changes Requested - never
    Pending or Cancelled (validated in the endpoint against
    workflow_rules.APPROVAL_RESPONSE_STATUSES so the 422 message can name
    exactly what went wrong)."""

    status: ApprovalStatus
    comment: Optional[str] = None

    @field_validator("comment")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_request_id: int
    approval_type: ApprovalType
    approval_type_label: str
    status: ApprovalStatus
    status_label: str
    approver_id: int
    approver_name: str
    approver_email: str
    requested_by: int
    requested_by_name: str
    requested_at: datetime
    responded_at: Optional[datetime] = None
    comment: Optional[str] = None
    cr_version: int
    # Module 18 Phase 1 - see this model's own docstring for why this is
    # optional and never a required/defaulted value.
    due_date: Optional[datetime] = None
    # Computed fresh at read time from due_date (app/services/approvals.py
    # ::approval_due_status) - "overdue" / "due_soon" / None. Never stored,
    # never meaningful once the approval has actually been decided.
    due_status: Optional[str] = None
    # True only for a still-PENDING approval whose cr_version has fallen
    # behind the CR's current_version (the CR was edited since this
    # approval was requested) - a decision already recorded is a historical
    # fact and never reported as outdated, no matter how the CR changes
    # after it. See app/services/approvals.py::is_approval_outdated.
    is_outdated: bool = False
    # Module 13 Phase 4: what the AI itself recommended on the analysis
    # this approval was requested against (approval.cr_version) - None if
    # no analysis exists for that version. Purely informational context,
    # never a constraint on the approver's decision.
    ai_recommendation: Optional[str] = None
    # True only once this approval has actually been decided (Approved /
    # Rejected / Changes Requested) AND that decision didn't match
    # ai_recommendation above - see
    # app/services/workflow_rules.py::overrides_ai_recommendation. Always
    # False while still Pending or Cancelled; never implies the decision
    # was wrong, only that it diverged from the AI's own suggestion.
    overrode_ai_recommendation: bool = False


class RecommendedApprovalType(BaseModel):
    """One entry in GET /{id}/approvals/recommended - an AI-derived
    suggestion only (spec's "AI recommends, humans decide" - see
    app/services/workflow_rules.py::required_approval_types). Never creates
    an Approval row by itself.

    is_outdated (Module 22): true when this recommendation was computed
    from an analysis that no longer matches the change request's current
    version (app/services/workflow_rules.py::is_analysis_outdated) - the
    same check the main CR detail view already surfaces its own "this
    analysis may be outdated" banner from (Module 13). Before this field
    existed, this endpoint had no way to say so at all: editing a CR after
    analyzing it left recommended_approvals silently suggesting approvals
    off stale data, with none of the "may be outdated" signal the rest of
    the app already gives elsewhere. Repeated on every item (rather than
    a separate top-level flag) so existing callers that treat this
    endpoint's response as a plain list of items keep working unchanged."""

    approval_type: ApprovalType
    label: str
    is_outdated: bool = False
