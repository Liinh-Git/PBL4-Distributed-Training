"""Node Enrollment repository — PostgreSQL data access for node_enrollment_codes table.

Enforces:
- Invariant: A code is only usable when used_at IS NULL and now < expires_at.
- Atomic one-time consumption via single conditional UPDATE statement.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_enrollment_code(
    conn: psycopg.Connection,
    *,
    code_hash: str,
    created_at: datetime,
    expires_at: datetime,
) -> dict:
    """Insert a new one-time enrollment code hash."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO node_enrollment_codes (code_hash, created_at, expires_at)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (code_hash, created_at, expires_at),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def consume_code_if_valid(
    conn: psycopg.Connection,
    *,
    code_hash: str,
    now: datetime | None = None,
) -> dict | None:
    """Atomically consume an enrollment code if valid and not expired.

    Guarantees race-free one-time consumption via a single atomic UPDATE statement:
    UPDATE node_enrollment_codes
    SET used_at = now
    WHERE code_hash = %s AND used_at IS NULL AND expires_at > now
    RETURNING *
    """
    check_time = now or datetime.now(UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE node_enrollment_codes
            SET used_at = %s
            WHERE code_hash = %s
              AND used_at IS NULL
              AND expires_at > %s
            RETURNING *
            """,
            (check_time, code_hash, check_time),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_enrollment_code(conn: psycopg.Connection, code_hash: str) -> dict | None:
    """Retrieve an enrollment code row by code_hash."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM node_enrollment_codes WHERE code_hash = %s",
            (code_hash,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def delete_enrollment_code(conn: psycopg.Connection, code_hash: str) -> bool:
    """Delete an enrollment code row (primarily for test cleanup)."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM node_enrollment_codes WHERE code_hash = %s",
            (code_hash,),
        )
        return cur.rowcount > 0
