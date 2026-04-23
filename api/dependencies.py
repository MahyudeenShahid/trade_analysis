"""API dependencies for authentication and validation."""

from typing import Optional
from fastapi import Header, HTTPException, WebSocket

from auth.security import decode_access_token
from config.settings import API_KEY, AUTH_ALLOW_LEGACY_API_KEY


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not str(authorization).startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _is_legacy_api_key(token: Optional[str]) -> bool:
    if not token:
        return False
    return bool(AUTH_ALLOW_LEGACY_API_KEY and token == API_KEY)


def _is_valid_access_token(token: Optional[str]) -> bool:
    if not token:
        return False
    claims = decode_access_token(token)
    return bool(claims and claims.get("sub"))


def _extract_websocket_token(websocket: WebSocket) -> Optional[str]:
    # Browser websocket clients cannot set Authorization header reliably,
    # so we allow query-string tokens too.
    token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    if token:
        return str(token).strip() or None
    auth_header = websocket.headers.get("authorization")
    return _extract_bearer(auth_header)


def require_api_key(authorization: Optional[str] = Header(None)):
    """
    Dependency for protecting endpoints with API key authentication.
    
    Expects: Authorization: Bearer <key>
    
    Args:
        authorization: Authorization header value
        
    Returns:
        bool: True if authenticated
        
    Raises:
        HTTPException: 401 if missing/invalid header, 403 if invalid key
    """
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header"
        )

    if _is_valid_access_token(token):
        return True

    if _is_legacy_api_key(token):
        return True

    # If it is neither a valid JWT nor an allowed legacy key, deny.
    if AUTH_ALLOW_LEGACY_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    raise HTTPException(status_code=403, detail="Invalid or expired access token")


def require_ws_auth(websocket: WebSocket) -> bool:
    """Validate websocket token from query params or Authorization header."""
    token = _extract_websocket_token(websocket)
    if not token:
        return False
    return _is_valid_access_token(token) or _is_legacy_api_key(token)


__all__ = ["require_api_key", "require_ws_auth"]
