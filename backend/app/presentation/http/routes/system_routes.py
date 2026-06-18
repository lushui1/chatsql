"""System routes — health, admin, runtime config."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.application.llm import PROVIDER_DEFAULTS
from app.presentation.http.security.auth_utils import verify_admin_key

router = APIRouter()
_settings = get_settings()

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "config.json"

# Runtime LLM overrides (survives within process lifetime)
_llm_overrides: dict = {}


def _load_config():
    """Load persisted LLM config from disk on startup."""
    global _llm_overrides
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            _llm_overrides = data.get("llm", {})
            # Apply to settings
            for field in ["provider", "api_key", "base_url", "model", "think_model", "temperature", "max_tokens"]:
                key = f"llm_{field}" if field != "provider" else "llm_provider"
                if field in _llm_overrides and hasattr(_settings, key):
                    setattr(_settings, key, _llm_overrides[field])
        except Exception:
            pass


def _save_config():
    """Persist LLM config to disk."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Read existing (may contain other sections)
    existing = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["llm"] = {
        "provider": _settings.llm_provider,
        "api_key": _settings.llm_api_key,
        "base_url": _settings.llm_base_url,
        "model": _settings.llm_model,
        "think_model": _settings.llm_think_model,
        "temperature": _settings.llm_temperature,
        "max_tokens": _settings.llm_max_tokens,
    }
    CONFIG_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


# Load on module import
_load_config()


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


@router.get("/v1/config/llm")
async def get_llm_config():
    """Return current LLM configuration (api_key masked for security)."""
    masked_key = ""
    if _settings.llm_api_key:
        key = _settings.llm_api_key
        if len(key) <= 8:
            masked_key = "*" * len(key)
        else:
            masked_key = key[:4] + "****" + key[-4:]

    from app.application.llm import get_provider_base_url
    effective_base_url = get_provider_base_url(_settings.llm_provider, _settings.llm_base_url)

    return JSONResponse(content={
        "provider": _llm_overrides.get("provider", _settings.llm_provider),
        "model": _llm_overrides.get("model", _settings.llm_model),
        "think_model": _llm_overrides.get("think_model", _settings.llm_think_model),
        "base_url": effective_base_url,
        "api_key_masked": masked_key,
        "temperature": _llm_overrides.get("temperature", _settings.llm_temperature),
        "max_tokens": _llm_overrides.get("max_tokens", _settings.llm_max_tokens),
        "available_providers": list(PROVIDER_DEFAULTS.keys()),
        "provider_models": PROVIDER_DEFAULTS.get(
            _llm_overrides.get("provider", _settings.llm_provider), {}
        ).get("models", []),
    })


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    think_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@router.post("/v1/config/llm")
async def update_llm_config(req: LLMConfigUpdate):
    """Update LLM configuration at runtime (in-memory, persists until restart)."""
    for field, value in req.model_dump(exclude_none=True).items():
        _llm_overrides[field] = value
    # Also update the settings object so ResponsesService picks it up
    if req.provider:
        _settings.llm_provider = req.provider
    if req.api_key is not None:
        _settings.llm_api_key = req.api_key
    if req.base_url is not None:
        _settings.llm_base_url = req.base_url
    if req.model:
        _settings.llm_model = req.model
    if req.think_model:
        _settings.llm_think_model = req.think_model
    if req.temperature is not None:
        _settings.llm_temperature = req.temperature
    if req.max_tokens is not None:
        _settings.llm_max_tokens = req.max_tokens
    _save_config()
    return JSONResponse(content={"ok": True, "message": "LLM配置已更新"})
