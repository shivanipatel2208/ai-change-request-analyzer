"""Pydantic schemas for ChangeRequestAssignment (Module 12 Phase 3)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AssignmentRole


class AssignmentCreate(BaseModel):
    user_id: int
    role: AssignmentRole


class ChangeRequestAssignmentRead(BaseModel):
    """Built manually by the API layer (not from_attributes) since
    user_name/user_email/assigned_by_name come from the related User rows,
    not directly off the ChangeRequestAssignment row itself."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str
    user_email: str
    role: AssignmentRole
    role_label: str
    assigned_by: int
    assigned_by_name: str
    assigned_at: datetime
