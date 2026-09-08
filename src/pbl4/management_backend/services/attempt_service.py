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

import psycopg
import psycopg.errors

from pbl4.management_backend.repositories import (
    attempt_repository,
    checkpoint_repository,
    command_repository,
    event_repository,
    job_repository,
    step_repository,
    worker_session_repository,
)
from pbl4.management_backend.services import job_service

logger = logging.getLogger(__name__)


class AttemptNotFoundError(Exception):
    pass


class AttemptStateError(Exception):
    def __init__(self, msg: str, current_state: str = "") -> None:
        super().__init__(msg)
        self.current_state = current_state


class AttemptConflictError(Exception):
    """Raised when a new attempt would violate the single-active invariant."""

    pass


class JobNotReadyError(Exception):
    pass


def _new_attempt_id() -> str:
    return f"atm_{uuid.uuid4().hex[:12]}"


def _new_command_id() -> str:
    return str(uuid.uuid4())


# ─── Start / Retry / Resume ──────────────────────────────────────────────────


def start_job(
    conn: psycopg.Connection, job_id: str, note: str | None = None
) -> tuple[dict, dict]:
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

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="START_ATTEMPT",
        target_type="ATTEMPT",
        target_id=attempt_id,
        request={
            "job_id": job_id,
            "attempt_id": attempt_id,
            "execution_mode": "FRESH",
            "note": note,
        },
        requested_at=now,
    )

    try:
        with conn.savepoint():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="FRESH",
                created_at=now,
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

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="START_ATTEMPT",
        target_type="ATTEMPT",
        target_id=attempt_id,
        request={
            "job_id": job_id,
            "attempt_id": attempt_id,
            "execution_mode": "RETRY_FROM_START",
        },
        requested_at=now,
    )

    try:
        with conn.savepoint():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="RETRY_FROM_START",
                created_at=now,
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
        raise AttemptStateError(f"Checkpoint '{checkpoint_id}' is not COMPLETE.")
    if ckpt["contract_hash"] != job["contract_hash"]:
        raise AttemptStateError("Checkpoint contract_hash does not match job contract_hash.")

    active = attempt_repository.get_active_attempt(conn)
    if active:
        raise AttemptConflictError(
            f"Active attempt '{active['attempt_id']}' is running. Abort before resuming."
        )

    attempt_id = _new_attempt_id()
    command_id = _new_command_id()
    now = datetime.now(UTC)

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="START_ATTEMPT",
        target_type="ATTEMPT",
        target_id=attempt_id,
        request={
            "job_id": job_id,
            "attempt_id": attempt_id,
            "execution_mode": "RESUME",
            "checkpoint_id": checkpoint_id,
        },
        requested_at=now,
    )

    try:
        with conn.savepoint():
            attempt_row = attempt_repository.create_attempt(
                conn,
                attempt_id=attempt_id,
                job_id=job_id,
                contract_hash=job["contract_hash"],
                execution_mode="RESUME",
                resume_from_checkpoint_id=checkpoint_id,
                created_at=now,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise AttemptConflictError(
            f"Active attempt already running for job '{job_id}' (V1: only one active at a time)."
        ) from exc

    logger.info(
        "Resume attempt created: %s (job=%s, ckpt=%s)", attempt_id, job_id, checkpoint_id
    )
    return attempt_row, cmd_row


# ─── Query ───────────────────────────────────────────────────────────────────


def get_attempt(conn: psycopg.Connection, attempt_id: str) -> dict:
    row = attempt_repository.get_attempt(conn, attempt_id)
    if row is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")
    return row


def list_attempts(
    conn: psycopg.Connection,
    *,
    job_id: str | None = None,
    state: str | None = None,
    execution_mode: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    return attempt_repository.list_attempts(
        conn,
        job_id=job_id,
        state=state,
        execution_mode=execution_mode,
        limit=limit,
        cursor=cursor,
    )


def get_attempt_snapshot(conn: psycopg.Connection, attempt_id: str) -> dict:
    """Return a management-plane snapshot of the attempt.

    Note: stale=True because this is a DB projection, not a live runtime query.
    A live snapshot would require an MCP/1 STATE_SNAPSHOT request.
    """
    row = attempt_repository.get_attempt(conn, attempt_id)
    if row is None:
        raise AttemptNotFoundError(f"Attempt '{attempt_id}' not found.")

    sessions = worker_session_repository.get_sessions_for_attempt(conn, attempt_id)
    latest_ckpt = checkpoint_repository.get_latest_complete_for_attempt(conn, attempt_id)

    metadata = row.get("runtime_metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

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
        "observed_at": None,
        "runtime_event_seq": None,
    }
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
        raise AttemptStateError(
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
        request={"attempt_id": attempt_id, "reason": reason},
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
        request={"attempt_id": attempt_id, "reason": reason},
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
    # Runtime gateway not connected — return None (stale)
    return None
