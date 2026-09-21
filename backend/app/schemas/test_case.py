"""Pydantic schemas for TestCase."""
import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import Priority, TestType


def _parse_steps(value):
    """steps is stored as a JSON-encoded list[str] column (see
    models/test_case.py's own docstring for why) - turn it back into a
    real list here, the same pattern ChangeRequest.tags already uses."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    test_id: str
    title: str
    test_type: TestType
    priority: Priority
    description: str
    expected_result: str
    # Module 15 Phase 5 (Repository Intelligence - Integration) - computed
    # fresh by the API layer (app/services/repository_linkage.py), never
    # stored: see AffectedComponentRead.related_files for the full rule.
    related_files: List[str] = []

    # --- Module 17 Phase 1 (Test Cases & Implementation Plan 2.0) -------
    # All nullable/empty-default: rows from before this module ran simply
    # have none of this recorded.
    preconditions: Optional[str] = None
    steps: List[str] = []

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_from_json(cls, value):
        return _parse_steps(value)

    # Module 17 Phase 4 - which Requirement(s)/Risk(s) this test case
    # actually verifies, computed fresh by the API layer the same
    # keyword-overlap way related_files above already is (never AI-
    # generated - see services/traceability_linkage.py's own docstring for
    # why asking the AI to cite not-yet-existing IDs would be a
    # hallucination risk). Empty when nothing overlaps meaningfully.
    requirement_references: List[str] = []
    risk_references: List[str] = []

    # Module 17 Phase 5 - which analysis version this test case belongs to,
    # and whether that analysis (and therefore this test case) is stale -
    # both populated by the API layer from the parent Analysis, the same
    # "computed fresh, never stored" rule KnowledgeEvidenceRead.is_outdated
    # already follows (one staleness axis: has the CR been edited since).
    analysis_version: Optional[int] = None
    is_outdated: bool = False

    # Module 17 Phase 6 (human editing) - None means "the AI's original
    # content, never touched by a human" - same pattern as
    # Requirement.reviewed_by/SecurityFinding.reviewed_by.
    edited_by: Optional[int] = None
    edited_at: Optional[datetime] = None
    edit_reason: Optional[str] = None


class TestCaseUpdate(BaseModel):
    """PATCH /{change_request_id}/test-cases/{test_case_id} body - Module 17
    Phase 6 (human editing). Every field is optional - only ones actually
    present in the request are changed (see the endpoint's own
    model_dump(exclude_unset=True) call), so correcting one field never
    requires resending the whole test case. `reason` is optional context
    for the audit trail, not required the way a Requirement's "Needs
    Clarification" comment is (see RequirementReviewUpdate) - editing an
    AI-generated test case isn't a rejection that demands justification.
    The AI's own prior wording is never lost - it's preserved as the
    old_value on this edit's own TEST_CASE_EDITED history row (see
    app/api/change_requests.py::update_test_case), never a second column
    on this row itself."""

    title: Optional[str] = None
    description: Optional[str] = None
    test_type: Optional[TestType] = None
    priority: Optional[Priority] = None
    preconditions: Optional[str] = None
    steps: Optional[List[str]] = None
    expected_result: Optional[str] = None
    reason: Optional[str] = None

    @field_validator("title", "description", "expected_result")
    @classmethod
    def _required_not_blank(cls, value: Optional[str]) -> Optional[str]:
        # title/description/expected_result are NOT NULL columns - unlike
        # preconditions/reason below, blanking one out here is a rejected
        # edit, not a legitimate "clear this field."
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field can't be blank.")
        return value

    @field_validator("preconditions", "reason")
    @classmethod
    def _optional_blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("steps")
    @classmethod
    def _clean_steps(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        return [str(item).strip() for item in value if str(item).strip()]
