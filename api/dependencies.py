"""API dependencies for authentication and validation."""

from typing import Optional
from fastapi import Header, HTTPException
from config.settings import API_KEY


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
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header"
        )
    key = authorization.split(" ", 1)[1].strip()
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


__all__ = ["require_api_key"]
