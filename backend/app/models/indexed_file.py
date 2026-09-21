"""IndexedFile model - Module 15 Phase 1 (Repository Intelligence).

One row per source file a RepositoryScan kept (everything ignored -
node_modules/.git/build/binaries/secrets/oversized files/etc - is simply
never written here at all, not stored-then-hidden). Phase 1 only records
what's knowable just from walking the filesystem: the path, a guessed
language, and basic size/line stats. Phase 2 (code understanding) adds the
deeper extraction - imports/functions/classes/API routes/database and
config references - as new nullable columns on this same table, same
reasoning as every other phased column addition in this app: by the time
Phase 2 ships, this table already has real rows from Phase 1 testing, so
init_db's plain `ALTER TABLE ADD COLUMN` (no DEFAULT) would otherwise leave
them NULL despite a NOT NULL claim.
"""
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class IndexedFile(Base):
    __tablename__ = "indexed_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("repository_scans.id"), nullable=False)
    # Relative to the scan's root_path, forward-slash separated regardless
    # of OS (see repository_scanner.py's use of PurePosixPath) - so a path
    # recorded on Windows reads/matches identically on any other machine.
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # A best-effort guess from the file extension (e.g. "python",
    # "javascript") - None for a recognized-but-unmapped extension. Not an
    # enum: the set of languages a real repository can contain is open-
    # ended, and this is derived deterministically from the extension
    # rather than something the app filters/branches logic on.
    language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Module 15 Phase 2 (Code Understanding) -------------------------
    # Each of these is a JSON-encoded list of strings (same "one text
    # column, not a new table" pattern already used for
    # ChangeRequest.tags/Analysis.security_analysis) - see
    # app/services/code_understanding.py for what actually populates them
    # and app/schemas/repository_scan.py for how they're read back out as
    # real lists. All nullable: an ALTER-added column on a table that
    # already has real rows from Phase 1 testing (same reasoning as every
    # other phased column addition in this app), and also simply absent
    # for a file type Phase 2 doesn't attempt to understand (e.g.
    # markdown, CSS) rather than ever being invented.
    imports: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    functions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_routes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    database_references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    scan: Mapped["RepositoryScan"] = relationship(back_populates="files")

    def __repr__(self) -> str:
        return f"<IndexedFile id={self.id} file_path={self.file_path!r}>"
