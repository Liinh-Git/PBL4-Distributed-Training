"""Worker Session repository — PostgreSQL data access for worker_sessions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def upsert_session(
    conn: psycopg.Connection,
    *,
    session_id: int,
    attempt_id: str,
    worker_id: int,
    node_label: str,
    protocol_version: int,
    state: str,
    connected_at: datetime,
    last_heartbeat_at: datetime | None = None,
    disconnected_at: datetime | None = None,
    failure_code: str | None = None,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO worker_sessions (
                session_id, attempt_id, worker_id, node_label,
                protocol_version, state, connected_at,
                last_heartbeat_at, disconnected_at, failure_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                state = EXCLUDED.state,
                last_heartbeat_at = COALESCE(
                    EXCLUDED.last_heartbeat_at, worker_sessions.last_heartbeat_at
                ),
                disconnected_at = COALESCE(
                    EXCLUDED.disconnected_at, worker_sessions.disconnected_at
                ),
                failure_code = COALESCE(
                    EXCLUDED.failure_code, worker_sessions.failure_code
                )
            RETURNING *
            """,
            (
                session_id,
                attempt_id,
                worker_id,
                node_label,
                protocol_version,
                state,
                connected_at,
                last_heartbeat_at,
                disconnected_at,
                failure_code,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_sessions_for_attempt(
    conn: psycopg.Connection,
    attempt_id: str,
    *,
    active_only: bool = False,
) -> list[dict]:
    """Return all worker sessions for an attempt, optionally filtered to active only."""
    params: list[Any] = [attempt_id]
    extra = ""
    if active_only:
        extra = "AND state NOT IN ('DISCONNECTED', 'FAILED')"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT * FROM worker_sessions
            WHERE attempt_id = %s {extra}
            ORDER BY worker_id ASC, connected_at DESC
            """,
            params,
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def get_active_session_for_worker(
    conn: psycopg.Connection,
    attempt_id: str,
    worker_id: int,
) -> dict | None:
    """Return the single active session for a given worker rank."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM worker_sessions
            WHERE attempt_id = %s AND worker_id = %s
              AND state NOT IN ('DISCONNECTED', 'FAILED')
            LIMIT 1
            """,
            (attempt_id, worker_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_sessions_for_worker(
    conn: psycopg.Connection,
    attempt_id: str,
    worker_id: int,
) -> list[dict]:
    """Return all sessions (including historical) for a given worker rank."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM worker_sessions
            WHERE attempt_id = %s AND worker_id = %s
            ORDER BY connected_at DESC
            """,
            (attempt_id, worker_id),
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]
