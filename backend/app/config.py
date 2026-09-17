"""ChatSQL configuration — env-driven, zero-boilerplate."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 配置文件查找路径。
#
# 坑：pydantic-settings 的 env_file 是**相对于进程 CWD** 解析的。
# .env 放在仓库根，但服务几乎总是从 `backend/` 目录启动
# （uvicorn 需要能 import app），于是 .env 永远读不到，
# 所有配置静默回落到默认值 —— LLM provider 变回 openai、api_key 变空，
# 表现为「明明配了 key 却 401」。
#
# 这里显式给出两个候选：先 CWD，再仓库根（后者优先覆盖）。
# backend/app/config.py → parents[0]=app, [1]=backend, [2]=仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = [".env", str(_REPO_ROOT / ".env")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
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
