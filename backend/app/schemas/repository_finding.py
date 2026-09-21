"""Module 15 Phase 3 (Repository Intelligence - CR -> File Matching).

`AffectedFileMatch`/`RepositoryMatchResult` are what the AI's raw JSON
response gets parsed and validated against (mirrors
app/schemas/ai_analysis.py's own pattern exactly) - a response that
doesn't match this shape fails validation loudly instead of persisting
something invented. `RepositoryFindingRead` is the read schema for an
already-persisted finding.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import FileMatchLabel, ImpactLevel

_NULLISH = {"none", "n a", "na", "not provided", "null", "", "not specified", "unknown", "tbd"}


def _normalize_impact(value):
    """Same "no answer given" placeholder handling as
    app/schemas/ai_analysis.py::_normalize, kept local rather than
    cross-imported (each schema file in this app is self-contained) -
    just enough of it for the one enum field this schema actually has."""
    if isinstance(value, str):
        cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned in _NULLISH:
            return None
        return cleaned
    return value


def _safe_confidence(value, default: float = 50.0):
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in _NULLISH:
            return default
        try:
            return float(cleaned)
        except ValueError:
            return default
    return value


class AffectedFileMatch(BaseModel):
    # Must exactly match one of the candidate file_path values the AI was
    # given - app/services/repository_matcher.py drops (never persists)
    # any match whose file_path isn't actually one of those candidates,
    # so a hallucinated path here is simply discarded, never invented
    # into a real finding.
    file_path: str
    impact_level: ImpactLevel = ImpactLevel.LOW
    confidence: float = Field(50.0, ge=0, le=100)
    reason: str = ""
    evidence: str = ""

    @field_validator("impact_level", mode="before")
    @classmethod
    def normalize_impact(cls, value):
        return _normalize_impact(value) or "low"

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_confidence(value, default=50.0)


class RepositoryMatchResult(BaseModel):
    matches: list[AffectedFileMatch] = []


class RepositoryFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_request_id: int
    change_request_version: int
    analysis_id: int
    repository_scan_id: int
    repository_scan_number: int
    indexed_file_id: int
    file_path: str
    language: str | None = None
    impact_level: ImpactLevel
    confidence: float
    match_label: FileMatchLabel
    reason: str
    evidence: str
    created_at: datetime
    # Module 15 Phase 4 (version awareness) - computed fresh on every
    # request by the API layer (app/services/workflow_rules.py::
    # repository_finding_outdated_reasons), never stored on the row
    # itself: this finding's own change_request_version/analysis_id/
    # repository_scan_id above never change once written, only whether
    # they still match "the latest" of each does. Defaults below only
    # matter if a caller builds this schema without setting them.
    is_outdated: bool = False
    outdated_reasons: list[str] = []
