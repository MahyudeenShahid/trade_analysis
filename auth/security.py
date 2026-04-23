"""Security primitives for password hashing and JWT token handling."""

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from config.settings import AUTH_ALGORITHM, AUTH_SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: Optional[str] = None, iterations: int = 260000) -> str:
    """Hash password with PBKDF2-SHA256."""
    if password is None:
        raise ValueError("password is required")
    if salt is None:
        salt_bytes = os.urandom(16)
        salt = base64.urlsafe_b64encode(salt_bytes).decode("ascii").rstrip("=")
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    digest = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify plain password against PBKDF2-SHA256 hash."""
    try:
        algo, iter_s, salt, digest = str(password_hash).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        expected = hash_password(password, salt=salt, iterations=iterations)
        return hmac.compare_digest(expected, password_hash)
    except Exception:
        return False


def create_access_token(subject: str, username: str, role: str = "admin", expires_minutes: Optional[int] = None) -> str:
    """Create signed JWT access token."""
    now = _utc_now()
    ttl = int(expires_minutes if expires_minutes is not None else ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + timedelta(minutes=max(ttl, 1))
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "username": str(username),
        "role": str(role),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        if payload.get("type") != "access":
            return None
        if not payload.get("sub"):
            return None
        return payload
    except Exception:
        return None
