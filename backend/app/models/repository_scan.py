"""RepositoryScan model - Module 15 Phase 1 (Repository Intelligence).

Records one pass of indexing a local repository/folder. Deliberately NOT
tied to a specific ChangeRequest - a scan indexes "the repository" in
general, the same way `git log` isn't scoped to any one change. Module 15
Phase 3 ties a *specific change request's* affected-file findings back to
one of these scans (plus the CR's own version and its analysis's version),
so the version-awareness the rest of the app relies on ("never present a
finding as current once something it depended on has moved on") applies
here too, without this table itself needing to know about change requests
at all.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import RepositoryScanStatus, sa_enum


class RepositoryScan(Base):
    __tablename__ = "repository_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Absolute path on disk that was scanned - kept as a string (not
    # resolved again at read time) so a scan's own record stays accurate
    # even if the app's configured REPOSITORY_ROOT changes later.
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # The Nth scan of this exact root_path, 1-based - lets the UI/API say
    # "Scan #3" instead of only an opaque database id, and gives Phase 3's
    # "repository scan version" its actual meaning.
    scan_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RepositoryScanStatus] = mapped_column(
        sa_enum(RepositoryScanStatus, "repository_scan_status"), nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triggered_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    files: Mapped[List["IndexedFile"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="IndexedFile.file_path"
    )

    def __repr__(self) -> str:
        return f"<RepositoryScan id={self.id} root_path={self.root_path!r} scan_number={self.scan_number}>"
