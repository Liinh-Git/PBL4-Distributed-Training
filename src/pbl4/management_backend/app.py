"""Management Backend — FastAPI application factory.

Canonical responsibility:
- Creates and configures the FastAPI application instance for Management Backend.
- Registers API routers, middleware, exception handlers, and dependency providers.

Important boundary:
- Hosts management REST API and WebSocket routes; does not host DTP/1 training endpoints.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pbl4.management_backend.services.attempt_service import (
    AttemptConflictError,
    AttemptNotFoundError,
    AttemptStateError,
    JobNotReadyError,
)
from pbl4.management_backend.services.command_service import CommandNotFoundError
from pbl4.management_backend.services.contract_resolver import ContractResolutionError
from pbl4.management_backend.services.dataset_service import (
    DatasetBuildNotFoundError,
    DatasetBuildReferenceError,
    DatasetBuildStateError,
    DatasetNotFoundError,
)
from pbl4.management_backend.services.idempotency import (
    IdempotencyConflictError,
    RequestInProgressError,
)
from pbl4.management_backend.services.job_service import (
    JobNotFoundError,
    JobStateError,
    JobValidationError,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: initialize DB pool + runtime gateway on startup, clean up on shutdown."""
    from pbl4.management_backend import db
    from pbl4.management_backend.config import get_settings
    from pbl4.management_backend.gateways.runtime_gateway import init_gateway

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

    # Initialize runtime gateway
    init_gateway(
        host=settings.runtime_host if settings.runtime_management_port else None,
        port=settings.runtime_management_port,
    )

    logger.info("Management Backend started on %s:%d", settings.backend_host, settings.backend_port)
    yield

    # Shutdown
    db.close_pool()
    logger.info("Management Backend shutdown complete.")


def _get_req_id(request: Request) -> str:
    return getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:8]}")


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    req_id = _get_req_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": req_id,
            }
        },
        headers={"X-Request-ID": req_id},
    )


def create_app() -> FastAPI:
    """Create and configure the Management Backend FastAPI application."""
    from pbl4.management_backend.config import get_settings

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

    # ─── Request ID Middleware ────────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:8]}"
        request.state.request_id = req_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    # ─── Global Error Handlers ────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            422,
            "VALIDATION_ERROR",
            "Request validation failed.",
            request,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(JobValidationError)
    async def job_validation_handler(request: Request, exc: JobValidationError) -> JSONResponse:
        return _error_response(
            422,
            "VALIDATION_ERROR",
            str(exc),
            request,
            details={"errors": exc.errors},
        )

    @app.exception_handler(ContractResolutionError)
    async def contract_resolution_handler(
        request: Request, exc: ContractResolutionError
    ) -> JSONResponse:
        return _error_response(
            422,
            "VALIDATION_ERROR",
            str(exc),
            request,
            details={"errors": exc.errors},
        )

    @app.exception_handler(JobNotFoundError)
    @app.exception_handler(AttemptNotFoundError)
    @app.exception_handler(DatasetNotFoundError)
    @app.exception_handler(DatasetBuildNotFoundError)
    @app.exception_handler(CommandNotFoundError)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(404, "NOT_FOUND", str(exc), request)

    @app.exception_handler(JobNotReadyError)
    @app.exception_handler(JobStateError)
    @app.exception_handler(AttemptStateError)
    @app.exception_handler(DatasetBuildStateError)
    async def state_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(409, "INVALID_STATE", str(exc), request)

    @app.exception_handler(AttemptConflictError)
    async def attempt_conflict_handler(
        request: Request, exc: AttemptConflictError
    ) -> JSONResponse:
        return _error_response(409, "ACTIVE_ATTEMPT_EXISTS", str(exc), request)

    @app.exception_handler(DatasetBuildReferenceError)
    async def build_reference_handler(
        request: Request, exc: DatasetBuildReferenceError
    ) -> JSONResponse:
        return _error_response(409, "DATASET_BUILD_IN_USE", str(exc), request)

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        request: Request, exc: IdempotencyConflictError
    ) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(RequestInProgressError)
    async def request_in_progress_handler(
        request: Request, exc: RequestInProgressError
    ) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            code = exc.detail["code"]
            msg = exc.detail.get("message", "HTTP error")
            details = exc.detail.get("details")
        else:
            status_map = {
                400: "BAD_REQUEST",
                401: "UNAUTHORIZED",
                403: "FORBIDDEN",
                404: "NOT_FOUND",
                409: "CONFLICT",
                422: "VALIDATION_ERROR",
                503: "SERVICE_UNAVAILABLE",
            }
            code = status_map.get(exc.status_code, "HTTP_ERROR")
            msg = str(exc.detail)
            details = None
        return _error_response(exc.status_code, code, msg, request, details)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        msg = str(exc)
        if "pool" in msg.lower() or "not initialized" in msg.lower():
            return _error_response(503, "DATABASE_UNAVAILABLE", msg, request)
        return _error_response(500, "INTERNAL_ERROR", msg, request)

    # CORS — allow origins from settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Register Routers ─────────────────────────────────────────────────────
    from pbl4.management_backend.api.attempts import router as attempts_router
    from pbl4.management_backend.api.checkpoints import router as checkpoints_router
    from pbl4.management_backend.api.commands import router as commands_router
    from pbl4.management_backend.api.datasets import router as datasets_router
    from pbl4.management_backend.api.events import router as events_router
    from pbl4.management_backend.api.jobs import router as jobs_router
    from pbl4.management_backend.api.runtime import router as runtime_router
    from pbl4.management_backend.api.system import router as system_router

    app.include_router(system_router)
    app.include_router(runtime_router)
    app.include_router(datasets_router)
    app.include_router(jobs_router)
    app.include_router(attempts_router)
    app.include_router(checkpoints_router)
    app.include_router(events_router)
    app.include_router(commands_router)

    # ─── WebSocket routes ─────────────────────────────────────────────────────
    from pbl4.management_backend.websocket import register_websocket_routes

    register_websocket_routes(app)

    return app
