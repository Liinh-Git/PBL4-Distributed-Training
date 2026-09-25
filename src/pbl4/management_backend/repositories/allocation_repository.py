"""Worker Allocation repository — PostgreSQL data access for worker_allocations table.

Enforces:
- Desired states: RUNNING, STOPPED.
- Actual states: REQUESTED, DISPATCHED, STARTED, ENDED, FAILED.
- Active actual states: REQUESTED, DISPATCHED, STARTED.
- At most one active worker allocation per node enforced at DB level via partial unique index.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DESIRED_STATE_RUNNING = "RUNNING"
DESIRED_STATE_STOPPED = "STOPPED"
VALID_DESIRED_STATES = {DESIRED_STATE_RUNNING, DESIRED_STATE_STOPPED}

ACTUAL_STATE_REQUESTED = "REQUESTED"
ACTUAL_STATE_DISPATCHED = "DISPATCHED"
ACTUAL_STATE_STARTED = "STARTED"
ACTUAL_STATE_ENDED = "ENDED"
ACTUAL_STATE_FAILED = "FAILED"

VALID_ACTUAL_STATES = {
    ACTUAL_STATE_REQUESTED,
    ACTUAL_STATE_DISPATCHED,
    ACTUAL_STATE_STARTED,
    ACTUAL_STATE_ENDED,
    ACTUAL_STATE_FAILED,
}

ACTIVE_ACTUAL_STATES = {
    ACTUAL_STATE_REQUESTED,
    ACTUAL_STATE_DISPATCHED,
    ACTUAL_STATE_STARTED,
}
TERMINAL_ACTUAL_STATES = {ACTUAL_STATE_ENDED, ACTUAL_STATE_FAILED}


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_allocation(
    conn: psycopg.Connection,
    *,
    allocation_id: str,
    attempt_id: str,
    node_id: str,
    desired_state: str = DESIRED_STATE_RUNNING,
    actual_state: str = ACTUAL_STATE_REQUESTED,
    device: str,
    runtime_endpoint: str,
    created_at: datetime,
    resource_allocation_jsonb: dict[str, Any] | str | None = None,
) -> dict:
    """Create a new worker allocation record."""
    if desired_state not in VALID_DESIRED_STATES:
        raise ValueError(f"Invalid desired_state '{desired_state}'")
    if actual_state not in VALID_ACTUAL_STATES:
        raise ValueError(f"Invalid actual_state '{actual_state}'")

    res_str = (
        resource_allocation_jsonb
        if isinstance(resource_allocation_jsonb, str)
        else json.dumps(resource_allocation_jsonb or {})
    )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO worker_allocations (
                allocation_id, attempt_id, node_id, desired_state, actual_state,
                device, runtime_endpoint, created_at, resource_allocation_jsonb
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING *
            """,
            (
                allocation_id,
                attempt_id,
                node_id,
                desired_state,
                actual_state,
                device,
                runtime_endpoint,
                created_at,
                res_str,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_allocation(conn: psycopg.Connection, allocation_id: str) -> dict | None:
    """Retrieve an allocation by its allocation_id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM worker_allocations WHERE allocation_id = %s",
            (allocation_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_for_attempt(
    conn: psycopg.Connection,
    attempt_id: str,
    *,
    active_only: bool = False,
) -> list[dict]:
    """List allocations belonging to a specific training attempt."""
    query = "SELECT * FROM worker_allocations WHERE attempt_id = %s"
    params: list[Any] = [attempt_id]

    if active_only:
        query += " AND actual_state IN ('REQUESTED', 'DISPATCHED', 'STARTED')"

    query += " ORDER BY created_at ASC"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def list_active(
    conn: psycopg.Connection,
    *,
    node_id: str | None = None,
) -> list[dict]:
    """List all currently active allocations across nodes (or for a specific node)."""
    query = (
        "SELECT * FROM worker_allocations "
        "WHERE actual_state IN ('REQUESTED', 'DISPATCHED', 'STARTED')"
    )
    params: list[Any] = []

    if node_id:
        query += " AND node_id = %s"
        params.append(node_id)

    query += " ORDER BY created_at ASC"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def update_actual_state(
    conn: psycopg.Connection,
    allocation_id: str,
    actual_state: str,
    *,
    dispatched_at: datetime | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> dict | None:
    """Apply one canonical allocation transition atomically.

    The source-state predicate prevents delayed Agent events from reviving a
    terminal allocation and closes the check/update race at the database.
    """
    if actual_state not in VALID_ACTUAL_STATES:
        raise ValueError(f"Invalid actual_state '{actual_state}'")

    allowed_from = {
        ACTUAL_STATE_DISPATCHED: (ACTUAL_STATE_REQUESTED,),
        ACTUAL_STATE_STARTED: (ACTUAL_STATE_DISPATCHED,),
        ACTUAL_STATE_ENDED: (ACTUAL_STATE_STARTED,),
        ACTUAL_STATE_FAILED: (
            ACTUAL_STATE_REQUESTED,
            ACTUAL_STATE_DISPATCHED,
            ACTUAL_STATE_STARTED,
        ),
    }.get(actual_state)
    if allowed_from is None:
        raise ValueError(f"No transition may target actual_state '{actual_state}'")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE worker_allocations
            SET actual_state = %s,
                dispatched_at = COALESCE(%s, dispatched_at),
                started_at = COALESCE(%s, started_at),
                ended_at = COALESCE(%s, ended_at),
                failure_code = COALESCE(%s, failure_code),
                failure_message = COALESCE(%s, failure_message)
            WHERE allocation_id = %s
              AND actual_state = ANY(%s)
            RETURNING *
            """,
            (
                actual_state,
                dispatched_at,
                started_at,
                ended_at,
                failure_code,
                failure_message,
                allocation_id,
                list(allowed_from),
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_desired_state(
    conn: psycopg.Connection,
    allocation_id: str,
    desired_state: str,
) -> dict | None:
    """Update desired_state (RUNNING, STOPPED)."""
    if desired_state not in VALID_DESIRED_STATES:
        raise ValueError(f"Invalid desired_state '{desired_state}'")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE worker_allocations
            SET desired_state = %s
            WHERE allocation_id = %s
            RETURNING *
            """,
            (desired_state, allocation_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def terminal_update(
    conn: psycopg.Connection,
    allocation_id: str,
    actual_state: str,
    *,
    ended_at: datetime,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> dict | None:
    """Helper to transition an allocation to a terminal state (ENDED or FAILED)."""
    if actual_state not in TERMINAL_ACTUAL_STATES:
        raise ValueError(
            f"Terminal state must be one of {TERMINAL_ACTUAL_STATES}, got '{actual_state}'"
        )

    return update_actual_state(
        conn,
        allocation_id,
        actual_state,
        ended_at=ended_at,
        failure_code=failure_code,
        failure_message=failure_message,
    )
