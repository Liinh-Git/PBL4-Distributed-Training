"""Job Service — business logic for training job registration and lifecycle.

State machine:
  DRAFT → READY (freeze: validate + resolve contract)
  DRAFT/READY → ARCHIVED

V1 invariants:
  - A READY job must have resolved_contract, contract_hash, and frozen_at set atomically.
  - Only DRAFT jobs may be updated.
  - A READY job may have active Attempts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

import psycopg

from pbl4.management_backend.repositories import (
    attempt_repository,
    job_repository,
)
from pbl4.management_backend.services import contract_resolver

logger = logging.getLogger(__name__)


class JobNotFoundError(Exception):
    pass


class JobStateError(Exception):
    """Raised when a requested state transition is invalid."""

    def __init__(self, msg: str, current_state: str = "") -> None:
        super().__init__(msg)
        self.current_state = current_state


class JobValidationError(Exception):
    """Raised when contract or field validation fails."""

    def __init__(self, msg: str, errors: list[str] | None = None) -> None:
        super().__init__(msg)
        self.errors = errors or [msg]


def _new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


def _canonical_json(d: dict) -> str:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_contract(resolved: dict) -> str:
    """SHA-256 of the canonical resolved contract."""
    return hashlib.sha256(_canonical_json(resolved).encode()).hexdigest()


def _validate_contract(requested_contract: dict) -> list[str]:
    """Basic contract validation. Returns list of error messages (empty = valid)."""
    errors = []
    required_fields = [
        "dataset_build_id",
        "model_id",
        "epochs",
        "learning_rate",
        "training_seed",
        "training_strategy",
    ]
    for field in required_fields:
        if field not in requested_contract or requested_contract[field] is None:
            errors.append(f"Missing required contract field: '{field}'")

    strategy = requested_contract.get("training_strategy", "")
    if strategy and strategy != "strict_bsp":
        errors.append(
            f"Unsupported training strategy: '{strategy}'. V1 only supports 'strict_bsp'."
        )

    epochs = requested_contract.get("epochs")
    if epochs is not None and (not isinstance(epochs, int) or epochs < 1):
        errors.append("epochs must be a positive integer.")

    lr = requested_contract.get("learning_rate")
    if lr is not None and (not isinstance(lr, (int, float)) or lr <= 0):
        errors.append("learning_rate must be a positive number.")

    return errors


def _resolve_contract(conn: psycopg.Connection, requested_contract: dict) -> dict:
    """Delegate to contract_resolver.resolve for canonical resolution logic."""
    try:
        return contract_resolver.resolve(conn, requested_contract)
    except contract_resolver.ContractResolutionError as e:
        raise JobValidationError(str(e), e.errors) from e


# ─── Service API ─────────────────────────────────────────────────────────────


def create_job(
    conn: psycopg.Connection,
    *,
    display_name: str,
    description: str,
    requested_contract: dict,
) -> dict:
    errors = _validate_contract(requested_contract)
    if errors:
        raise JobValidationError("Contract validation failed", errors)

    job_id = _new_job_id()
    now = datetime.now(UTC)
    row = job_repository.create_job(
        conn,
        job_id=job_id,
        display_name=display_name,
        description=description,
        requested_contract=requested_contract,
        created_at=now,
    )
    logger.info("Job created: %s (state=DRAFT)", job_id)
    return row


def get_job(conn: psycopg.Connection, job_id: str) -> dict:
    row = job_repository.get_job(conn, job_id)
    if row is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    return row


def list_jobs(
    conn: psycopg.Connection,
    *,
    state: str | None = None,
    dataset_build_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    return job_repository.list_jobs(
        conn,
        state=state,
        dataset_build_id=dataset_build_id,
        q=q,
        limit=limit,
        cursor=cursor,
    )


def update_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    requested_contract: dict | None = None,
) -> dict:
    current = job_repository.get_job(conn, job_id)
    if current is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    if current["state"] != "DRAFT":
        raise JobStateError(
            f"Job '{job_id}' is in state '{current['state']}'; only DRAFT jobs may be updated.",
            current_state=current["state"],
        )
    if requested_contract is not None:
        errors = _validate_contract(requested_contract)
        if errors:
            raise JobValidationError("Contract validation failed", errors)

    row = job_repository.update_job(
        conn,
        job_id,
        display_name=display_name,
        description=description,
        requested_contract=requested_contract,
    )
    if row is None:
        raise JobNotFoundError(f"Job '{job_id}' not found after update.")
    return row


def validate_job(conn: psycopg.Connection, job_id: str) -> dict:
    """Validate the job contract against current catalog. Does NOT transition state."""
    current = job_repository.get_job(conn, job_id)
    if current is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")

    rc = current["requested_contract"]
    if isinstance(rc, str):
        rc = json.loads(rc)

    errors = _validate_contract(rc)
    resolved_preview = None
    warnings = []

    if not errors:
        try:
            resolved_preview = _resolve_contract(conn, rc)
        except JobValidationError as e:
            errors.extend(e.errors)

    return {
        "requested_contract": rc,
        "resolved_preview": resolved_preview,
        "warnings": warnings,
        "errors": errors,
    }


def freeze_job(conn: psycopg.Connection, job_id: str) -> dict:
    """Validate + freeze a DRAFT job to READY state.

    Atomically sets resolved_contract, contract_hash, and frozen_at + state=READY.
    """
    current = job_repository.get_job(conn, job_id)
    if current is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    if current["state"] != "DRAFT":
        raise JobStateError(
            f"Job '{job_id}' is '{current['state']}'; only DRAFT jobs may be frozen.",
            current_state=current["state"],
        )

    rc = current["requested_contract"]
    if isinstance(rc, str):
        rc = json.loads(rc)

    errors = _validate_contract(rc)
    if errors:
        raise JobValidationError("Contract validation failed before freeze", errors)

    resolved = _resolve_contract(conn, rc)
    contract_hash = _hash_contract(resolved)
    now = datetime.now(UTC)

    row = job_repository.freeze_job(
        conn,
        job_id,
        resolved_contract=resolved,
        contract_hash=contract_hash,
        frozen_at=now,
    )
    if row is None:
        raise JobStateError(
            f"Job '{job_id}' could not be frozen (race condition or not DRAFT).",
            current_state=current["state"],
        )
    logger.info("Job frozen: %s (hash=%s)", job_id, contract_hash[:8])
    return row


def clone_job(conn: psycopg.Connection, job_id: str, *, display_name: str | None = None) -> dict:
    """Create a new DRAFT job cloned from an existing job's requested_contract."""
    source = job_repository.get_job(conn, job_id)
    if source is None:
        raise JobNotFoundError(f"Source job '{job_id}' not found.")

    rc = source["requested_contract"]
    if isinstance(rc, str):
        rc = json.loads(rc)

    new_job_id = _new_job_id()
    now = datetime.now(UTC)
    new_display_name = display_name or f"Clone of {source['display_name']}"

    row = job_repository.create_job(
        conn,
        job_id=new_job_id,
        display_name=new_display_name,
        description=source.get("description", ""),
        requested_contract=rc,
        created_at=now,
    )
    # Patch cloned_from_job_id (create_job doesn't set it)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET cloned_from_job_id = %s WHERE job_id = %s",
            (job_id, new_job_id),
        )
    row = job_repository.get_job(conn, new_job_id)
    logger.info("Job cloned: %s → %s", job_id, new_job_id)
    return row


def archive_job(conn: psycopg.Connection, job_id: str) -> dict:
    """Archive a DRAFT or READY job (no active attempts allowed for READY)."""
    current = job_repository.get_job(conn, job_id)
    if current is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    if current["state"] not in ("DRAFT", "READY"):
        raise JobStateError(
            f"Job '{job_id}' is '{current['state']}'; only DRAFT/READY may be archived.",
            current_state=current["state"],
        )

    # Check for active attempts
    active = attempt_repository.get_active_attempt(conn)
    if active and active.get("job_id") == job_id:
        raise JobStateError(
            f"Job '{job_id}' has an active attempt '{active['attempt_id']}'; stop it before archiving.",
            current_state=current["state"],
        )

    now = datetime.now(UTC)
    row = job_repository.archive_job(conn, job_id, archived_at=now)
    if row is None:
        raise JobStateError(
            f"Job '{job_id}' could not be archived.",
            current_state=current["state"],
        )
    logger.info("Job archived: %s", job_id)
    return row
