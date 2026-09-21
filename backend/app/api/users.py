"""A simple, read-only user directory (Module 12 Phase 3) - lets the
frontend populate the "assign a team member" picker on a change request.
No admin user-management here (invite/edit/deactivate) - out of scope for
this hackathon.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import UserRead

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    return db.query(User).order_by(User.name).all()
