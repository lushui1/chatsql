"""System routes — health, admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.presentation.http.security.auth_utils import verify_admin_key

router = APIRouter()
_settings = get_settings()


@router.get("/healthz")
async def healthz():
    return {"ok": True, "service": "chatsql"}


@router.get("/readyz")
async def readyz():
    return {"ok": True, "service": "chatsql", "version": "0.1.0"}


@router.get("/admin/provider")
async def get_provider(_admin: str = Depends(verify_admin_key)):
    return JSONResponse(content={
        "provider": _settings.llm_provider,
        "model": _settings.llm_model,
        "think_model": _settings.llm_think_model,
        "datasource": _settings.datasource_type,
    })
