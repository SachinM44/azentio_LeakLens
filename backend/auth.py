"""API-key authentication: every endpoint except /health requires `X-API-Key`."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from backend.settings import get_settings


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key"),
                    x_analyst: str = Header(default="", alias="X-Analyst")) -> str:
    """FastAPI dependency; returns the actor written to the audit log: the X-Analyst name when sent, else the
    API-key actor."""
    settings = get_settings()
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.leaklens_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing X-API-Key")
    analyst = x_analyst.strip()[:80]
    return analyst or settings.api_actor
