"""FastAPI app factory — wires all routes, middleware, startup/shutdown."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.infrastructure import init_db
from app.presentation.http.routes import responses_routes, sessions_routes, system_routes

logger = logging.getLogger("chatsql")
_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB. Shutdown: cleanup."""
    logger.info("ChatSQL starting up...")
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("ChatSQL shutting down...")


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
