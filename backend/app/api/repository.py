"""Module 15 Phase 1 (Repository Intelligence): trigger and inspect scans
of the configured local repository/folder.

Not scoped to any one change request - a scan indexes "the repository" in
general (see app/models/repository_scan.py's docstring for why). Any
authenticated user can trigger or view a scan for now, the same way
GET /api/users is a read-only directory open to anyone logged in - nothing
here exposes anything about a specific change request yet. Per-CR
permission checks arrive in Phase 3, once a scan's findings are actually
tied to one.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.repository_scan import RepositoryScan
from app.models.user import User
from app.schemas.repository_scan import RepositoryScanDetail, RepositoryScanRead
from app.services.repository_scanner import RepositoryScanError, scan_repository

router = APIRouter(prefix="/api/repository", tags=["repository"])

_SCAN_RELATIONSHIPS = (selectinload(RepositoryScan.files),)


@router.post("/scan", response_model=RepositoryScanRead, status_code=status.HTTP_201_CREATED)
def trigger_scan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RepositoryScan:
    """Scans the app's configured repository root and records the result
    as a new RepositoryScan. Never touches or deletes any prior scan - a
    failed or stale scan just sits there as history, exactly like a failed
    AI re-analysis leaves the previous good analysis untouched."""
    try:
        return scan_repository(db, triggered_by=current_user.id)
    except RepositoryScanError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[RepositoryScanRead])
def list_scans(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RepositoryScan]:
    """Every scan ever run, newest first - a lightweight history list (no
    file listing), same shape as GET /api/change-requests/{id}/analyses."""
    return db.query(RepositoryScan).order_by(RepositoryScan.started_at.desc()).all()


@router.get("/latest", response_model=RepositoryScanDetail)
def get_latest_scan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RepositoryScan:
    scan = (
        db.query(RepositoryScan)
        .options(*_SCAN_RELATIONSHIPS)
        .order_by(RepositoryScan.started_at.desc())
        .first()
    )
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No repository scan has been run yet.")
    return scan


@router.get("/{scan_id}", response_model=RepositoryScanDetail)
def get_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RepositoryScan:
    scan = (
        db.query(RepositoryScan)
        .options(*_SCAN_RELATIONSHIPS)
        .filter(RepositoryScan.id == scan_id)
        .first()
    )
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository scan not found.")
    return scan
