"""Shared FastAPI dependencies for the API layer."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.enums import Capability
from app.models.user import User
from app.services.permissions import has_permission
from app.services.workflow_rules import is_active_user, is_admin

# auto_error=False so a missing token gives us our own consistent 401
# response below, instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired, please log in again"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

    user_id = payload.get("sub")
    user = db.get(User, int(user_id)) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    # Module 21: a deactivated account's existing token stops working on
    # its very next request - same "logged out" experience as an expired
    # token (app/context/AuthContext.jsx already treats any /auth/me
    # failure as "log this session out"), rather than only blocking future
    # logins.
    if not is_active_user(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deactivated. Contact an administrator.",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Module 21: gate for every /api/admin/* endpoint. is_active_user is
    already enforced by get_current_user above, so this only adds the
    role check on top."""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required for this action."
        )
    return current_user


def check_capability(db: Session, user: User, capability: Capability) -> None:
    """Module 21 spec section 3: "backend must enforce permissions." Raises
    403 if `user`'s role doesn't have `capability` per the permissions
    matrix (app/services/permissions.py). Called directly inside an
    endpoint body (matching this file's existing can_edit_change_request-
    style inline checks) rather than as a Depends() - several call sites
    need this to run after the request body is parsed (e.g. responding to
    an approval is Capability.APPROVAL or Capability.REJECTION depending
    on the status in the payload), so every call site uses the same
    pattern rather than mixing two styles."""
    if not has_permission(db, user, capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your role doesn't have permission to do this ({capability.value.replace('_', ' ')}).",
        )
