"""ChatSQL configuration — env-driven, zero-boilerplate."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATSQL_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──
    app_name: str = "ChatSQL"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # ── LLM Provider ──
    llm_provider: Literal[
        "openai", "anthropic", "google", "dashscope",
        "zhipu", "moonshot", "deepseek", "ollama", "custom",
    ] = "openai"
    llm_api_key: str = ""
    llm_base_url: str = ""  # empty = use provider default
    llm_model: str = "gpt-4o-mini"  # fast mode
    llm_think_model: str = "gpt-4o"  # think mode
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096

    # ── Database (sessions/feedback) ──
    database_url: str = "sqlite+aiosqlite:///./data/chatsql.db"

    # ── DataSource (OLAP) ──
    datasource_type: Literal["duckdb", "mysql", "postgresql", "clickhouse"] = "duckdb"
    datasource_url: str = ""  # empty = embedded duckdb with demo data
    datasource_schema: str = "main"

    # ── Security ──
    api_key: str = ""  # empty = no auth (dev mode)
    admin_key: str = ""  # empty = no admin auth

    # ── Streaming ──
    stream_buffer_size: int = 200  # max SSE events buffered per active stream


@lru_cache
def get_settings() -> Settings:
    return Settings()
