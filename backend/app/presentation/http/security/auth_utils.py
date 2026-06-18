"""HTTP presentation — routes, auth."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from app.config import get_settings

_settings = get_settings()


async def verify_api_key(
    authorization: str | None = Header(None),
) -> str:
    """Verify Bearer token if API key is configured."""
    if not _settings.api_key:
        return "anonymous"
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")
    token = authorization[7:]
    if token != _settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


async def verify_admin_key(
    authorization: str | None = Header(None),
) -> str:
    """Verify admin key for admin endpoints."""
    if not _settings.admin_key:
        return "admin"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin credentials")
    token = authorization[7:]
    if token != _settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return token


def get_session_mode(x_smartbot_mode: str | None = Header(None)) -> str | None:
    """Extract session mode from X-SmartBot-Mode header."""
    if x_smartbot_mode is None:
        return None
    mode = x_smartbot_mode.lower().strip()
    if mode not in ("fast", "think"):
        raise HTTPException(status_code=400, detail="mode must be fast or think")
    return mode


def get_session_id(x_session_id: str | None = Header(None)) -> str | None:
    """Extract session ID from X-Session-Id header."""
    if x_session_id is None:
        return None
    if not x_session_id.startswith("sess_") or len(x_session_id) != 37:
        raise HTTPException(status_code=400, detail="Invalid X-Session-Id format")
    return x_session_id
