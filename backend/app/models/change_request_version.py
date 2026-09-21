"""ChangeRequestVersion model (Module 12) - a snapshot taken every time a
change request's editable fields are meaningfully modified.

Version 1 is created the moment a CR is created (or, for CRs that already
existed before this module, backfilled by init_db.py as "Initial version
imported"). Every subsequent save that changes at least one editable field
creates Version 2, 3, 4, ... - never overwrites a previous one, so the
Compare Versions view (GET /api/change-requests/{id}/compare) always has
two real snapshots to diff.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ChangeRequestVersion(Base):
    __tablename__ = "change_request_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    # Short human-readable summary, e.g. "Priority changed from Medium to
    # High" or "Initial version imported."
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON object of the CR's editable fields as of this version - what
    # Compare Versions actually diffs. Not a full relational history; a
    # flat field-name -> value dict is enough per the spec ("a clean
    # field-by-field comparison is sufficient").
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="versions")
    changed_by_user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<ChangeRequestVersion cr={self.change_request_id} v={self.version_number}>"
