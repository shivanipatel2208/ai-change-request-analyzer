"""Pydantic schemas for Requirement."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import Certainty, Priority, RequirementType, ReviewStatus


class RequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    requirement_type: RequirementType
    description: str
    priority: Priority
    # Module 13 (AI Analysis 2.0) - all nullable: rows from before this
    # module ran have no epistemic status recorded.
    certainty: Optional[Certainty] = None
    confidence: Optional[float] = None
    evidence: Optional[str] = None
    # Module 14 Phase 6 (human review) - None means "no human has reviewed
    # this yet"; never set by the AI, never overwrites certainty/confidence/
    # evidence above.
    review_status: Optional[ReviewStatus] = None
    review_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None


class RequirementReviewUpdate(BaseModel):
    """PATCH /{id}/requirements/{requirement_id}/review body - see
    app/api/change_requests.py::review_requirement. A comment is required
    when marking Needs Clarification (validated in the endpoint, same
    pattern as ApprovalRespond's required-comment-for-negative-outcomes
    rule), optional for Confirmed."""

    review_status: ReviewStatus
    comment: Optional[str] = None

    @field_validator("comment")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None
