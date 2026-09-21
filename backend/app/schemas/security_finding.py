"""Pydantic schemas for SecurityFinding."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import SecurityCategory, SecurityFindingStatus, Severity


class SecurityFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    category: SecurityCategory
    finding: str
    severity: Severity
    evidence: str
    recommendation: str
    status: SecurityFindingStatus
    # Module 14 Phase 6 (human review) - all nullable: no human has
    # touched `status` yet until these are set.
    review_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None


class SecurityFindingStatusUpdate(BaseModel):
    """PATCH /{id}/security-findings/{finding_id}/status body - see
    app/api/change_requests.py::update_security_finding_status. Any of the
    4 status values may be set here (unlike the AI, which is restricted to
    open/not_applicable - see SecurityFindingItem.normalize_status) - a
    human reviewer has full authority to move a finding forward
    (Acknowledged/Resolved) or back (e.g. reopening a Resolved finding)."""

    status: SecurityFindingStatus
    comment: Optional[str] = None

    @field_validator("comment")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None
