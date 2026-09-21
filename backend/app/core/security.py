"""Password hashing and JWT helpers.

Password hashing uses PBKDF2-HMAC-SHA256 from Python's standard library
`hashlib` - not bcrypt/argon2. This is a deliberate choice for this
project: earlier modules hit real build failures on this machine because
some packages (pydantic-core) needed to compile native code for a very new
Python version, and bcrypt has the same class of risk (it ships prebuilt
wheels, but not always for the newest Python on day one). PBKDF2 avoids
that entirely - it's pure Python/stdlib, and it's a legitimate, widely used
algorithm (it was Django's own default for years) at a strong iteration
count.

Tokens are JWTs (HS256) via PyJWT, which is pure Python with no compiled
dependency either - same reasoning.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 260_000  # OWASP-recommended minimum (2023+) for PBKDF2-SHA256


def hash_password(password: str) -> str:
    """Returns a self-contained hash string: "pbkdf2_sha256$<iterations>$<salt>$<hash>" (hex)."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time comparison - never short-circuits on the first differing byte."""
    try:
        algorithm, iterations, salt, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            _PBKDF2_ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(derived.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def create_access_token(*, user_id: int, email: str, expires_minutes: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError on failure - callers handle these."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
