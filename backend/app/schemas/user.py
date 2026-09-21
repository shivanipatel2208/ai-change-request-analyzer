"""Pydantic schemas for User."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import UserRole


class UserBase(BaseModel):
    name: str
    email: str
    role: UserRole = UserRole.ENGINEER


class UserCreate(UserBase):
    # Plaintext password - hashing happens in the auth module, which
    # doesn't exist yet. Nothing calls this schema yet; it just defines the
    # shape for that later module to build against.
    password: str


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    # Module 21: NULL (every account predating this column) reads as
    # active - same convention as ChangeRequestRead.current_version's own
    # "value or default" validator just below it in that file.
    is_active: bool = True

    @field_validator("is_active", mode="before")
    @classmethod
    def _default_active(cls, value):
        return True if value is None else value
