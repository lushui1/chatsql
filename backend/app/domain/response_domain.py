"""Response domain — build response resource, generate IDs."""

from __future__ import annotations

import secrets
import time
from typing import Any

from app.schemas import ResponseResource, Usage


def generate_response_id() -> str:
    return f"resp_{secrets.token_hex(16)}"


def build_response_resource(
    *,
    response_id: str | None = None,
    model: str = "",
    output: list[dict] | None = None,
    status: str = "completed",
    usage: dict | None = None,
    error: dict | None = None,
    created_at: int | None = None,
) -> ResponseResource:
    return ResponseResource(
        id=response_id or generate_response_id(),
        created_at=created_at or int(time.time()),
        status=status,
        model=model,
        output=output or [],
        usage=Usage(**(usage or {})),
        error=error,
    )
