"""Authentication endpoints: register, login, current-user, logout."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.workflow_rules import is_active_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: User, remember_me: bool = False) -> TokenResponse:
    settings = get_settings()
    expires_minutes = (
        settings.remember_me_token_expire_minutes if remember_me else settings.access_token_expire_minutes
    )
    token = create_access_token(user_id=user.id, email=user.email, expires_minutes=expires_minutes)
    return TokenResponse(
        access_token=token,
        expires_in=expires_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists."
        )

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.ENGINEER,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Module 22: closes a narrow race - two registrations for the same
        # email arriving close enough together can both pass the .first()
        # check above before either commits. Without this, the second
        # commit would raise an uncaught IntegrityError (the unique
        # constraint on User.email) straight through to a generic 500
        # instead of the same clean 409 the normal duplicate-email path
        # already returns just above.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists."
        )
    db.refresh(user)

    # Auto-login on register - a fresh account can go straight in rather
    # than bouncing the user to a separate login step.
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        # Deliberately the same error for "no such user" and "wrong password" -
        # don't leak which one it was.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    # Module 21: only reachable once the password has already been
    # verified correct - so this never leaks "this email exists but is
    # deactivated" to someone who doesn't already know the password.
    if not is_active_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact an administrator.",
        )

    return _issue_token(user, remember_me=payload.remember_me)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    """A protected endpoint - requires a valid Authorization: Bearer <token> header."""
    return UserRead.model_validate(current_user)


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)) -> dict:
    # Tokens are stateless JWTs, so there's nothing to invalidate server-side
    # without a token blocklist (deliberately not added - extra
    # infrastructure this project doesn't need yet). The frontend discards
    # its stored token immediately after calling this; this endpoint mainly
    # exists so "logout" is a real authenticated action, not just a
    # frontend-only concept.
    return {"message": "Logged out. Discard the access token client-side."}
