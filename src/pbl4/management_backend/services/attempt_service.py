"""Attempt Service — business logic for training attempt lifecycle.

V1 invariants:
  - At most one active Attempt at a time (enforced by DB unique index).
  - Attempt execution modes: FRESH, RETRY_FROM_START, RESUME.
  - START_ATTEMPT / ABORT_ATTEMPT commands are persisted BEFORE dispatch to runtime.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import psycopg.errors

from pbl4.management_backend.gateways.runtime_gateway import RuntimeUnavailableError, get_gateway
from pbl4.management_backend.repositories import (
    allocation_repository,
    attempt_repository,
    checkpoint_repository,
    command_repository,
    event_repository,
    job_repository,
    node_repository,
    step_repository,
    worker_session_repository,
)
from pbl4.management_backend.services import idempotency, job_service
from pbl4.management_backend.services.allocation_service import AllocationService
from pbl4.management_backend.services.cluster_scheduler import (
    ClusterScheduler,
)
from pbl4.management_backend.services.dataset_service import (
    InvalidCursorError as InvalidCursorError,
)
from pbl4.management_backend.services.dataset_service import (
    decode_cursor as decode_cursor,
)
from pbl4.management_backend.services.dataset_service import (
    encode_cursor as encode_cursor,
)

logger = logging.getLogger(__name__)

PUBLIC_COMMAND_ERROR_CODES = {
    "ACTIVE_ATTEMPT_EXISTS",
    "ATTEMPT_NOT_ABORTABLE",
    "CHECKPOINT_CONTRACT_MISMATCH",
    "CHECKPOINT_NOT_COMPLETE",
    "COMMAND_FAILED",
    "COMMAND_REJECTED",
    "INVALID_STATE",
    "JOB_NOT_READY",
    "NODE_CAPACITY_UNAVAILABLE",
    "WORKER_SPAWN_FAILED",
}


def _require_idempotency_key(value: str | None) -> str:
    if not value:
        raise ValueError("Idempotency-Key is required for this mutation.")
    return value


class AttemptNotFoundError(Exception):
    pass


class AttemptDataIntegrityError(Exception):
    """Raised when attempt data or its parent contract is corrupted or inconsistent."""

    pass


class AttemptStateError(Exception):
    code = "INVALID_STATE"

    def __init__(self, msg: str, current_state: str = "") -> None:
        super().__init__(msg)
        self.current_state = current_state


class AttemptNotAbortableError(AttemptStateError):
    code = "ATTEMPT_NOT_ABORTABLE"


class CheckpointNotCompleteError(AttemptStateError):
    code = "CHECKPOINT_NOT_COMPLETE"


class CheckpointContractMismatchError(AttemptStateError):
    code = "CHECKPOINT_CONTRACT_MISMATCH"


class AttemptConflictError(Exception):
    """Raised when a new attempt would violate the single-active invariant."""

    code = "ACTIVE_ATTEMPT_EXISTS"


class JobNotReadyError(Exception):
    code = "JOB_NOT_READY"


class CommandRejectedError(Exception):
    def __init__(
        self,
        message: str,
        command_id: str,
        code: str = "COMMAND_REJECTED",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.command_id = command_id
        self.code = code
        self.status_code = 409
        self.details = details


class CommandFailedError(Exception):
    def __init__(
        self,
        message: str,
        command_id: str,
        code: str = "COMMAND_FAILED",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.command_id = command_id
        self.code = code
        self.status_code = 502
        self.details = details


def _check_cached_error(cached_record: dict | None) -> None:
    if not cached_record:
        return
    status_code = cached_record.get("response_status_code") or 200
    if status_code >= 400:
        body = cached_record.get("response_body_jsonb") or {}
        if isinstance(body, str):
            body = json.loads(body)
        err = body.get("error", body)
        code = err.get("code", "COMMAND_FAILED")
        msg = err.get("message", "Command was rejected or failed.")
        cmd_id = err.get("command_id") or str(cached_record.get("command_id"))
        if status_code == 409:
            raise CommandRejectedError(msg, command_id=cmd_id, code=code)
        else:
            raise CommandFailedError(msg, command_id=cmd_id, code=code)


def _handle_command_outcome(
    db_module,
    *,
    cmd_result: dict[str, Any],
    command_id: str,
    target_id: str,
    scope: str,
    effective_key: str,
    success_response_payload: dict[str, Any],
    default_reject_code: str = "COMMAND_REJECTED",
) -> None:
    cmd_state = cmd_result["state"]
    if cmd_state in ("REJECTED", "FAILED"):
        res = cmd_result.get("result") or {}
        err_msg = (
            res.get("message")
            or res.get("reason")
            or f"Command '{command_id}' was {cmd_state.lower()} by Runtime."
        )
        runtime_code = res.get("code")
        fallback_code = default_reject_code if cmd_state == "REJECTED" else "COMMAND_FAILED"
        err_code = runtime_code if runtime_code in PUBLIC_COMMAND_ERROR_CODES else fallback_code
        details = (
            {"runtime_code": runtime_code} if runtime_code and runtime_code != err_code else None
        )
        status_code = 409 if cmd_state == "REJECTED" else 502
        err_payload = {
            "error": {
                "code": err_code,
                "message": err_msg,
                "command_id": command_id,
                "details": details,
            }
        }
        with db_module.transaction() as conn:
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope=scope,
                idempotency_key=effective_key,
                response_status_code=status_code,
                response_body=err_payload,
                command_id=command_id,
                resource_id=target_id,
            )
        if cmd_state == "REJECTED":
            raise CommandRejectedError(
                err_msg, command_id=command_id, code=err_code, details=details
            )
        else:
            raise CommandFailedError(err_msg, command_id=command_id, code=err_code, details=details)

    with db_module.transaction() as conn:
        idempotency.complete_record(
            conn,
            endpoint_semantic_scope=scope,
            idempotency_key=effective_key,
            response_status_code=202,
            response_body=success_response_payload,
            command_id=command_id,
            resource_id=target_id,
        )


def _new_attempt_id() -> str:
    return f"atm_{uuid.uuid4().hex[:12]}"


def _new_command_id() -> str:
    return str(uuid.uuid4())


def _select_and_create_allocations(
    conn: psycopg.Connection,
    attempt_id: str,
    resolved_contract: dict[str, Any] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    sync_cfg = (resolved_contract or {}).get("synchronization") or {}
    expected_workers = sync_cfg.get("expected_workers")
    if (
        expected_workers is None
        or not isinstance(expected_workers, int)
        or isinstance(expected_workers, bool)
        or expected_workers <= 0
    ):
        raise ValueError(
            "Invalid or missing expected_workers in "
            f"resolved_contract['synchronization']: {expected_workers!r}"
        )

    online_nodes = node_repository.list_nodes(
        conn, state=node_repository.NODE_STATE_ONLINE, limit=1000
    )
    active_allocs = allocation_repository.list_active(conn)
    placements = ClusterScheduler.select_placements(
        expected_workers=expected_workers,
        nodes=online_nodes,
        active_allocations=active_allocs,
    )

    return AllocationService.create_allocations_for_attempt(
        conn,
        attempt_id=attempt_id,
        placements=placements,
        now=now,
    )


# ─── Start / Retry / Resume ──────────────────────────────────────────────────


def start_job(conn: psycopg.Connection, job_id: str, note: str | None = None) -> tuple[dict, dict]:
    """Start a FRESH attempt for a DRAFT or READY job.

    If job is in DRAFT state, it is frozen to READY first (freeze-on-start).
    Returns (attempt_row, command_row).
    Raises AttemptConflictError if another attempt is already active (V1 constraint).
    """
    job = job_repository.get_job(conn, job_id)
    if job is None:
        raise JobNotReadyError(f"Job '{job_id}' not found.")
    if job["state"] == "DRAFT":
        job = job_service.freeze_job(conn, job_id)
    elif job["state"] != "READY":
        raise JobNotReadyError(
            f"Job '{job_id}' is in state '{job['state']}'; must be DRAFT or READY to start."
        )

    active = attempt_repository.get_active_attempt(conn)
    if active:
        raise AttemptConflictError(
            f"Active attempt '{active['attempt_id']}' already running "
            "(V1: only one active at a time)."
        )

    attempt_id = _new_attempt_id()
    command_id = _new_command_id()
    now = datetime.now(UTC)

    res = job.get("resolved_contract")
    if isinstance(res, str):
        res = json.loads(res)

    request_payload = {
        "command_id": command_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": "FRESH",
        "resolved_contract": res,
        "contract_hash": job["contract_hash"],
        "resume_from_checkpoint_id": None,
        "requested_at": now.isoformat(),
        "note": note,
    }

    try:
        with conn.transaction():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="FRESH",
                created_at=now,
            )
            _select_and_create_allocations(
                conn, attempt_id=attempt_id, resolved_contract=res, now=now
            )
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="START_ATTEMPT",
                target_type="ATTEMPT",
                target_id=attempt_id,
                request=request_payload,
                requested_at=now,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise AttemptConflictError(
            f"Active attempt already running for job '{job_id}' (V1: only one active at a time)."
        ) from exc

    logger.info("Attempt created: %s (job=%s, cmd=%s)", attempt_id, job_id, command_id)
    return attempt_row, cmd_row


def retry_job(conn: psycopg.Connection, job_id: str) -> tuple[dict, dict]:
    """Retry a job from the start (RETRY_FROM_START)."""
    job = job_repository.get_job(conn, job_id)
    if job is None:
        raise JobNotReadyError(f"Job '{job_id}' not found.")
    if job["state"] != "READY":
        raise JobNotReadyError(f"Job '{job_id}' must be READY to retry.")

    active = attempt_repository.get_active_attempt(conn)
    if active:
        raise AttemptConflictError(
            f"Active attempt '{active['attempt_id']}' is running. Abort it before retrying."
        )

    attempt_id = _new_attempt_id()
    command_id = _new_command_id()
    now = datetime.now(UTC)

    res = job.get("resolved_contract")
    if isinstance(res, str):
        res = json.loads(res)

    request_payload = {
        "command_id": command_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": "RETRY_FROM_START",
        "resolved_contract": res,
        "contract_hash": job["contract_hash"],
        "resume_from_checkpoint_id": None,
        "requested_at": now.isoformat(),
    }

    try:
        with conn.transaction():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="RETRY_FROM_START",
                created_at=now,
            )
            _select_and_create_allocations(
                conn, attempt_id=attempt_id, resolved_contract=res, now=now
            )
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="START_ATTEMPT",
                target_type="ATTEMPT",
                target_id=attempt_id,
                request=request_payload,
                requested_at=now,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise AttemptConflictError(
            f"Active attempt already running for job '{job_id}' (V1: only one active at a time)."
        ) from exc

    logger.info("Retry attempt created: %s (job=%s)", attempt_id, job_id)
    return attempt_row, cmd_row


def resume_job(conn: psycopg.Connection, job_id: str, checkpoint_id: str) -> tuple[dict, dict]:
    """Resume a job from a specific checkpoint (RESUME)."""
    job = job_repository.get_job(conn, job_id)
    if job is None:
        raise JobNotReadyError(f"Job '{job_id}' not found.")
    if job["state"] != "READY":
        raise JobNotReadyError(f"Job '{job_id}' must be READY to resume.")

    ckpt = checkpoint_repository.get_checkpoint(conn, checkpoint_id)
    if ckpt is None:
        raise AttemptNotFoundError(f"Checkpoint '{checkpoint_id}' not found.")
    if ckpt["state"] != "COMPLETE":
        raise CheckpointNotCompleteError(
            f"Checkpoint '{checkpoint_id}' is in state '{ckpt['state']}'; "
            "only COMPLETE checkpoints can be resumed.",
            current_state=ckpt["state"],
        )
    if ckpt["contract_hash"] != job["contract_hash"]:
        raise CheckpointContractMismatchError(
            f"Checkpoint contract_hash '{ckpt['contract_hash']}' "
            f"does not match job contract_hash '{job['contract_hash']}'."
        )
    descriptor_fields = (
        "created_by_attempt_id",
        "model_sha256",
        "metadata_sha256",
    )
    if any(
        not isinstance(ckpt.get(field), str) or not ckpt.get(field) for field in descriptor_fields
    ):
        raise CheckpointNotCompleteError(
            f"Checkpoint '{checkpoint_id}' lacks its durable integrity descriptor.",
            current_state=ckpt["state"],
        )

    res = job.get("resolved_contract")
    if isinstance(res, str):
        res = json.loads(res)
    if (
        res
        and ckpt.get("dataset_build_id")
        and res.get("dataset_build_id")
        and ckpt["dataset_build_id"] != res["dataset_build_id"]
    ):
        raise CheckpointContractMismatchError(
            f"Checkpoint dataset_build_id '{ckpt['dataset_build_id']}' "
            f"does not match job contract '{res['dataset_build_id']}'."
        )

    active = attempt_repository.get_active_attempt(conn)
    if active:
        raise AttemptConflictError(
            f"Active attempt '{active['attempt_id']}' is running. Abort before resuming."
        )

    attempt_id = _new_attempt_id()
    command_id = _new_command_id()
    now = datetime.now(UTC)

    request_payload = {
        "command_id": command_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": "RESUME",
        "resolved_contract": res,
        "contract_hash": job["contract_hash"],
        "resume_from_checkpoint_id": checkpoint_id,
        "resume_checkpoint": {
            "checkpoint_id": checkpoint_id,
            "source_attempt_id": ckpt["created_by_attempt_id"],
            "model_sha256": ckpt["model_sha256"],
            "metadata_sha256": ckpt["metadata_sha256"],
        },
        "requested_at": now.isoformat(),
    }

    try:
        with conn.transaction():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="RESUME",
                resume_from_checkpoint_id=checkpoint_id,
                created_at=now,
            )
            _select_and_create_allocations(
                conn, attempt_id=attempt_id, resolved_contract=res, now=now
            )
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="START_ATTEMPT",
                target_type="ATTEMPT",
                target_id=attempt_id,
                request=request_payload,
                requested_at=now,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise AttemptConflictError(
            f"Active attempt already running for job '{job_id}' (V1: only one active at a time)."
        ) from exc

    logger.info("Resume attempt created: %s (job=%s, ckpt=%s)", attempt_id, job_id, checkpoint_id)
    return attempt_row, cmd_row


# ─── Query ───────────────────────────────────────────────────────────────────


def get_attempt(conn: psycopg.Connection, attempt_id: str) -> dict:
    row = attempt_repository.get_attempt(conn, attempt_id)
    if row is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")
    return row


def get_attempt_detail(conn: psycopg.Connection, attempt_id: str) -> dict:
    row = attempt_repository.get_attempt(conn, attempt_id)
    if row is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")

    job = job_repository.get_job(conn, row["job_id"])
    if job is None:
        raise AttemptDataIntegrityError(
            f"Parent job '{row['job_id']}' for attempt '{attempt_id}' not found."
        )

    rc = job.get("resolved_contract") if job else None
    if isinstance(rc, str):
        try:
            rc = json.loads(rc)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AttemptDataIntegrityError(
                f"Attempt '{attempt_id}' has an unparseable frozen resolved contract."
            ) from exc
    if not isinstance(rc, dict) or "synchronization" not in rc:
        raise AttemptDataIntegrityError(
            f"Attempt '{attempt_id}' has an invalid frozen resolved contract."
        )

    try:
        sync = rc["synchronization"]
        expected_workers = sync["expected_workers"]
        training_strategy = sync["training_strategy"]
    except (KeyError, TypeError) as exc:
        raise AttemptDataIntegrityError(
            f"Attempt '{attempt_id}' has an invalid frozen resolved contract."
        ) from exc

    if (
        not isinstance(expected_workers, int)
        or isinstance(expected_workers, bool)
        or expected_workers <= 0
    ):
        raise AttemptDataIntegrityError(
            f"Attempt '{attempt_id}' has invalid expected_workers in its frozen contract."
        )

    workers = worker_session_repository.get_sessions_for_attempt(conn, attempt_id)
    snap = get_attempt_snapshot(conn, attempt_id)

    return {
        "row": row,
        "job": job,
        "expected_workers": expected_workers,
        "training_strategy": training_strategy,
        "workers": workers,
        "snapshot": snap,
    }


def list_attempts(
    conn: psycopg.Connection,
    *,
    job_id: str | None = None,
    state: str | None = None,
    execution_mode: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    cursor_dt: datetime | None = None
    cursor_id: str | None = None
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
    return attempt_repository.list_attempts(
        conn,
        job_id=job_id,
        state=state,
        execution_mode=execution_mode,
        limit=limit,
        cursor=cursor,
        cursor_dt=cursor_dt,
        cursor_id=cursor_id,
    )


def get_attempt_snapshot(conn: psycopg.Connection, attempt_id: str) -> dict:
    """Return the current or last-known reconciled Runtime projection."""
    row = attempt_repository.get_attempt(conn, attempt_id)
    if row is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")

    sessions = worker_session_repository.get_sessions_for_attempt(conn, attempt_id)
    latest_ckpt = checkpoint_repository.get_latest_complete_for_attempt(conn, attempt_id)

    metadata = row.get("runtime_metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    gateway_snapshot = get_gateway().get_authoritative_snapshot(attempt_id)
    runtime_seq = metadata.get("authoritative_snapshot_seq")
    observed_at = metadata.get("observed_at") or metadata.get("reconciled_at")
    snapshot = {
        "attempt_id": attempt_id,
        "state": row["state"],
        "training_strategy": metadata.get("training_strategy"),
        "epoch": metadata.get("epoch"),
        "current_operation_id": metadata.get("current_operation_id"),
        "current_batch_ordinal": metadata.get("current_batch_ordinal"),
        "model_version": metadata.get("model_version"),
        "workers": sessions,
        "strategy_state": metadata.get("strategy_state"),
        "checkpoint_state": latest_ckpt["state"] if latest_ckpt else None,
        "latest_checkpoint_id": latest_ckpt["checkpoint_id"] if latest_ckpt else None,
        "stale": True,
        "observed_at": observed_at,
        "runtime_event_seq": runtime_seq,
    }
    if gateway_snapshot is not None:
        for key in (
            "attempt_state",
            "state",
            "training_strategy",
            "epoch",
            "current_operation_id",
            "current_batch_ordinal",
            "model_version",
            "strategy_state",
            "checkpoint_state",
            "latest_checkpoint_id",
            "stale",
            "observed_at",
            "runtime_event_seq",
        ):
            if key in gateway_snapshot and gateway_snapshot[key] is not None:
                target_key = "state" if key == "attempt_state" else key
                snapshot[target_key] = gateway_snapshot[key]
    if not snapshot.get("strategy_state"):
        snapshot["strategy_state"] = None
    return snapshot


def list_attempt_workers(conn: psycopg.Connection, attempt_id: str) -> list[dict]:
    _ = get_attempt(conn, attempt_id)  # Validate existence
    return worker_session_repository.get_sessions_for_attempt(conn, attempt_id)


def get_worker(conn: psycopg.Connection, attempt_id: str, worker_id: int) -> dict:
    _ = get_attempt(conn, attempt_id)
    active = worker_session_repository.get_active_session_for_worker(conn, attempt_id, worker_id)
    history = worker_session_repository.get_sessions_for_worker(conn, attempt_id, worker_id)
    if not active and not history:
        raise AttemptNotFoundError(f"Worker {worker_id} not found for attempt '{attempt_id}'.")
    return {
        "worker_id": worker_id,
        "active_session": active,
        "historical_sessions": history,
    }


def list_attempt_events(
    conn: psycopg.Connection,
    attempt_id: str,
    *,
    event_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    after_seq: int | None = None,
) -> list[dict]:
    _ = get_attempt(conn, attempt_id)
    return event_repository.list_events(
        conn,
        attempt_id=attempt_id,
        event_type=event_type,
        severity=severity,
        limit=limit,
        cursor=cursor,
        after_seq=after_seq,
        runtime_only=True,
    )


def list_attempt_steps(
    conn: psycopg.Connection,
    attempt_id: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    _ = get_attempt(conn, attempt_id)
    return step_repository.list_steps(conn, attempt_id, limit=limit, cursor=cursor)


def get_step(conn: psycopg.Connection, attempt_id: str, step_id: int) -> dict:
    _ = get_attempt(conn, attempt_id)
    step = step_repository.get_step(conn, attempt_id, step_id)
    if step is None:
        raise AttemptNotFoundError(f"Step {step_id} not found for attempt '{attempt_id}'.")
    worker_steps = step_repository.get_worker_steps(conn, attempt_id, step_id)
    return {**step, "worker_steps": worker_steps}


# ─── Commands ────────────────────────────────────────────────────────────────


def abort_attempt(conn: psycopg.Connection, attempt_id: str, reason: str | None = None) -> dict:
    attempt = attempt_repository.get_attempt(conn, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")
    if attempt["state"] not in attempt_repository.ABORTABLE_ATTEMPT_STATES:
        raise AttemptNotAbortableError(
            f"Attempt '{attempt_id}' is in state '{attempt['state']}'; cannot be aborted.",
            current_state=attempt["state"],
        )

    command_id = _new_command_id()
    now = datetime.now(UTC)

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="ABORT_ATTEMPT",
        target_type="ATTEMPT",
        target_id=attempt_id,
        request={
            "command_id": command_id,
            "job_id": attempt["job_id"],
            "attempt_id": attempt_id,
            "reason": reason,
            "requested_at": now.isoformat(),
        },
        requested_at=now,
    )

    logger.info("Abort command issued: %s (attempt=%s)", command_id, attempt_id)
    return cmd_row


def request_checkpoint(
    conn: psycopg.Connection, attempt_id: str, reason: str | None = None
) -> dict:
    attempt = attempt_repository.get_attempt(conn, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")
    if attempt["state"] != "RUNNING":
        raise AttemptStateError(
            f"Attempt '{attempt_id}' is '{attempt['state']}'; "
            "checkpoint can only be requested when RUNNING.",
            current_state=attempt["state"],
        )

    command_id = _new_command_id()
    now = datetime.now(UTC)

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="REQUEST_CHECKPOINT",
        target_type="ATTEMPT",
        target_id=attempt_id,
        request={
            "command_id": command_id,
            "job_id": attempt["job_id"],
            "attempt_id": attempt_id,
            "reason": reason,
            "requested_at": now.isoformat(),
        },
        requested_at=now,
    )

    logger.info("Checkpoint request issued: %s (attempt=%s)", command_id, attempt_id)
    return cmd_row


def get_join_spec(conn: psycopg.Connection, attempt_id: str) -> dict | None:
    """Return the join spec for an active attempt (for worker handshake).

    Returns None when runtime is not connected.
    """
    attempt = attempt_repository.get_attempt(conn, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")
    if attempt["state"] not in attempt_repository.ACTIVE_ATTEMPT_STATES:
        raise AttemptStateError(
            f"Attempt '{attempt_id}' is not in an active state.",
            current_state=attempt["state"],
        )
    gw = get_gateway()
    if not gw.connected:
        return None

    from pbl4.management_backend.config import get_settings

    settings = get_settings()
    job = job_repository.get_job(conn, attempt["job_id"])
    if not job or not job.get("resolved_contract"):
        raise AttemptStateError(f"Job '{attempt['job_id']}' has no frozen resolved_contract.")

    rc = job["resolved_contract"]
    if isinstance(rc, str):
        rc = json.loads(rc)
    expected_workers = rc["synchronization"]["expected_workers"]

    return {
        "ps_host": settings.dtp_advertised_host,
        "ps_port": int(
            getattr(settings, "runtime_dtp_port", getattr(settings, "runtime_port", 9000))
        ),
        "job_id": attempt["job_id"],
        "attempt_id": attempt_id,
        "contract_hash": attempt["contract_hash"],
        "protocol": {
            "dtp_version": 1,
        },
        "expected_workers": expected_workers,
        "expires_at": None,
    }


# ─── 2-Phase Idempotent Command Execution ────────────────────────────────────


def _extract_command_payload(cmd_row: dict[str, Any]) -> dict[str, Any]:
    payload = cmd_row.get("request") or cmd_row.get("request_jsonb") or {}
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


def _dispatch_workers_for_attempt(
    db_module: Any,
    *,
    attempt_id: str,
    job: dict[str, Any] | None,
    attempt_row: dict[str, Any],
    node_gateway: Any | None = None,
    runtime_gateway: Any | None = None,
) -> None:
    from pbl4.management_backend.gateways.node_control_gateway import get_node_control_gateway

    node_gw = node_gateway or get_node_control_gateway()
    rt_gw = runtime_gateway or get_gateway()

    with db_module.transaction() as conn:
        allocations = AllocationService.list_for_attempt(conn, attempt_id)

    dispatched: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for alloc in allocations:
        alloc_id = str(alloc["allocation_id"])
        if alloc.get("actual_state") in (
            allocation_repository.ACTUAL_STATE_DISPATCHED,
            allocation_repository.ACTUAL_STATE_STARTED,
        ):
            dispatched.append(alloc)
            continue

        if failed:
            with db_module.transaction() as conn:
                updated = AllocationService.record_failed(
                    conn,
                    alloc_id,
                    failure_code="NODE_DISPATCH_FAILED",
                    failure_message=(
                        "Cancelled due to a prior allocation dispatch failure in attempt."
                    ),
                )
            failed.append(updated)
            continue

        try:
            start_cmd = AllocationService.build_start_worker_command(
                allocation=alloc,
                job=job,
                attempt=attempt_row,
            )
            with db_module.transaction() as conn:
                updated = AllocationService.dispatch_allocation(
                    conn,
                    alloc_id,
                    command=start_cmd,
                    gateway=node_gw,
                )
            if updated.get("actual_state") == allocation_repository.ACTUAL_STATE_FAILED:
                failed.append(updated)
            else:
                dispatched.append(updated)
        except Exception as exc:
            logger.error("Failed to build/dispatch START_WORKER for alloc %s: %s", alloc_id, exc)
            with db_module.transaction() as conn:
                updated = AllocationService.record_failed(
                    conn,
                    alloc_id,
                    failure_code="NODE_DISPATCH_FAILED",
                    failure_message=f"Dispatch failed: {exc}",
                )
            failed.append(updated)

    if failed:
        logger.warning(
            "Partial failure dispatching workers for attempt %s "
            "(%d succeeded, %d failed). Aborting attempt.",
            attempt_id,
            len(dispatched),
            len(failed),
        )
        # Send STOP_WORKER best-effort to already dispatched allocations
        for d_alloc in dispatched:
            try:
                stop_cmd = AllocationService.build_stop_worker_command(
                    allocation=d_alloc,
                    force=True,
                )
                node_gw.send_stop_worker(str(d_alloc["node_id"]), command=stop_cmd)
                with db_module.transaction() as conn:
                    allocation_repository.update_desired_state(
                        conn,
                        str(d_alloc["allocation_id"]),
                        allocation_repository.DESIRED_STATE_STOPPED,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed best-effort STOP_WORKER to node %s: %s", d_alloc.get("node_id"), exc
                )

        # Send ABORT_ATTEMPT to Runtime
        try:
            with db_module.transaction() as conn:
                abort_cmd_row = abort_attempt(
                    conn,
                    attempt_id,
                    reason="Partial worker dispatch failure",
                )
            rt_gw.send_command_and_wait_result(
                command_type="ABORT_ATTEMPT",
                command_id=str(abort_cmd_row["command_id"]),
                target_id=attempt_id,
                payload=_extract_command_payload(abort_cmd_row),
                timeout=5.0,
            )
        except Exception as exc:
            logger.error(
                "Failed to send ABORT_ATTEMPT to Runtime for attempt %s: %s", attempt_id, exc
            )

        raise CommandFailedError(
            f"Failed to dispatch workers for attempt '{attempt_id}': "
            f"{len(failed)} worker(s) failed.",
            command_id=str(attempt_row.get("command_id") or attempt_id),
            code="WORKER_SPAWN_FAILED",
        )


def execute_start_job(
    db_module: Any,
    job_id: str,
    *,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Execute START_ATTEMPT following the canonical 2-phase pattern.

    TX1: Acquire idempotency, persist attempt + PENDING command -> COMMIT.
    Outside TX: Dispatch via McpClientPort to Runtime.
    On failure: command remains PENDING, record dispatch failure -> raise RuntimeUnavailableError.
    TX2: Complete idempotency record with PENDING command_state -> COMMIT.
    """
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="START_ATTEMPT",
        path=f"/api/v1/jobs/{job_id}/start",
        body_obj={"job_id": job_id, "note": note},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="JOB_START",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            _check_cached_error(cached_record)
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            a_id = body.get("attempt_id")
            c_id = body.get("command_id")
            attempt_row = attempt_repository.get_attempt(conn, a_id) if a_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return attempt_row or body, cmd_row or body

        if (
            action == "RESUME"
            and cached_record
            and cached_record.get("command_id")
            and cached_record.get("resource_id")
        ):
            command_id = str(cached_record["command_id"])
            attempt_id = str(cached_record["resource_id"])
            cmd_row = command_repository.get_command(conn, command_id)
            attempt_row = attempt_repository.get_attempt(conn, attempt_id)
            if cmd_row and attempt_row:
                dispatch_payload = _extract_command_payload(cmd_row)
            else:
                attempt_row, cmd_row = start_job(conn, job_id, note=note)
                dispatch_payload = _extract_command_payload(cmd_row)
                command_id = str(cmd_row["command_id"])
                attempt_id = str(attempt_row["attempt_id"])
        else:
            attempt_row, cmd_row = start_job(conn, job_id, note=note)
            dispatch_payload = _extract_command_payload(cmd_row)
            command_id = str(cmd_row["command_id"])
            attempt_id = str(attempt_row["attempt_id"])

    gw = get_gateway()
    try:
        cmd_result = gw.send_command_and_wait_result(
            command_type="START_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload=dispatch_payload,
            timeout=5.0,
        )
    except RuntimeUnavailableError:
        logger.warning(
            "Runtime dispatch/acceptance failed for start_job cmd=%s attempt=%s (remains PENDING)",
            command_id,
            attempt_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="JOB_START",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    cmd_state = cmd_result["state"]
    if cmd_state in ("REJECTED", "FAILED"):
        _handle_command_outcome(
            db_module,
            cmd_result=cmd_result,
            command_id=command_id,
            target_id=attempt_id,
            scope="JOB_START",
            effective_key=effective_key,
            success_response_payload={},
            default_reject_code="ACTIVE_ATTEMPT_EXISTS",
        )

    # Runtime ACCEPTED -> Dispatch START_WORKER to selected Nodes
    with db_module.transaction() as conn:
        job = job_repository.get_job(conn, job_id)

    job_row = (
        job if job is not None else {"resolved_contract": dispatch_payload.get("resolved_contract")}
    )
    try:
        _dispatch_workers_for_attempt(
            db_module,
            attempt_id=attempt_id,
            job=job_row,
            attempt_row=attempt_row,
            runtime_gateway=gw,
        )
    except Exception as exc:
        err_code = getattr(exc, "code", "WORKER_SPAWN_FAILED")
        err_payload = {
            "error": {
                "code": err_code,
                "message": str(exc),
                "command_id": command_id,
            }
        }
        with db_module.transaction() as conn:
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="JOB_START",
                idempotency_key=effective_key,
                response_status_code=502,
                response_body=err_payload,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    resp_payload = {
        "command_id": command_id,
        "command_type": "START_ATTEMPT",
        "command_state": cmd_state,
        "target_type": "ATTEMPT",
        "target_id": attempt_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": attempt_row.get("execution_mode", "FRESH"),
    }
    _handle_command_outcome(
        db_module,
        cmd_result=cmd_result,
        command_id=command_id,
        target_id=attempt_id,
        scope="JOB_START",
        effective_key=effective_key,
        success_response_payload=resp_payload,
        default_reject_code="ACTIVE_ATTEMPT_EXISTS",
    )
    with db_module.transaction() as conn:
        cmd_row = command_repository.get_command(conn, command_id) or cmd_row

    if isinstance(cmd_row, dict):
        cmd_row = {**cmd_row, "command_state": cmd_state, "state": cmd_state}
    return attempt_row, cmd_row


def execute_retry_job(
    db_module: Any,
    job_id: str,
    *,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Execute RETRY_FROM_START following the canonical 2-phase pattern."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="RETRY_ATTEMPT",
        path=f"/api/v1/jobs/{job_id}/retry",
        body_obj={"job_id": job_id},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="JOB_RETRY",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            _check_cached_error(cached_record)
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            a_id = body.get("attempt_id")
            c_id = body.get("command_id")
            attempt_row = attempt_repository.get_attempt(conn, a_id) if a_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return attempt_row or body, cmd_row or body

        if (
            action == "RESUME"
            and cached_record
            and cached_record.get("command_id")
            and cached_record.get("resource_id")
        ):
            command_id = str(cached_record["command_id"])
            attempt_id = str(cached_record["resource_id"])
            cmd_row = command_repository.get_command(conn, command_id)
            attempt_row = attempt_repository.get_attempt(conn, attempt_id)
            if cmd_row and attempt_row:
                dispatch_payload = _extract_command_payload(cmd_row)
            else:
                attempt_row, cmd_row = retry_job(conn, job_id)
                dispatch_payload = _extract_command_payload(cmd_row)
                command_id = str(cmd_row["command_id"])
                attempt_id = str(attempt_row["attempt_id"])
        else:
            attempt_row, cmd_row = retry_job(conn, job_id)
            dispatch_payload = _extract_command_payload(cmd_row)
            command_id = str(cmd_row["command_id"])
            attempt_id = str(attempt_row["attempt_id"])

    gw = get_gateway()
    try:
        cmd_result = gw.send_command_and_wait_result(
            command_type="START_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload=dispatch_payload,
            timeout=5.0,
        )
    except RuntimeUnavailableError:
        logger.warning(
            "Runtime dispatch/acceptance failed for retry_job cmd=%s attempt=%s (remains PENDING)",
            command_id,
            attempt_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="JOB_RETRY",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    cmd_state = cmd_result["state"]
    if cmd_state in ("REJECTED", "FAILED"):
        _handle_command_outcome(
            db_module,
            cmd_result=cmd_result,
            command_id=command_id,
            target_id=attempt_id,
            scope="JOB_RETRY",
            effective_key=effective_key,
            success_response_payload={},
            default_reject_code="ACTIVE_ATTEMPT_EXISTS",
        )

    # Runtime ACCEPTED -> Dispatch START_WORKER to selected Nodes
    with db_module.transaction() as conn:
        job = job_repository.get_job(conn, job_id)

    job_row = (
        job if job is not None else {"resolved_contract": dispatch_payload.get("resolved_contract")}
    )
    try:
        _dispatch_workers_for_attempt(
            db_module,
            attempt_id=attempt_id,
            job=job_row,
            attempt_row=attempt_row,
            runtime_gateway=gw,
        )
    except Exception as exc:
        err_code = getattr(exc, "code", "WORKER_SPAWN_FAILED")
        err_payload = {
            "error": {
                "code": err_code,
                "message": str(exc),
                "command_id": command_id,
            }
        }
        with db_module.transaction() as conn:
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="JOB_RETRY",
                idempotency_key=effective_key,
                response_status_code=502,
                response_body=err_payload,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    resp_payload = {
        "command_id": command_id,
        "command_type": "START_ATTEMPT",
        "command_state": cmd_state,
        "target_type": "ATTEMPT",
        "target_id": attempt_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": attempt_row.get("execution_mode", "RETRY_FROM_START"),
    }
    _handle_command_outcome(
        db_module,
        cmd_result=cmd_result,
        command_id=command_id,
        target_id=attempt_id,
        scope="JOB_RETRY",
        effective_key=effective_key,
        success_response_payload=resp_payload,
        default_reject_code="ACTIVE_ATTEMPT_EXISTS",
    )
    with db_module.transaction() as conn:
        cmd_row = command_repository.get_command(conn, command_id) or cmd_row

    if isinstance(cmd_row, dict):
        cmd_row = {**cmd_row, "command_state": cmd_state, "state": cmd_state}
    return attempt_row, cmd_row


def execute_resume_job(
    db_module: Any,
    job_id: str,
    checkpoint_id: str,
    *,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Execute RESUME attempt following the canonical 2-phase pattern."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="RESUME_ATTEMPT",
        path=f"/api/v1/jobs/{job_id}/resume",
        body_obj={"job_id": job_id, "checkpoint_id": checkpoint_id},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="JOB_RESUME",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            _check_cached_error(cached_record)
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            a_id = body.get("attempt_id")
            c_id = body.get("command_id")
            attempt_row = attempt_repository.get_attempt(conn, a_id) if a_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return attempt_row or body, cmd_row or body

        if (
            action == "RESUME"
            and cached_record
            and cached_record.get("command_id")
            and cached_record.get("resource_id")
        ):
            command_id = str(cached_record["command_id"])
            attempt_id = str(cached_record["resource_id"])
            cmd_row = command_repository.get_command(conn, command_id)
            attempt_row = attempt_repository.get_attempt(conn, attempt_id)
            if cmd_row and attempt_row:
                dispatch_payload = _extract_command_payload(cmd_row)
            else:
                attempt_row, cmd_row = resume_job(conn, job_id, checkpoint_id)
                dispatch_payload = _extract_command_payload(cmd_row)
                command_id = str(cmd_row["command_id"])
                attempt_id = str(attempt_row["attempt_id"])
        else:
            attempt_row, cmd_row = resume_job(conn, job_id, checkpoint_id)
            dispatch_payload = _extract_command_payload(cmd_row)
            command_id = str(cmd_row["command_id"])
            attempt_id = str(attempt_row["attempt_id"])

    gw = get_gateway()
    try:
        cmd_result = gw.send_command_and_wait_result(
            command_type="START_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload=dispatch_payload,
            timeout=5.0,
        )
    except RuntimeUnavailableError:
        logger.warning(
            "Runtime dispatch/acceptance failed for resume_job cmd=%s attempt=%s (remains PENDING)",
            command_id,
            attempt_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="JOB_RESUME",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    cmd_state = cmd_result["state"]
    if cmd_state in ("REJECTED", "FAILED"):
        _handle_command_outcome(
            db_module,
            cmd_result=cmd_result,
            command_id=command_id,
            target_id=attempt_id,
            scope="JOB_RESUME",
            effective_key=effective_key,
            success_response_payload={},
            default_reject_code="CHECKPOINT_NOT_COMPLETE",
        )

    # Runtime ACCEPTED -> Dispatch START_WORKER to selected Nodes
    with db_module.transaction() as conn:
        job = job_repository.get_job(conn, job_id)

    job_row = (
        job if job is not None else {"resolved_contract": dispatch_payload.get("resolved_contract")}
    )
    try:
        _dispatch_workers_for_attempt(
            db_module,
            attempt_id=attempt_id,
            job=job_row,
            attempt_row=attempt_row,
            runtime_gateway=gw,
        )
    except Exception as exc:
        err_code = getattr(exc, "code", "WORKER_SPAWN_FAILED")
        err_payload = {
            "error": {
                "code": err_code,
                "message": str(exc),
                "command_id": command_id,
            }
        }
        with db_module.transaction() as conn:
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="JOB_RESUME",
                idempotency_key=effective_key,
                response_status_code=502,
                response_body=err_payload,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    resp_payload = {
        "command_id": command_id,
        "command_type": "START_ATTEMPT",
        "command_state": cmd_state,
        "target_type": "ATTEMPT",
        "target_id": attempt_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_mode": attempt_row.get("execution_mode", "RESUME"),
        "resume_from_checkpoint_id": checkpoint_id,
    }
    _handle_command_outcome(
        db_module,
        cmd_result=cmd_result,
        command_id=command_id,
        target_id=attempt_id,
        scope="JOB_RESUME",
        effective_key=effective_key,
        success_response_payload=resp_payload,
        default_reject_code="CHECKPOINT_NOT_COMPLETE",
    )
    with db_module.transaction() as conn:
        cmd_row = command_repository.get_command(conn, command_id) or cmd_row

    if isinstance(cmd_row, dict):
        cmd_row = {**cmd_row, "command_state": cmd_state, "state": cmd_state}
    return attempt_row, cmd_row


def execute_abort_attempt(
    db_module: Any,
    attempt_id: str,
    *,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Execute ABORT_ATTEMPT following the canonical 2-phase pattern."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="ABORT_ATTEMPT",
        path=f"/api/v1/attempts/{attempt_id}/abort",
        body_obj={"attempt_id": attempt_id, "reason": reason},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="ATTEMPT_ABORT",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            _check_cached_error(cached_record)
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            c_id = body.get("command_id")
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return cmd_row or body

        if action == "RESUME" and cached_record and cached_record.get("command_id"):
            command_id = str(cached_record["command_id"])
            cmd_row = command_repository.get_command(conn, command_id)
            if not cmd_row:
                cmd_row = abort_attempt(conn, attempt_id, reason=reason)
                command_id = str(cmd_row["command_id"])
        else:
            cmd_row = abort_attempt(conn, attempt_id, reason=reason)
            command_id = str(cmd_row["command_id"])

    gw = get_gateway()
    try:
        cmd_result = gw.send_command_and_wait_result(
            command_type="ABORT_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload=_extract_command_payload(cmd_row),
            timeout=5.0,
        )
    except RuntimeUnavailableError:
        logger.warning(
            "Runtime dispatch/acceptance failed for abort_attempt "
            "cmd=%s attempt=%s (remains PENDING)",
            command_id,
            attempt_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="ATTEMPT_ABORT",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    cmd_state = cmd_result["state"]
    resp_payload = {
        "command_id": command_id,
        "command_type": "ABORT_ATTEMPT",
        "command_state": cmd_state,
        "target_type": "ATTEMPT",
        "target_id": attempt_id,
        "attempt_id": attempt_id,
    }
    _handle_command_outcome(
        db_module,
        cmd_result=cmd_result,
        command_id=command_id,
        target_id=attempt_id,
        scope="ATTEMPT_ABORT",
        effective_key=effective_key,
        success_response_payload=resp_payload,
        default_reject_code="ATTEMPT_NOT_ABORTABLE",
    )
    with db_module.transaction() as conn:
        cmd_row = command_repository.get_command(conn, command_id) or cmd_row

    if isinstance(cmd_row, dict):
        cmd_row = {**cmd_row, "command_state": cmd_state, "state": cmd_state}
    return cmd_row


def execute_request_checkpoint(
    db_module: Any,
    attempt_id: str,
    *,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Execute REQUEST_CHECKPOINT following the canonical 2-phase pattern."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="REQUEST_CHECKPOINT",
        path=f"/api/v1/attempts/{attempt_id}/checkpoint-requests",
        body_obj={"attempt_id": attempt_id, "reason": reason},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="CHECKPOINT_REQUEST",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            _check_cached_error(cached_record)
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            c_id = body.get("command_id")
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return cmd_row or body

        if action == "RESUME" and cached_record and cached_record.get("command_id"):
            command_id = str(cached_record["command_id"])
            cmd_row = command_repository.get_command(conn, command_id)
            if not cmd_row:
                cmd_row = request_checkpoint(conn, attempt_id, reason=reason)
                command_id = str(cmd_row["command_id"])
        else:
            cmd_row = request_checkpoint(conn, attempt_id, reason=reason)
            command_id = str(cmd_row["command_id"])

    gw = get_gateway()
    try:
        cmd_result = gw.send_command_and_wait_result(
            command_type="REQUEST_CHECKPOINT",
            command_id=command_id,
            target_id=attempt_id,
            payload=cmd_row["request"],
            timeout=5.0,
        )
    except RuntimeUnavailableError:
        logger.warning(
            "Runtime dispatch/acceptance failed for request_checkpoint "
            "cmd=%s attempt=%s (remains PENDING)",
            command_id,
            attempt_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="CHECKPOINT_REQUEST",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=attempt_id,
            )
        raise

    cmd_state = cmd_result["state"]
    resp_payload = {
        "command_id": command_id,
        "command_type": "REQUEST_CHECKPOINT",
        "command_state": cmd_state,
        "target_type": "ATTEMPT",
        "target_id": attempt_id,
        "attempt_id": attempt_id,
    }
    _handle_command_outcome(
        db_module,
        cmd_result=cmd_result,
        command_id=command_id,
        target_id=attempt_id,
        scope="CHECKPOINT_REQUEST",
        effective_key=effective_key,
        success_response_payload=resp_payload,
        default_reject_code="COMMAND_REJECTED",
    )
    with db_module.transaction() as conn:
        cmd_row = command_repository.get_command(conn, command_id) or cmd_row

    if isinstance(cmd_row, dict):
        cmd_row = {**cmd_row, "command_state": cmd_state, "state": cmd_state}
    return cmd_row
