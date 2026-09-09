"""Checkpoint repository — PostgreSQL data access for the checkpoints table.

DB only stores checkpoint index/metadata.
Actual checkpoint bytes reside on the Runtime filesystem.
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


def create_checkpoint(
    conn: psycopg.Connection,
    *,
    checkpoint_id: str,
    created_by_attempt_id: str,
    source_operation_id: int,
    source_step_id: int | None = None,
    model_version: int,
    recovery_cursor_jsonb: dict,
    epoch: int | None = None,
    next_batch_ordinal: int | None = None,
    contract_hash: str | None = None,
    dataset_build_id: str | None = None,
    dataset_manifest_hash: str | None = None,
    parameter_manifest_hash: str | None = None,
    checkpoint_policy: str,
    checkpoint_policy_version: int,
    created_at: datetime,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO checkpoints (
                checkpoint_id, created_by_attempt_id, source_operation_id,
                source_step_id, state, model_version, recovery_cursor_jsonb,
                epoch, next_batch_ordinal, contract_hash,
                dataset_build_id, dataset_manifest_hash, parameter_manifest_hash,
                checkpoint_policy, checkpoint_policy_version, created_at
            ) VALUES (
                %s, %s, %s, %s, 'WRITING', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (checkpoint_id) DO NOTHING
            RETURNING *
            """,
            (
                checkpoint_id,
                created_by_attempt_id,
                source_operation_id,
                source_step_id,
                model_version,
                json.dumps(recovery_cursor_jsonb),
                epoch,
                next_batch_ordinal,
                contract_hash,
                dataset_build_id,
                dataset_manifest_hash,
                parameter_manifest_hash,
                checkpoint_policy,
                checkpoint_policy_version,
                created_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT * FROM checkpoints WHERE checkpoint_id = %s", (checkpoint_id,))
            row = cur.fetchone()
    return _row_to_dict(row)


def complete_checkpoint(
    conn: psycopg.Connection,
    checkpoint_id: str,
    *,
    model_path: str,
    metadata_path: str,
    model_sha256: str,
    metadata_sha256: str,
    artifact_size_bytes: int,
    completed_at: datetime,
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE checkpoints
            SET state = 'COMPLETE',
                model_path = %s,
                metadata_path = %s,
                model_sha256 = %s,
                metadata_sha256 = %s,
                artifact_size_bytes = %s,
                completed_at = %s
            WHERE checkpoint_id = %s AND state = 'WRITING'
            RETURNING *
            """,
            (
                model_path,
                metadata_path,
                model_sha256,
                metadata_sha256,
                artifact_size_bytes,
                completed_at,
                checkpoint_id,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def fail_checkpoint(conn: psycopg.Connection, checkpoint_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE checkpoints SET state = 'FAILED'
            WHERE checkpoint_id = %s AND state = 'WRITING'
            RETURNING *
            """,
            (checkpoint_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_checkpoint(conn: psycopg.Connection, checkpoint_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM checkpoints WHERE checkpoint_id = %s", (checkpoint_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_checkpoints(
    conn: psycopg.Connection,
    *,
    attempt_id: str | None = None,
    job_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    conditions = []
    params: list[Any] = []

    if attempt_id:
        conditions.append("created_by_attempt_id = %s")
        params.append(attempt_id)
    if job_id:
        # Join via attempts
        conditions.append(
            "created_by_attempt_id IN (SELECT attempt_id FROM attempts WHERE job_id = %s)"
        )
        params.append(job_id)
    if state:
        conditions.append("state = %s")
        params.append(state)

    if cursor:
        try:
            ts_str, cid = cursor.split("|", 1)
            conditions.append("(created_at, checkpoint_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, cid])
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    sql = f"""
        SELECT c.*,
            a.job_id
        FROM checkpoints c
        JOIN attempts a ON c.created_by_attempt_id = a.attempt_id
        {where}
        ORDER BY c.created_at DESC, c.checkpoint_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def get_latest_complete_for_attempt(conn: psycopg.Connection, attempt_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM checkpoints
            WHERE created_by_attempt_id = %s AND state = 'COMPLETE'
            ORDER BY model_version DESC
            LIMIT 1
            """,
            (attempt_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None
