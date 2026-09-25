"""Management Backend — FastAPI application factory.

Canonical responsibility:
- Creates and configures the FastAPI application instance for Management Backend.
- Registers API routers, middleware, exception handlers, and dependency providers.

Important boundary:
- Hosts management REST API and WebSocket routes; does not host DTP/1 training endpoints.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import psycopg_pool
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pbl4.management_backend.clients.dataset_manager import (
    DatasetManagerBusinessError,
    DatasetManagerUnavailableError,
)
from pbl4.management_backend.gateways.runtime_gateway import DatabaseUnavailableError
from pbl4.management_backend.services.allocation_service import (
    AllocationNotFoundError,
    AllocationStateError,
    WorkerAdmissionConfigError,
)
from pbl4.management_backend.services.attempt_service import (
    AttemptConflictError,
    AttemptDataIntegrityError,
    AttemptNotAbortableError,
    AttemptNotFoundError,
    AttemptStateError,
    CheckpointContractMismatchError,
    CheckpointNotCompleteError,
    CommandFailedError,
    CommandRejectedError,
    JobNotReadyError,
    RuntimeUnavailableError,
)
from pbl4.management_backend.services.cluster_scheduler import (
    NodeCapacityUnavailableError,
)
from pbl4.management_backend.services.command_service import CommandNotFoundError
from pbl4.management_backend.services.contract_resolver import ContractResolutionError
from pbl4.management_backend.services.dataset_service import (
    DatasetBuildNotFoundError,
    DatasetBuildReferenceError,
    DatasetBuildStateError,
    DatasetNotFoundError,
    InvalidCursorError,
)
from pbl4.management_backend.services.idempotency import (
    IdempotencyConflictError,
    RequestInProgressError,
)
from pbl4.management_backend.services.job_service import (
    JobFrozenError,
    JobNotFoundError,
    JobStateError,
    JobValidationError,
)
from pbl4.management_backend.services.node_enrollment_service import (
    NodeEnrollmentCodeExpiredError,
    NodeEnrollmentCodeInvalidError,
)
from pbl4.management_backend.services.node_service import (
    NodeNotFoundError,
    NodeOfflineError,
    NodeRevokedError,
    NodeUnauthorizedError,
)

logger = logging.getLogger(__name__)


def _run_node_maintenance_once(settings: Any) -> None:
    """Apply one durable liveness/worker-start maintenance cycle."""
    from pbl4.management_backend import db
    from pbl4.management_backend.gateways.node_control_gateway import (
        get_node_control_gateway,
    )
    from pbl4.management_backend.gateways.runtime_gateway import get_gateway
    from pbl4.management_backend.repositories import attempt_repository
    from pbl4.management_backend.services import (
        allocation_service,
        attempt_service,
        node_service,
    )

    with db.transaction() as conn:
        node_service.mark_stale_nodes(
            conn,
            timeout_seconds=settings.node_heartbeat_timeout_seconds,
        )
        timed_out_ids = allocation_service.fail_timed_out_dispatched_allocations(
            conn,
            timeout_seconds=settings.worker_start_timeout_seconds,
        )
        affected_attempts = {
            str(allocation_service.get_allocation(conn, allocation_id)["attempt_id"])
            for allocation_id in timed_out_ids
        }

    runtime_gateway = get_gateway()
    node_gateway = get_node_control_gateway()
    for attempt_id in sorted(affected_attempts):
        with db.transaction() as conn:
            attempt = attempt_repository.get_attempt(conn, attempt_id)
            if attempt is None or attempt.get("state") in (
                attempt_repository.TERMINAL_ATTEMPT_STATES
            ):
                continue
            abort_command = attempt_service.abort_attempt(
                conn,
                attempt_id,
                reason="Worker start timeout",
            )
            active_allocations = allocation_service.list_for_attempt(
                conn, attempt_id, active_only=True
            )

        try:
            runtime_gateway.send_command_and_wait_result(
                command_type="ABORT_ATTEMPT",
                command_id=str(abort_command["command_id"]),
                target_id=attempt_id,
                payload=attempt_service._extract_command_payload(abort_command),
                timeout=5.0,
            )
        except Exception as exc:
            logger.error(
                "Failed best-effort ABORT_ATTEMPT after worker start timeout for %s: %s",
                attempt_id,
                exc,
            )

        for allocation in active_allocations:
            try:
                with db.transaction() as conn:
                    allocation_service.stop_allocation(
                        conn,
                        str(allocation["allocation_id"]),
                        gateway=node_gateway,
                        force=True,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed best-effort STOP_WORKER for allocation %s: %s",
                    allocation.get("allocation_id"),
                    exc,
                )


async def _node_maintenance_loop(settings: Any) -> None:
    """Run periodic node-heartbeat and worker-start timeout maintenance."""
    interval = max(float(settings.node_heartbeat_interval_seconds), 1.0)
    while True:
        try:
            await asyncio.sleep(interval)
            if settings.database_url:
                try:
                    _run_node_maintenance_once(settings)
                except Exception as exc:
                    logger.error("Error in node maintenance loop: %s", exc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Unexpected error in node maintenance worker: %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and clean up the DB pool, gateways, and maintenance tasks."""
    from pbl4.management_backend import db
    from pbl4.management_backend.config import get_settings
    from pbl4.management_backend.gateways.node_control_gateway import init_node_control_gateway
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

    # Initialize node control gateway
    node_control_gateway = init_node_control_gateway()

    # Start periodic node & allocation maintenance loop
    maintenance_task = asyncio.create_task(_node_maintenance_loop(settings))

    # Initialize Dataset Manager client
    from pbl4.management_backend.clients.dataset_manager import init_client

    init_client(
        base_url=settings.dataset_manager_base_url,
        timeout=settings.dataset_manager_timeout_seconds,
    )

    logger.info("Management Backend started on %s:%d", settings.backend_host, settings.backend_port)
    yield

    # Shutdown
    maintenance_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await maintenance_task

    await node_control_gateway.close_all_connections()

    from pbl4.management_backend.gateways.runtime_gateway import get_gateway

    get_gateway().port.disconnect()
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
    command_id: str | None = None,
) -> JSONResponse:
    req_id = _get_req_id(request)
    error_obj: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details,
        "request_id": req_id,
    }
    if command_id is not None:
        error_obj["command_id"] = command_id
    return JSONResponse(
        status_code=status_code,
        content={"error": error_obj},
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

    # ─── Canonical Request ID & Response Envelope Middleware ─────────────────
    @app.middleware("http")
    async def canonical_response_middleware(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        import json

        req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:8]}"
        request.state.request_id = req_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id

        path = request.url.path
        if (
            path.startswith("/api/v1/")
            and response.status_code in (200, 201, 202)
            and response.headers.get("content-type", "").startswith("application/json")
        ):
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            try:
                data = json.loads(body_bytes.decode("utf-8"))
                if isinstance(data, dict):
                    if "error" in data:
                        return Response(
                            content=body_bytes,
                            status_code=response.status_code,
                            media_type="application/json",
                            headers=dict(response.headers),
                        )
                    if "data" in data and "page" in data:
                        return Response(
                            content=body_bytes,
                            status_code=response.status_code,
                            media_type="application/json",
                            headers=dict(response.headers),
                        )
                    if "data" in data and "meta" in data:
                        if isinstance(data["meta"], dict):
                            data["meta"]["request_id"] = req_id
                        new_body = json.dumps(data).encode("utf-8")
                        headers = dict(response.headers)
                        headers["content-length"] = str(len(new_body))
                        return Response(
                            content=new_body,
                            status_code=response.status_code,
                            media_type="application/json",
                            headers=headers,
                        )

                    return Response(
                        content=body_bytes,
                        status_code=response.status_code,
                        media_type="application/json",
                        headers=dict(response.headers),
                    )
            except Exception:
                pass

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                media_type="application/json",
                headers=dict(response.headers),
            )

        return response

    # ─── Global Error Handlers ────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        from fastapi.encoders import jsonable_encoder

        safe_errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
        return _error_response(
            422,
            "VALIDATION_ERROR",
            "Request validation failed.",
            request,
            details={"errors": safe_errors},
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

    @app.exception_handler(InvalidCursorError)
    async def invalid_cursor_handler(request: Request, exc: InvalidCursorError) -> JSONResponse:
        return _error_response(400, "INVALID_CURSOR", str(exc), request)

    @app.exception_handler(JobNotFoundError)
    @app.exception_handler(AttemptNotFoundError)
    @app.exception_handler(DatasetNotFoundError)
    @app.exception_handler(DatasetBuildNotFoundError)
    @app.exception_handler(CommandNotFoundError)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(404, "NOT_FOUND", str(exc), request)

    @app.exception_handler(AttemptDataIntegrityError)
    async def attempt_integrity_error_handler(
        request: Request, exc: AttemptDataIntegrityError
    ) -> JSONResponse:
        logger.error("Attempt data integrity error processing %s: %s", request.url.path, exc)
        return _error_response(500, "DATA_INTEGRITY_ERROR", str(exc), request)

    @app.exception_handler(RuntimeUnavailableError)
    async def runtime_unavailable_handler(
        request: Request, exc: RuntimeUnavailableError
    ) -> JSONResponse:
        return _error_response(
            503,
            "RUNTIME_UNAVAILABLE",
            str(exc),
            request,
            command_id=exc.command_id,
        )

    @app.exception_handler(DatasetManagerUnavailableError)
    async def dataset_manager_unavailable_handler(
        request: Request, exc: DatasetManagerUnavailableError
    ) -> JSONResponse:
        return _error_response(503, "DATASET_MANAGER_UNAVAILABLE", str(exc), request)

    @app.exception_handler(DatasetManagerBusinessError)
    async def dataset_manager_business_handler(
        request: Request, exc: DatasetManagerBusinessError
    ) -> JSONResponse:
        code = exc.code
        status_code = exc.status_code
        if status_code == 404:
            code = "NOT_FOUND"
        elif exc.code == "BUILD_NOT_READY":
            code = "DATASET_BUILD_NOT_READY"
            status_code = 409

        details = exc.details or {}
        details = {"info": details} if not isinstance(details, dict) else dict(details)
        details["downstream_code"] = exc.code
        details["downstream_status"] = exc.status_code

        return _error_response(
            status_code,
            code,
            exc.message,
            request,
            details=details,
        )

    @app.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_handler(
        request: Request, exc: DatabaseUnavailableError
    ) -> JSONResponse:
        return _error_response(
            503,
            "DATABASE_UNAVAILABLE",
            str(exc),
            request,
            command_id=exc.command_id,
        )

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(psycopg_pool.PoolTimeout)
    async def database_operational_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Database operational error processing %s: %s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return _error_response(
            503,
            "DATABASE_UNAVAILABLE",
            "Database is currently unavailable. Please retry later.",
            request,
        )

    @app.exception_handler(psycopg.DataError)
    async def database_data_error_handler(request: Request, exc: psycopg.DataError) -> JSONResponse:
        logger.error(
            "Database data error processing %s: %s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return _error_response(
            500,
            "INTERNAL_SERVER_ERROR",
            "A database data processing error occurred.",
            request,
        )

    @app.exception_handler(JobFrozenError)
    async def job_frozen_handler(request: Request, exc: JobFrozenError) -> JSONResponse:
        return _error_response(409, "JOB_FROZEN", str(exc), request)

    @app.exception_handler(JobNotReadyError)
    async def job_not_ready_handler(request: Request, exc: JobNotReadyError) -> JSONResponse:
        return _error_response(409, "JOB_NOT_READY", str(exc), request)

    @app.exception_handler(CommandRejectedError)
    async def command_rejected_handler(request: Request, exc: CommandRejectedError) -> JSONResponse:
        return _error_response(
            exc.status_code,
            exc.code,
            exc.message,
            request,
            details=exc.details,
            command_id=exc.command_id,
        )

    @app.exception_handler(CommandFailedError)
    async def command_failed_handler(request: Request, exc: CommandFailedError) -> JSONResponse:
        return _error_response(
            exc.status_code,
            exc.code,
            exc.message,
            request,
            details=exc.details,
            command_id=exc.command_id,
        )

    @app.exception_handler(AttemptNotAbortableError)
    async def attempt_not_abortable_handler(
        request: Request, exc: AttemptNotAbortableError
    ) -> JSONResponse:
        details = {"state": exc.current_state} if getattr(exc, "current_state", None) else None
        return _error_response(
            409,
            "ATTEMPT_NOT_ABORTABLE",
            str(exc),
            request,
            details=details,
        )

    @app.exception_handler(CheckpointNotCompleteError)
    async def checkpoint_not_complete_handler(
        request: Request, exc: CheckpointNotCompleteError
    ) -> JSONResponse:
        return _error_response(409, "CHECKPOINT_NOT_COMPLETE", str(exc), request)

    @app.exception_handler(CheckpointContractMismatchError)
    async def checkpoint_mismatch_handler(
        request: Request, exc: CheckpointContractMismatchError
    ) -> JSONResponse:
        return _error_response(409, "CHECKPOINT_CONTRACT_MISMATCH", str(exc), request)

    @app.exception_handler(JobStateError)
    @app.exception_handler(AttemptStateError)
    @app.exception_handler(DatasetBuildStateError)
    async def state_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
        code = getattr(exc, "code", "INVALID_STATE")
        return _error_response(409, code, str(exc), request)

    @app.exception_handler(AttemptConflictError)
    async def attempt_conflict_handler(request: Request, exc: AttemptConflictError) -> JSONResponse:
        return _error_response(409, "ACTIVE_ATTEMPT_EXISTS", str(exc), request)

    @app.exception_handler(DatasetBuildReferenceError)
    async def build_reference_handler(
        request: Request, exc: DatasetBuildReferenceError
    ) -> JSONResponse:
        details = {"references": exc.references} if exc.references else None
        return _error_response(
            409,
            "DATASET_BUILD_IN_USE",
            str(exc),
            request,
            details=details,
        )

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
        cmd_id = None
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            code = exc.detail["code"]
            msg = exc.detail.get("message", "HTTP error")
            details = exc.detail.get("details")
            cmd_id = exc.detail.get("command_id")
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
        return _error_response(exc.status_code, code, msg, request, details, command_id=cmd_id)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        msg = str(exc)
        if "pool" in msg.lower() or "not initialized" in msg.lower():
            return _error_response(503, "DATABASE_UNAVAILABLE", msg, request)
        return _error_response(500, "INTERNAL_ERROR", msg, request)

    @app.exception_handler(Exception)
    async def catch_all_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception processing %s: %s", request.url.path, exc, exc_info=True)
        return _error_response(
            500,
            "INTERNAL_SERVER_ERROR",
            "An unexpected server error occurred.",
            request,
        )

    # ─── Node & Allocation Exception Handlers ─────────────────────────────────
    @app.exception_handler(NodeEnrollmentCodeInvalidError)
    async def node_enrollment_code_invalid_handler(
        request: Request, exc: NodeEnrollmentCodeInvalidError
    ) -> JSONResponse:
        return _error_response(400, exc.code, str(exc), request)

    @app.exception_handler(NodeEnrollmentCodeExpiredError)
    async def node_enrollment_code_expired_handler(
        request: Request, exc: NodeEnrollmentCodeExpiredError
    ) -> JSONResponse:
        return _error_response(400, exc.code, str(exc), request)

    @app.exception_handler(NodeUnauthorizedError)
    async def node_unauthorized_handler(
        request: Request, exc: NodeUnauthorizedError
    ) -> JSONResponse:
        return _error_response(401, exc.code, str(exc), request)

    @app.exception_handler(NodeRevokedError)
    async def node_revoked_handler(request: Request, exc: NodeRevokedError) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(NodeOfflineError)
    async def node_offline_handler(request: Request, exc: NodeOfflineError) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(NodeCapacityUnavailableError)
    async def node_capacity_unavailable_handler(
        request: Request, exc: NodeCapacityUnavailableError
    ) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(NodeNotFoundError)
    async def node_not_found_handler(request: Request, exc: NodeNotFoundError) -> JSONResponse:
        return _error_response(404, "NOT_FOUND", str(exc), request)

    @app.exception_handler(AllocationNotFoundError)
    async def allocation_not_found_handler(
        request: Request, exc: AllocationNotFoundError
    ) -> JSONResponse:
        return _error_response(404, "NOT_FOUND", str(exc), request)

    @app.exception_handler(AllocationStateError)
    async def allocation_state_handler(request: Request, exc: AllocationStateError) -> JSONResponse:
        return _error_response(409, exc.code, str(exc), request)

    @app.exception_handler(WorkerAdmissionConfigError)
    async def worker_admission_config_handler(
        request: Request, exc: WorkerAdmissionConfigError
    ) -> JSONResponse:
        return _error_response(500, exc.code, str(exc), request)

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
    from pbl4.management_backend.api.nodes import router as nodes_router
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
    app.include_router(nodes_router)

    # ─── WebSocket routes ─────────────────────────────────────────────────────
    from pbl4.management_backend.websocket import register_websocket_routes

    register_websocket_routes(app)

    return app
