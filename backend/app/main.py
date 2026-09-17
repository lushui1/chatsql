"""FastAPI app factory — wires all routes, middleware, startup/shutdown."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.infrastructure import init_db
from app.presentation.http.routes import responses_routes, sessions_routes, system_routes, learn_routes, datasource_routes, context_routes, dashboard_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("chatsql")
_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB. Shutdown: cleanup."""
    logger.info("ChatSQL starting up...")
    _log_llm_config()
    await init_db()
    from app.infrastructure.persistence.context_store import init_context_db
    await init_context_db()
    logger.info("Database initialized")
    yield
    logger.info("ChatSQL shutting down...")


def _log_llm_config() -> None:
    """启动时打印 LLM 配置摘要（脱敏）。

    存在的理由：配置静默回落是这类项目最难查的故障。.env 没读到时
    provider 会退回 openai、api_key 变空，表现为「明明配了 key 却 401」，
    不看日志完全看不出是配置没加载。
    """
    s = get_settings()
    key = s.llm_api_key
    masked = f"{key[:6]}...{key[-4:]} (len={len(key)})" if key else "** 未配置 **"
    logger.info(
        "LLM config: provider=%s base_url=%s model=%s think_model=%s key=%s",
        s.llm_provider, s.llm_base_url or "(default)", s.llm_model,
        s.llm_think_model, masked,
    )
    if not key:
        logger.warning("llm_api_key 为空 —— 请在仓库根目录的 .env 中配置 CHATSQL_LLM_API_KEY")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ChatSQL",
        description="Open-source ChatBI framework — chat with your database",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — permissive for dev, tighten for production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Session-Id",
            "X-Session-Mode",
            "X-Response-Id",
            "Content-Type",
        ],
    )

    # Routes
    app.include_router(system_routes.router, tags=["system"])
    app.include_router(responses_routes.router, tags=["responses"])
    app.include_router(sessions_routes.router, tags=["sessions"])
    app.include_router(learn_routes.router, tags=["learn"])
    app.include_router(datasource_routes.router, tags=["datasources"])
    app.include_router(context_routes.router, tags=["context"])
    app.include_router(dashboard_routes.router, tags=["dashboards"])


    # Root
    @app.get("/")
    async def root():
        return {
            "name": "ChatSQL",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/healthz",
        }

    return app


app = create_app()
