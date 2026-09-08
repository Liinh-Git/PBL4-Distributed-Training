"""Management Backend — FastAPI application factory.

Canonical responsibility:
- Creates and configures the FastAPI application instance for Management Backend.
- Registers API routers, middleware, and dependency providers.

Important boundary:
- Hosts management REST API and WebSocket routes; does not host DTP/1 training endpoints.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: initialize DB pool + runtime gateway on startup, clean up on shutdown."""
    from management_backend.config import get_settings
    from management_backend import db
    from management_backend.gateways.runtime_gateway import init_gateway

    settings = get_settings()

    # Initialize DB pool (skip if DATABASE_URL not configured)
    if settings.database_url:
        try:
            db.init_pool(settings.database_url)
        except Exception as exc:
            logger.error("Failed to initialize database pool: %s", exc)
            # Don't raise — allow the server to start so /health can report degraded state
    else:
        logger.warning("DATABASE_URL not configured; database pool not initialized.")

    # Initialize runtime gateway stub
    init_gateway(
        host=settings.runtime_host if settings.runtime_management_port else None,
        port=settings.runtime_management_port,
    )

    # Run DB schema bootstrap if BOOTSTRAP_DB env var is set
    if os.getenv("BOOTSTRAP_DB", "").lower() in ("1", "true", "yes"):
        _run_schema_bootstrap(settings.database_url)

    logger.info("Management Backend started on %s:%d", settings.backend_host, settings.backend_port)
    yield

    # Shutdown
    db.close_pool()
    logger.info("Management Backend shutdown complete.")


def _run_schema_bootstrap(database_url: str | None) -> None:
    """Apply the initial SQL schema if it hasn't been applied yet."""
    if not database_url:
        return
    import pathlib
    sql_path = pathlib.Path(__file__).parent / "migrations" / "0001_initial_schema.sql"
    if not sql_path.exists():
        logger.warning("Schema bootstrap file not found: %s", sql_path)
        return
    try:
        import psycopg
        with psycopg.connect(database_url) as conn:
            conn.autocommit = True
            conn.execute(sql_path.read_text(encoding="utf-8"))
        logger.info("Database schema bootstrap completed.")
    except Exception as exc:
        logger.error("Schema bootstrap failed: %s", exc)


def create_app() -> FastAPI:
    """Create and configure the Management Backend FastAPI application."""
    from management_backend.config import get_settings
    settings = get_settings()

    # Configure root logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = FastAPI(
        title="PBL4 Distributed Training Management Backend",
        description=(
            "Management control-plane REST API and WebSocket for the "
            "Distributed Deep Learning system."
        ),
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Global error handlers
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        msg = str(exc)
        if "pool" in msg.lower() or "not initialized" in msg.lower():
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "DATABASE_UNAVAILABLE", "message": msg}},
            )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": msg}},
        )

    # CORS — allow origins from settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Register Routers ─────────────────────────────────────────────────────
    from management_backend.api.system import router as system_router
    from management_backend.api.runtime import router as runtime_router
    from management_backend.api.datasets import router as datasets_router
    from management_backend.api.jobs import router as jobs_router
    from management_backend.api.attempts import router as attempts_router
    from management_backend.api.checkpoints import router as checkpoints_router
    from management_backend.api.events import router as events_router
    from management_backend.api.commands import router as commands_router

    app.include_router(system_router)
    app.include_router(runtime_router)
    app.include_router(datasets_router)
    app.include_router(jobs_router)
    app.include_router(attempts_router)
    app.include_router(checkpoints_router)
    app.include_router(events_router)
    app.include_router(commands_router)

    # ─── WebSocket routes ─────────────────────────────────────────────────────
    from management_backend.websocket import register_websocket_routes
    register_websocket_routes(app)

    return app
