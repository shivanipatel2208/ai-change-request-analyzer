"""Pydantic schemas for ImplementationTask."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import AssignmentRole, Priority


class ImplementationTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    task: str
    description: str
    component: str
    priority: Priority
    estimated_effort: str
    dependencies: Optional[str] = None
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: see AffectedComponentRead.related_files for the full rule.
    related_files: List[str] = []

    # --- Module 17 Phase 1 (Test Cases & Implementation Plan 2.0) -------
    # Nullable: rows from before this module ran have no suggestion
    # recorded. A suggestion only, never an actual assignment - see
    # models/implementation_task.py's own docstring.
    owner_suggestion: Optional[AssignmentRole] = None

    # Module 17 Phase 4 - which Requirement(s) this task actually
    # implements, computed the same keyword-overlap way related_files
    # above already is (never AI-generated - see TestCaseRead's own
    # docstring for why). Empty when nothing overlaps meaningfully.
    requirement_references: List[str] = []

    # Module 17 Phase 5 - see TestCaseRead's own docstring for both fields.
    analysis_version: Optional[int] = None
    is_outdated: bool = False

    # Module 17 Phase 6 (human editing) - see TestCaseRead's own docstring.
    edited_by: Optional[int] = None
    edited_at: Optional[datetime] = None
    edit_reason: Optional[str] = None


class ImplementationTaskUpdate(BaseModel):
    """PATCH /{change_request_id}/implementation-tasks/{task_id} body -
    see TestCaseUpdate's own docstring for the same "every field optional,
    reason optional, AI's prior wording preserved on the history row"
    reasoning, applied here to ImplementationTask instead."""

    task: Optional[str] = None
    description: Optional[str] = None
    component: Optional[str] = None
    priority: Optional[Priority] = None
    estimated_effort: Optional[str] = None
    dependencies: Optional[str] = None
    # A human may set this to any real AssignmentRole (or explicitly clear
    # it back to null) - unlike the AI, which can only ever suggest one via
    # ImplementationTaskItem's own normalizer, a human reviewer isn't
    # restricted to "clearly calls for it" - see workflow_rules.
    # can_review_analysis_findings for the permission gate itself.
    owner_suggestion: Optional[AssignmentRole] = None
    reason: Optional[str] = None

    @field_validator("task", "description", "component", "estimated_effort")
    @classmethod
    def _required_not_blank(cls, value: Optional[str]) -> Optional[str]:
        # task/description/component/estimated_effort are NOT NULL columns -
        # unlike dependencies/reason below, blanking one out here is a
        # rejected edit, not a legitimate "clear this field."
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field can't be blank.")
        return value

    @field_validator("dependencies", "reason")
    @classmethod
    def _optional_blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None
