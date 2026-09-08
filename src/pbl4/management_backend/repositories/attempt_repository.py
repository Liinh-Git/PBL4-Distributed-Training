"""Attempt repository — PostgreSQL data access for the attempts table."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

ACTIVE_ATTEMPT_STATES = {
    "CREATED", "WAITING_WORKERS", "PROVISIONING",
    "INITIALIZING", "RUNNING", "COMPLETING",
}
ABORTABLE_ATTEMPT_STATES = {
    "CREATED", "WAITING_WORKERS", "PROVISIONING",
    "INITIALIZING", "RUNNING",
}
TERMINAL_ATTEMPT_STATES = {"COMPLETED", "FAILED", "ABORTED"}


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_attempt(
    conn: psycopg.Connection,
    *,
    attempt_id: str,
    job_id: str,
    contract_hash: str,
    execution_mode: str,
    resume_from_checkpoint_id: str | None = None,
    created_at: datetime,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, contract_hash, execution_mode,
                state, resume_from_checkpoint_id, created_at
            ) VALUES (%s, %s, %s, %s, 'CREATED', %s, %s)
            RETURNING *
            """,
            (
                attempt_id, job_id, contract_hash, execution_mode,
                resume_from_checkpoint_id, created_at,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_attempt(conn: psycopg.Connection, attempt_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM attempts WHERE attempt_id = %s", (attempt_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_attempts(
    conn: psycopg.Connection,
    *,
    job_id: str | None = None,
    state: str | None = None,
    execution_mode: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    conditions = []
    params: list[Any] = []

    if job_id:
        conditions.append("job_id = %s")
        params.append(job_id)
    if state:
        conditions.append("state = %s")
        params.append(state)
    if execution_mode:
        conditions.append("execution_mode = %s")
        params.append(execution_mode)

    if cursor:
        try:
            ts_str, aid = cursor.split("|", 1)
            conditions.append("(created_at, attempt_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, aid])
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    sql = f"""
        SELECT * FROM attempts
        {where}
        ORDER BY created_at DESC, attempt_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def update_attempt_state(
    conn: psycopg.Connection,
    attempt_id: str,
    new_state: str,
    *,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
    runtime_metadata: dict | None = None,
) -> dict | None:
    sets = ["state = %s"]
    params: list[Any] = [new_state]

    if started_at is not None:
        sets.append("started_at = %s")
        params.append(started_at)
    if ended_at is not None:
        sets.append("ended_at = %s")
        params.append(ended_at)
    if failure_code is not None:
        sets.append("failure_code = %s")
        params.append(failure_code)
    if failure_message is not None:
        sets.append("failure_message = %s")
        params.append(failure_message)
    if runtime_metadata is not None:
        sets.append("runtime_metadata = %s")
        params.append(json.dumps(runtime_metadata))

    params.append(attempt_id)
    sql = f"UPDATE attempts SET {', '.join(sets)} WHERE attempt_id = %s RETURNING *"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_active_attempt(conn: psycopg.Connection) -> dict | None:
    """Return the single active attempt if one exists, else None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM attempts
            WHERE state IN (
                'CREATED', 'WAITING_WORKERS', 'PROVISIONING',
                'INITIALIZING', 'RUNNING', 'COMPLETING'
            )
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None
