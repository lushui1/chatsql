"""Session domain — ID generation, mode validation."""

from __future__ import annotations

import secrets
from typing import Literal

VALID_MODES = {"fast", "think"}


def generate_session_id() -> str:
    return f"sess_{secrets.token_hex(16)}"


def validate_mode(mode: str | None) -> str:
    if mode is None:
        raise ValueError("mode must be fast or think")
    mode = mode.lower().strip()
    if mode not in VALID_MODES:
        raise ValueError("mode must be fast or think")
    return mode
