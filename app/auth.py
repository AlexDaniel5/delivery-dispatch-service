"""API-key authentication for write endpoints.

Authentication is opt-in: if no keys are configured (``DISPATCH_API_KEYS`` is
empty) every request is allowed, which keeps local development and the default
test setup friction-free. When keys are configured, write endpoints require a
matching ``X-API-Key`` header.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing a valid ``X-API-Key`` when auth is enabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        return
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    if x_api_key not in settings.api_key_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid API key",
        )
