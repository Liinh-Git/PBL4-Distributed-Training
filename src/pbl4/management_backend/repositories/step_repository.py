"""Step repository — PostgreSQL data access for steps and worker_steps."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_step(
    conn: psycopg.Connection,
    *,
    attempt_id: str,
    step_id: int,
    operation_id: int,
    training_strategy: str,
    epoch: int,
    batch_ordinal: int,
    input_model_version: int,
    started_at: datetime,
    state: str = "CREATED",
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO steps (
                attempt_id, step_id, operation_id, training_strategy,
                epoch, batch_ordinal, input_model_version,
                state, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, step_id) DO UPDATE SET
                state = CASE
                    WHEN steps.state = 'CREATED' AND EXCLUDED.state != 'CREATED' THEN EXCLUDED.state
                    ELSE steps.state
                END
            RETURNING *
            """,
            (
                attempt_id,
                step_id,
                operation_id,
                training_strategy,
                epoch,
                batch_ordinal,
                input_model_version,
                state,
                started_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            # Already exists — fetch it
            cur.execute(
                "SELECT * FROM steps WHERE attempt_id = %s AND step_id = %s",
                (attempt_id, step_id),
            )
            row = cur.fetchone()
    return _row_to_dict(row)


def update_step(
    conn: psycopg.Connection,
    attempt_id: str,
    step_id: int,
    *,
    state: str | None = None,
    output_model_version: int | None = None,
    total_sample_count: int | None = None,
    synchronization_completed_at: datetime | None = None,
    update_completed_at: datetime | None = None,
    committed_at: datetime | None = None,
    aggregate_ms: float | None = None,
    optimizer_ms: float | None = None,
    broadcast_ms: float | None = None,
    checkpoint_ms: float | None = None,
) -> dict | None:
    sets = []
    params: list[Any] = []

    if state is not None:
        if state == "CHECKPOINTING":
            sets.append("state = CASE WHEN state = 'COMMITTED' THEN state ELSE %s END")
        else:
            sets.append("state = %s")
        params.append(state)
    if output_model_version is not None:
        sets.append("output_model_version = %s")
        params.append(output_model_version)
    if total_sample_count is not None:
        sets.append("total_sample_count = %s")
        params.append(total_sample_count)
    if synchronization_completed_at is not None:
        sets.append("synchronization_completed_at = %s")
        params.append(synchronization_completed_at)
    if update_completed_at is not None:
        sets.append("update_completed_at = %s")
        params.append(update_completed_at)
    if committed_at is not None:
        sets.append("committed_at = %s")
        params.append(committed_at)
    if aggregate_ms is not None:
        sets.append("aggregate_ms = %s")
        params.append(aggregate_ms)
    if optimizer_ms is not None:
        sets.append("optimizer_ms = %s")
        params.append(optimizer_ms)
    if broadcast_ms is not None:
        sets.append("broadcast_ms = %s")
        params.append(broadcast_ms)
    if checkpoint_ms is not None:
        sets.append("checkpoint_ms = %s")
        params.append(checkpoint_ms)

    if not sets:
        return get_step(conn, attempt_id, step_id)

    params.extend([attempt_id, step_id])
    sql = f"UPDATE steps SET {', '.join(sets)} WHERE attempt_id = %s AND step_id = %s RETURNING *"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_step(conn: psycopg.Connection, attempt_id: str, step_id: int) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT s.*,
                (
                    SELECT c.completed_at
                    FROM checkpoints c
                    WHERE c.created_by_attempt_id = s.attempt_id
                      AND c.source_step_id = s.step_id
                      AND c.state = 'COMPLETE'
                    ORDER BY c.model_version DESC
                    LIMIT 1
                ) AS checkpoint_completed_at
            FROM steps s
            WHERE s.attempt_id = %s AND s.step_id = %s
            """,
            (attempt_id, step_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_steps(
    conn: psycopg.Connection,
    attempt_id: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    params: list[Any] = [attempt_id]
    extra = ""
    if cursor:
        try:
            step_id = int(cursor)
            extra = "AND step_id < %s"
            params.append(step_id)
        except ValueError:
            pass

    params.append(limit)
    sql = f"""
        SELECT * FROM steps
        WHERE attempt_id = %s {extra}
        ORDER BY step_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def get_worker_steps(conn: psycopg.Connection, attempt_id: str, step_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM worker_steps
            WHERE attempt_id = %s AND step_id = %s
            ORDER BY worker_id ASC
            """,
            (attempt_id, step_id),
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_worker_step(
    conn: psycopg.Connection,
    *,
    attempt_id: str,
    step_id: int,
    worker_id: int,
    session_id: int,
    shard_id: int,
    batch_id: int,
    sample_count: int,
    loss: float | None = None,
    accuracy: float | None = None,
    compute_ms: float = 0.0,
    upload_ms: float = 0.0,
    parameter_apply_ms: float = 0.0,
    bytes_sent: int = 0,
    bytes_received: int = 0,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO worker_steps (
                attempt_id, step_id, worker_id, session_id, shard_id,
                batch_id, sample_count, loss, accuracy,
                compute_ms, upload_ms, parameter_apply_ms,
                bytes_sent, bytes_received
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, step_id, worker_id) DO UPDATE SET
                loss = COALESCE(EXCLUDED.loss, worker_steps.loss),
                accuracy = COALESCE(EXCLUDED.accuracy, worker_steps.accuracy),
                compute_ms = EXCLUDED.compute_ms,
                upload_ms = EXCLUDED.upload_ms,
                parameter_apply_ms = EXCLUDED.parameter_apply_ms,
                bytes_sent = EXCLUDED.bytes_sent,
                bytes_received = EXCLUDED.bytes_received
            RETURNING *
            """,
            (
                attempt_id,
                step_id,
                worker_id,
                session_id,
                shard_id,
                batch_id,
                sample_count,
                loss,
                accuracy,
                compute_ms,
                upload_ms,
                parameter_apply_ms,
                bytes_sent,
                bytes_received,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def upsert_worker_steps_batch(
    conn: psycopg.Connection,
    items: list[dict[str, Any]],
) -> None:
    """Batch upsert multiple worker contributions in a single database roundtrip."""
    if not items:
        return
    normalized = [
        {
            "attempt_id": it["attempt_id"],
            "step_id": it["step_id"],
            "worker_id": it["worker_id"],
            "session_id": it["session_id"],
            "shard_id": it["shard_id"],
            "batch_id": it["batch_id"],
            "sample_count": it["sample_count"],
            "loss": it.get("loss"),
            "accuracy": it.get("accuracy"),
            "compute_ms": float(it.get("compute_ms", 0.0)),
            "upload_ms": float(it.get("upload_ms", 0.0)),
            "parameter_apply_ms": float(it.get("parameter_apply_ms", 0.0)),
            "bytes_sent": int(it.get("bytes_sent", 0)),
            "bytes_received": int(it.get("bytes_received", 0)),
        }
        for it in items
    ]
    sql = """
        INSERT INTO worker_steps (
            attempt_id, step_id, worker_id, session_id, shard_id,
            batch_id, sample_count, loss, accuracy,
            compute_ms, upload_ms, parameter_apply_ms,
            bytes_sent, bytes_received
        ) VALUES (
            %(attempt_id)s, %(step_id)s, %(worker_id)s, %(session_id)s, %(shard_id)s,
            %(batch_id)s, %(sample_count)s, %(loss)s, %(accuracy)s,
            %(compute_ms)s, %(upload_ms)s, %(parameter_apply_ms)s,
            %(bytes_sent)s, %(bytes_received)s
        )
        ON CONFLICT (attempt_id, step_id, worker_id) DO UPDATE SET
            loss = COALESCE(EXCLUDED.loss, worker_steps.loss),
            accuracy = COALESCE(EXCLUDED.accuracy, worker_steps.accuracy),
            compute_ms = EXCLUDED.compute_ms,
            upload_ms = EXCLUDED.upload_ms,
            parameter_apply_ms = EXCLUDED.parameter_apply_ms,
            bytes_sent = EXCLUDED.bytes_sent,
            bytes_received = EXCLUDED.bytes_received
    """
    with conn.cursor() as cur:
        cur.executemany(sql, normalized)

