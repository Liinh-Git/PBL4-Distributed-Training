"""Dataset repository — PostgreSQL data access for the datasets table."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_dataset(
    conn: psycopg.Connection,
    *,
    dataset_id: str,
    name: str,
    task_type: str,
    source_type: str,
    source_reference: str,
    created_at: datetime,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO datasets
                (dataset_id, name, task_type, source_type, source_reference, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (dataset_id, name, task_type, source_type, source_reference, created_at),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_dataset(conn: psycopg.Connection, dataset_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM datasets WHERE dataset_id = %s", (dataset_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_datasets(
    conn: psycopg.Connection,
    *,
    task_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    """List datasets with optional filters and cursor pagination (created_at DESC, dataset_id DESC)."""
    conditions = []
    params: list[Any] = []

    if task_type:
        conditions.append("task_type = %s")
        params.append(task_type)

    if q:
        conditions.append(
            "(LOWER(dataset_id) LIKE LOWER(%s) OR LOWER(name) LIKE LOWER(%s))"
        )
        like = f"%{q}%"
        params.extend([like, like])

    if cursor:
        try:
            ts_str, did = cursor.split("|", 1)
            conditions.append("(created_at, dataset_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, did])
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    sql = f"""
        SELECT * FROM datasets
        {where}
        ORDER BY created_at DESC, dataset_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def get_build_counts_for_dataset(conn: psycopg.Connection, dataset_id: str) -> dict:
    """Return a count per state for all dataset builds of the given dataset."""
    all_states = [
        "CREATED", "QUEUED", "IMPORTING", "VALIDATING", "PREPROCESSING",
        "MATERIALIZING", "VERIFYING", "REGISTERING", "READY", "FAILED",
        "DEPRECATED", "DELETING", "DELETED",
    ]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT state, COUNT(*) FROM dataset_builds
            WHERE dataset_id = %s
            GROUP BY state
            """,
            (dataset_id,),
        )
        rows = cur.fetchall()

    counts = {s: 0 for s in all_states}
    for state, cnt in rows:
        if state in counts:
            counts[state] = int(cnt)
    return counts
