"""Pydantic schema for Notification (Module 12 Phase 5)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: NotificationType
    title: str
    message: str
    change_request_id: Optional[int] = None
    # Module 18 Phase 1 - see app/models/notification.py's own docstring.
    approval_id: Optional[int] = None
    is_read: bool
    created_at: datetime
