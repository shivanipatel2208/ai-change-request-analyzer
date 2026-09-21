"""RepositoryFinding model - Module 15 Phase 3 (Repository Intelligence -
CR -> File Matching).

One row per (change request, source file) pair the matcher decided is
plausibly affected. Deliberately carries its own change_request_version,
analysis_id, and repository_scan_id rather than only pointing at "the
change request" - this is what makes a finding version-aware from day
one: it's tied to the *exact* CR version, AI analysis, and repository
scan it was generated against, so Phase 4 can compute whether any of
those three have since moved on without this table needing to change at
all (the same "tied to a CR + its version, never presented as current
once the CR has moved on" rule the POST-MODULE-12 architecture lock
requires of every future module).

A brand-new table, so every column here is NOT NULL from day one - same
reasoning as ImpactAssessment/SecurityFinding before it.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import FileMatchLabel, ImpactLevel, sa_enum


class RepositoryFinding(Base):
    __tablename__ = "repository_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), nullable=False)
    # The CR's own current_version at the moment this finding was
    # generated - NOT a live/computed value, so it stays exactly what it
    # was even after the CR is edited again later (see Phase 4).
    change_request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    repository_scan_id: Mapped[int] = mapped_column(ForeignKey("repository_scans.id"), nullable=False)
    indexed_file_id: Mapped[int] = mapped_column(ForeignKey("indexed_files.id"), nullable=False)
    impact_level: Mapped[ImpactLevel] = mapped_column(
        sa_enum(ImpactLevel, "repository_finding_impact_level"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    # Computed server-side from `confidence` (FileMatchLabel.from_confidence)
    # - see that classmethod's own docstring for why this is never trusted
    # from the AI's raw response.
    match_label: Mapped[FileMatchLabel] = mapped_column(
        sa_enum(FileMatchLabel, "repository_finding_match_label"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    change_request: Mapped["ChangeRequest"] = relationship()
    analysis: Mapped["Analysis"] = relationship()
    repository_scan: Mapped["RepositoryScan"] = relationship()
    indexed_file: Mapped["IndexedFile"] = relationship()

    # --- Read-only convenience for the API layer -------------------------
    # RepositoryFindingRead (app/schemas/repository_finding.py) reads these
    # straight off the ORM object via from_attributes - avoids either a
    # manual join in every endpoint or duplicating file_path/language onto
    # this table (which would just be a second, driftable copy of what
    # IndexedFile already owns).
    @property
    def file_path(self) -> str:
        return self.indexed_file.file_path

    @property
    def language(self) -> Optional[str]:
        return self.indexed_file.language

    @property
    def repository_scan_number(self) -> int:
        return self.repository_scan.scan_number

    def __repr__(self) -> str:
        return (
            f"<RepositoryFinding id={self.id} change_request_id={self.change_request_id} "
            f"indexed_file_id={self.indexed_file_id} match_label={self.match_label}>"
        )
