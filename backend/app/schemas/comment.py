"""Pydantic schemas for ChangeRequestComment (Module 12 Phase 5)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class CommentCreate(BaseModel):
    body: str
    # One level of replies only (spec: "reply where practical" - a flat
    # two-level thread, not a full nested tree) - the API layer checks this
    # points at a top-level comment (parent_id is itself None) on the same
    # change request.
    parent_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def body_length(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 1:
            raise ValueError("Comment can't be empty.")
        if len(value) > 4000:
            raise ValueError("Comment must be 4000 characters or fewer.")
        return value


class CommentResolve(BaseModel):
    resolved: bool


class CommentRead(BaseModel):
    """Built manually by the API layer (not from_attributes) - user_name
    comes from the related User row, and mentioned_user_ids is recomputed
    fresh from `body` at read time (mentions aren't stored structurally,
    see app/models/comment.py), same "compute, don't store" pattern as
    is_analysis_outdated / is_approval_outdated elsewhere in Module 12."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    change_request_id: int
    user_id: int
    user_name: str
    parent_id: Optional[int] = None
    body: str
    resolved: bool
    created_at: datetime
    mentioned_user_ids: List[int] = []
