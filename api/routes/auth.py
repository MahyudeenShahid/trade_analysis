"""Authentication routes for login and session validation."""

from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import require_api_key
from auth.security import create_access_token, decode_access_token, hash_password, verify_password
from config.settings import AUTH_ADMIN_PASSWORD, AUTH_ADMIN_USERNAME, ACCESS_TOKEN_EXPIRE_MINUTES
from db.auth_queries import ensure_default_admin, get_user_by_username

router = APIRouter(prefix="/auth", tags=["auth"])

# Basic in-memory login throttling by client IP
_FAILED_LOGIN: Dict[str, Dict[str, object]] = {}
_MAX_ATTEMPTS = 5
_LOCK_MINUTES = 5


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_username(value: str) -> str:
    return str(value or "").strip().lower()


def _assert_not_locked(ip: str):
    rec = _FAILED_LOGIN.get(ip)
    if not rec:
        return
    locked_until = rec.get("locked_until")
    if isinstance(locked_until, datetime) and locked_until > _utc_now():
        remaining = int((locked_until - _utc_now()).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {max(remaining, 1)} seconds.",
        )


def _record_failure(ip: str):
    now = _utc_now()
    rec = _FAILED_LOGIN.get(ip, {"count": 0, "locked_until": None})
    rec["count"] = int(rec.get("count", 0)) + 1
    if rec["count"] >= _MAX_ATTEMPTS:
        rec["locked_until"] = now + timedelta(minutes=_LOCK_MINUTES)
        rec["count"] = 0
    _FAILED_LOGIN[ip] = rec


def _clear_failures(ip: str):
    if ip in _FAILED_LOGIN:
        _FAILED_LOGIN.pop(ip, None)


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    """Authenticate with username/password and return a JWT access token."""
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    _assert_not_locked(client_ip)

    username = _normalize_username(payload.username)
    password = payload.password

    user = get_user_by_username(username)
    if not user:
        _record_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not bool(user.get("is_active", 1)):
        raise HTTPException(status_code=403, detail="User account is disabled")

    if not verify_password(password, str(user.get("password_hash") or "")):
        _record_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    _clear_failures(client_ip)
    token = create_access_token(
        subject=str(user.get("id")),
        username=str(user.get("username")),
        role=str(user.get("role") or "admin"),
        expires_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "role": user.get("role") or "admin",
        },
    }


@router.get("/me")
def me(
    authorization: str = Header(None),
    _auth: bool = Depends(require_api_key),
):
    """Return details about the currently authenticated principal."""
    token = None
    if authorization and str(authorization).startswith("Bearer "):
        token = str(authorization).split(" ", 1)[1].strip()

     claims = decode_access_token(token)
     if not claims:
        # Legacy API-key auth has no user claims; expose a synthetic service user.
        return {
            "id": "legacy-api-key",
            "username": "legacy_api_key",
            "role": "admin",
        }
     return {
         "id": claims.get("sub"),
         "username": claims.get("username"),
         "role": claims.get("role") or "admin",
     }


def bootstrap_default_auth_user() -> None:
    """Create default admin user when auth table is empty."""
    username = _normalize_username(AUTH_ADMIN_USERNAME)
    password_hash = hash_password(AUTH_ADMIN_PASSWORD)
    ensure_default_admin(username=username, password_hash=password_hash)


__all__ = ["router", "bootstrap_default_auth_user"]
