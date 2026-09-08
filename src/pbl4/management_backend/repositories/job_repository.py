"""Job repository — PostgreSQL data access for the jobs table.

All SQL is explicit and parameterized. No ORM, no SQLAlchemy.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Valid job states
JOB_STATES = {"DRAFT", "READY", "ARCHIVED"}

# Active attempt states (for counting)
ACTIVE_ATTEMPT_STATES = {
    "CREATED",
    "WAITING_WORKERS",
    "PROVISIONING",
    "INITIALIZING",
    "RUNNING",
    "COMPLETING",
}


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_job(
    conn: psycopg.Connection,
    *,
    job_id: str,
    display_name: str,
    description: str,
    requested_contract: dict,
    created_at: datetime,
) -> dict:
    """Insert a new DRAFT job and return the full row."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO jobs
                (job_id, display_name, description, state, requested_contract, created_at)
            VALUES
                (%s, %s, %s, 'DRAFT', %s, %s)
            RETURNING *
            """,
            (job_id, display_name, description, json.dumps(requested_contract), created_at),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_job(conn: psycopg.Connection, job_id: str) -> dict | None:
    """Fetch a job by job_id. Returns None if not found."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(
    conn: psycopg.Connection,
    *,
    state: str | None = None,
    dataset_build_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    """List jobs with optional filtering and cursor-based pagination.

    Stable sort: created_at DESC, job_id DESC.
    Cursor encodes (created_at, job_id) as 'ISO|job_id'.
    """
    conditions = []
    params: list[Any] = []

    if state:
        conditions.append("state = %s")
        params.append(state)

    if dataset_build_id:
        conditions.append("requested_contract->>'dataset_build_id' = %s")
        params.append(dataset_build_id)

    if q:
        conditions.append(
            "(LOWER(display_name) LIKE LOWER(%s) OR LOWER(description) LIKE LOWER(%s))"
        )
        like = f"%{q}%"
        params.extend([like, like])

    if cursor:
        try:
            ts_str, cid = cursor.split("|", 1)
            conditions.append("(created_at, job_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, cid])
        except ValueError:
            pass  # ignore malformed cursor

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    sql = f"""
        SELECT j.*,
            (SELECT COUNT(*) FROM attempts a WHERE a.job_id = j.job_id) AS attempt_count,
            (SELECT a.attempt_id FROM attempts a
             WHERE a.job_id = j.job_id ORDER BY a.created_at DESC LIMIT 1) AS latest_attempt_id,
            (SELECT a.state FROM attempts a
             WHERE a.job_id = j.job_id ORDER BY a.created_at DESC LIMIT 1) AS latest_attempt_state
        FROM jobs j
        {where}
        ORDER BY j.created_at DESC, j.job_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def update_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    requested_contract: dict | None = None,
) -> dict | None:
    """Partial update a DRAFT job's metadata/contract fields."""
    sets = []
    params: list[Any] = []

    if display_name is not None:
        sets.append("display_name = %s")
        params.append(display_name)
    if description is not None:
        sets.append("description = %s")
        params.append(description)
    if requested_contract is not None:
        sets.append("requested_contract = %s")
        params.append(json.dumps(requested_contract))

    if not sets:
        return get_job(conn, job_id)

    params.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = %s RETURNING *"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def freeze_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    resolved_contract: dict,
    contract_hash: str,
    frozen_at: datetime,
) -> dict | None:
    """Set a job to READY with resolved_contract, contract_hash, frozen_at atomically."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE jobs
            SET state = 'READY',
                resolved_contract = %s,
                contract_hash = %s,
                frozen_at = %s
            WHERE job_id = %s AND state = 'DRAFT'
            RETURNING *
            """,
            (json.dumps(resolved_contract), contract_hash, frozen_at, job_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def archive_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    archived_at: datetime,
) -> dict | None:
    """Set a job to ARCHIVED."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE jobs
            SET state = 'ARCHIVED', archived_at = %s
            WHERE job_id = %s AND state IN ('DRAFT', 'READY')
            RETURNING *
            """,
            (archived_at, job_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def count_attempts(conn: psycopg.Connection, job_id: str) -> int:
    """Count total attempts for a job."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM attempts WHERE job_id = %s", (job_id,))
        return cur.fetchone()[0]
