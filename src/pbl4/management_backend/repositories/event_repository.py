"""Event repository — PostgreSQL data access for the events table.

Deduplication: unique index on (attempt_id, runtime_event_seq) for runtime events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def insert_event(
    conn: psycopg.Connection,
    *,
    event_type: str,
    scope_type: str,
    severity: str,
    occurred_at: datetime,
    persisted_at: datetime,
    attempt_id: str | None = None,
    runtime_event_seq: int | None = None,
    source_component: str = "Management",
    scope_id: str | None = None,
    payload: dict | None = None,
) -> dict | None:
    """Insert a runtime/management event. Returns None if deduplication skips it."""
    payload = payload or {}
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO events (
                    attempt_id, runtime_event_seq, event_type,
                    source_component, scope_type, scope_id, severity,
                    payload_jsonb, occurred_at, persisted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (attempt_id, runtime_event_seq)
                    WHERE attempt_id IS NOT NULL AND runtime_event_seq IS NOT NULL
                DO NOTHING
                RETURNING *
                """,
                (
                    attempt_id,
                    runtime_event_seq,
                    event_type,
                    source_component,
                    scope_type,
                    scope_id,
                    severity,
                    json.dumps(payload),
                    occurred_at,
                    persisted_at,
                ),
            )
            row = cur.fetchone()
    except psycopg.errors.UniqueViolation:
        logger.debug("Duplicate event skipped: attempt_id=%s seq=%s", attempt_id, runtime_event_seq)
        return None
    return _row_to_dict(row) if row else None


def get_event_by_seq(
    conn: psycopg.Connection, attempt_id: str, runtime_event_seq: int
) -> dict | None:
    """Fetch an event for an attempt by its runtime_event_seq."""
    sql = "SELECT * FROM events WHERE attempt_id = %s AND runtime_event_seq = %s"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (attempt_id, runtime_event_seq))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_latest_runtime_event_seq(conn: psycopg.Connection, attempt_id: str) -> int | None:
    """Fetch the maximum runtime_event_seq recorded for an attempt."""
    sql = "SELECT MAX(runtime_event_seq) FROM events WHERE attempt_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (attempt_id,))
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def list_events_after_seq(
    conn: psycopg.Connection, attempt_id: str, after_seq: int, limit: int = 500
) -> list[dict]:
    """Fetch runtime events for an attempt with seq strictly greater than after_seq, ascending."""
    sql = """
        SELECT * FROM events
        WHERE attempt_id = %s AND runtime_event_seq > %s
        ORDER BY runtime_event_seq ASC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (attempt_id, after_seq, limit))
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def list_events(
    conn: psycopg.Connection,
    *,
    attempt_id: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    after_seq: int | None = None,
    runtime_only: bool = False,
) -> list[dict]:
    conditions = []
    params: list[Any] = []

    if attempt_id:
        conditions.append("attempt_id = %s")
        params.append(attempt_id)
    if scope_type:
        conditions.append("scope_type = %s")
        params.append(scope_type)
    if scope_id:
        conditions.append("scope_id = %s")
        params.append(scope_id)
    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if severity:
        conditions.append("severity = %s")
        params.append(severity)
    if after_seq is not None:
        conditions.append("runtime_event_seq > %s")
        params.append(after_seq)
    if runtime_only:
        conditions.append("runtime_event_seq IS NOT NULL")

    if cursor:
        try:
            event_id = int(cursor)
            conditions.append("event_id < %s")
            params.append(event_id)
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    order_clause = (
        "ORDER BY runtime_event_seq ASC"
        if after_seq is not None or runtime_only
        else "ORDER BY event_id DESC"
    )

    sql = f"""
        SELECT * FROM events
        {where}
        {order_clause}
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]
