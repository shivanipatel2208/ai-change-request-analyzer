"""Pydantic read schemas for RepositoryScan/IndexedFile - Module 15
Phases 1-2 (Repository Intelligence)."""
import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import RepositoryScanStatus


def _parse_json_list(value):
    """imports/functions/classes/api_routes/database_references/
    config_references are each stored as a JSON-encoded string column
    (Module 15 Phase 2) - same pattern as ChangeRequest.tags
    (app/schemas/change_request.py::_parse_tags), turned back into a real
    list here so the API always returns [] instead of null for a file
    with no findings of that kind."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return []


class IndexedFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    language: Optional[str] = None
    size_bytes: int
    line_count: int
    imports: List[str] = []
    functions: List[str] = []
    classes: List[str] = []
    api_routes: List[str] = []
    database_references: List[str] = []
    config_references: List[str] = []

    @field_validator(
        "imports", "functions", "classes", "api_routes", "database_references", "config_references",
        mode="before",
    )
    @classmethod
    def _lists_from_json(cls, value):
        return _parse_json_list(value)


class RepositoryScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    root_path: str
    scan_number: int
    status: RepositoryScanStatus
    error_message: Optional[str] = None
    file_count: int
    skipped_count: int
    triggered_by: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class RepositoryScanDetail(RepositoryScanRead):
    files: List[IndexedFileRead] = []
