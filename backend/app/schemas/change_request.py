"""Pydantic schemas for ChangeRequest."""
import json
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import ApprovalRecommendation, ChangeRequestStatus, ComplexityLevel, Priority


def _parse_tags(value):
    """tags is stored as a JSON-encoded string column; every schema that
    reads it from the ORM needs to turn that back into a real list."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class ChangeRequestBase(BaseModel):
    title: str
    description: str
    business_objective: Optional[str] = None
    priority: Priority = Priority.MEDIUM
    requested_by: Optional[str] = None
    target_system: Optional[str] = None
    desired_deadline: Optional[date] = None
    # --- Module 12 (Enterprise Workflow) additional CR fields -----------
    business_impact: Optional[str] = None
    technical_impact: Optional[str] = None
    customer_impact: Optional[str] = None
    environment: Optional[str] = None
    dependencies_note: Optional[str] = None
    compliance_requirements: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_from_json(cls, value):
        return _parse_tags(value)


class ChangeRequestCreate(BaseModel):
    """What the "New Change Request" form submits. created_by/status are NOT
    accepted from the client - created_by comes from the authenticated user
    and status is always set server-side to PENDING_ANALYSIS."""

    title: str
    description: str
    business_objective: Optional[str] = None
    priority: Priority = Priority.MEDIUM
    requested_by: str
    target_system: str
    desired_deadline: Optional[date] = None
    business_impact: Optional[str] = None
    technical_impact: Optional[str] = None
    customer_impact: Optional[str] = None
    environment: Optional[str] = None
    dependencies_note: Optional[str] = None
    compliance_requirements: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("title")
    @classmethod
    def title_length(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Title must be at least 5 characters.")
        if len(value) > 255:
            raise ValueError("Title must be 255 characters or fewer.")
        return value

    @field_validator("description")
    @classmethod
    def description_length(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError(
                "Description must be at least 20 characters - describe the change in enough detail to be useful."
            )
        if len(value) > 4000:
            raise ValueError("Description must be 4000 characters or fewer.")
        return value

    @field_validator("business_objective")
    @classmethod
    def business_objective_normalize(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("requested_by")
    @classmethod
    def requested_by_required(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Requested By is required.")
        if len(value) > 255:
            raise ValueError("Requested By must be 255 characters or fewer.")
        return value

    @field_validator("target_system")
    @classmethod
    def target_system_required(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Target System is required.")
        if len(value) > 255:
            raise ValueError("Target System must be 255 characters or fewer.")
        return value

    @field_validator("desired_deadline")
    @classmethod
    def deadline_not_in_past(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value < date.today():
            raise ValueError("Desired deadline can't be in the past.")
        return value


# --- Module 12: editing -----------------------------------------------
#
# Every field is Optional with no default spelled out as "unset" - the API
# layer reads payload.model_dump(exclude_unset=True) so a field the client
# never included in the request body is left completely untouched (true
# partial-update / PATCH-like semantics on a PUT route), while a field
# explicitly sent as null clears it. Reuses ChangeRequestCreate's own
# validators where the same rule applies (title/description length, etc),
# but every validator here is skipped when the field is simply absent -
# only ChangeRequestCreate enforces "required at creation time".


class ChangeRequestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    business_objective: Optional[str] = None
    priority: Optional[Priority] = None
    requested_by: Optional[str] = None
    target_system: Optional[str] = None
    desired_deadline: Optional[date] = None
    business_impact: Optional[str] = None
    technical_impact: Optional[str] = None
    customer_impact: Optional[str] = None
    environment: Optional[str] = None
    dependencies_note: Optional[str] = None
    compliance_requirements: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("title")
    @classmethod
    def title_length(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Title must be at least 5 characters.")
        if len(value) > 255:
            raise ValueError("Title must be 255 characters or fewer.")
        return value

    @field_validator("description")
    @classmethod
    def description_length(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 20:
            raise ValueError(
                "Description must be at least 20 characters - describe the change in enough detail to be useful."
            )
        if len(value) > 4000:
            raise ValueError("Description must be 4000 characters or fewer.")
        return value

    @field_validator("requested_by", "target_system")
    @classmethod
    def not_blank_if_provided(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("This field can't be blank.")
        return value


class ChangeRequestRead(ChangeRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ChangeRequestStatus
    created_by: int
    created_at: datetime
    updated_at: datetime
    current_version: int = 1

    @field_validator("current_version", mode="before")
    @classmethod
    def _default_version(cls, value):
        return value or 1


# --- Module 5: Change Request Management (list page + detail view) -------
#
# Everything below is read-only display shaping - no new AI logic, just
# presenting data that already exists (the raw `status` column, plus
# whatever the latest analysis/clarification questions already say).


class ChangeRequestListItem(BaseModel):
    """One row in the Change Requests table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    priority: Priority
    status: ChangeRequestStatus
    # A human-facing status layered on top of the raw `status` column plus
    # whether/how the request has been analyzed - see
    # app/api/change_requests.py::_effective_status(). One of: "draft",
    # "pending_analysis", "analyzing", "requires_clarification", "completed",
    # "approved". Never stored - always computed fresh from real rows.
    effective_status: str
    category: Optional[str] = None
    risk: Optional[str] = None
    complexity: Optional[str] = None
    created_at: datetime
    current_version: int = 1

    @field_validator("current_version", mode="before")
    @classmethod
    def _default_version(cls, value):
        return value or 1


class ChangeRequestListResponse(BaseModel):
    items: List[ChangeRequestListItem]
    total: int
    limit: int
    offset: int


class ClarificationQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    priority: Priority
    reason: str
    resolved: bool


class LatestAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    summary: str
    category: str
    complexity: ComplexityLevel
    risk_score: float
    confidence_score: float
    recommendation: Optional[ApprovalRecommendation] = None
    created_at: datetime
    change_request_version: int = 1
    clarification_questions: List[ClarificationQuestionRead] = []

    @field_validator("change_request_version", mode="before")
    @classmethod
    def _default_version(cls, value):
        return value or 1


class StatusTransitionOption(BaseModel):
    """One legal next step from the CR's current status - what the
    "Change Status" picker offers (Module 12 Phase 3)."""

    status: ChangeRequestStatus
    label: str
    requires_reason: bool


class ChangeRequestDetail(ChangeRequestRead):
    effective_status: str
    latest_analysis: Optional[LatestAnalysisRead] = None
    # Module 12: computed fresh every request from current_version vs
    # latest_analysis.change_request_version - never stored (see
    # app/services/workflow_rules.py::is_analysis_outdated).
    is_analysis_outdated: bool = False
    # Module 12 Phase 3: the real workflow lifecycle. `status` above is the
    # raw enum value (e.g. "in_review"); status_label is its human label,
    # and available_transitions lists exactly what this CR can legally move
    # to next - both computed fresh from app/services/workflow_rules.py, so
    # the frontend never has to duplicate the status graph.
    status_label: str = ""
    available_transitions: List[StatusTransitionOption] = []


class ChangeStatusRequest(BaseModel):
    """PUT /{id}/status body (Module 12 Phase 3)."""

    status: ChangeRequestStatus
    reason: Optional[str] = None


# --- Module 12: versions, history, compare --------------------------------


class ChangeRequestVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    changed_by: int
    created_at: datetime
    change_summary: str


class ChangeRequestVersionDetail(ChangeRequestVersionRead):
    snapshot: dict

    @field_validator("snapshot", mode="before")
    @classmethod
    def _parse_snapshot(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value


# --- Module 20: version-aware reports --------------------------------------


class ReportableVersionRead(BaseModel):
    """One row of GET /{id}/report/versions - what the "generate a report
    for an earlier version" picker on the frontend renders from. Not an
    ORM-backed model (this is a computed view combining version + analysis
    data), so no from_attributes config - the API layer builds these by
    hand."""

    version_number: int
    is_current: bool
    change_summary: str
    created_at: datetime
    has_analysis: bool


class ChangeRequestHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    actor_label: Optional[str] = None
    action: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    version_number: Optional[int] = None
    created_at: datetime

    @field_validator("action", mode="before")
    @classmethod
    def _action_value(cls, value):
        return value.value if hasattr(value, "value") else value


class FieldComparisonRead(BaseModel):
    field: str
    label: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    status: str


class VersionCompareResponse(BaseModel):
    from_version: int
    to_version: int
    fields: List[FieldComparisonRead]


class ChangeRequestUpdateResponse(BaseModel):
    """What PUT /change-requests/{id} returns: the updated CR plus a plain
    summary of what changed, so the frontend can show "here's what
    changed" without re-deriving it from the history endpoint."""

    change_request: ChangeRequestDetail
    changes: List[FieldComparisonRead]
    new_version: Optional[int] = None
