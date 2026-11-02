"""Checkpoint repository — PostgreSQL data access for the checkpoints table.

DB only stores checkpoint index/metadata.
Actual checkpoint bytes reside on the Runtime filesystem.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from pbl4.management_backend.repositories import event_repository

_RETIREMENT_JOIN = """
    LEFT JOIN events r ON r.scope_id = c.checkpoint_id
        AND r.attempt_id = c.created_by_attempt_id
        AND r.scope_type = 'CHECKPOINT' AND r.event_type = 'checkpoint.artifact.retired'
"""


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
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO checkpoints (
                checkpoint_id, created_by_attempt_id, source_operation_id,
                source_step_id, state, model_version, recovery_cursor_jsonb,
                epoch, next_batch_ordinal, contract_hash,
                dataset_build_id, dataset_manifest_hash, parameter_manifest_hash,
                checkpoint_policy, checkpoint_policy_version, created_at
            ) SELECT
                %s, %s, %s, %s, 'WRITING', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM events WHERE scope_type = 'CHECKPOINT'
                    AND event_type = 'checkpoint.artifact.retired'
                    AND scope_id = %s AND attempt_id = %s
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
                checkpoint_id,
                created_by_attempt_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT * FROM checkpoints WHERE checkpoint_id = %s", (checkpoint_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def complete_checkpoint(
    conn: psycopg.Connection,
    checkpoint_id: str,
    *,
    model_path: str,
    metadata_path: str,
    model_sha256: str,
    metadata_sha256: str,
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
                completed_at = %s
            WHERE checkpoint_id = %s AND state = 'WRITING'
            RETURNING *
            """,
            (
                model_path,
                metadata_path,
                model_sha256,
                metadata_sha256,
                completed_at,
                checkpoint_id,
            ),
        )
        row = cur.fetchone()
    return dict(row) if row else None


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
    return dict(row) if row else None


def get_checkpoint(
    conn: psycopg.Connection, checkpoint_id: str, *, for_update: bool = False
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        if for_update:
            # Lock first, then read events using a fresh READ COMMITTED statement snapshot.
            cur.execute(
                "SELECT checkpoint_id FROM checkpoints WHERE checkpoint_id = %s FOR UPDATE",
                (checkpoint_id,),
            )
            if cur.fetchone() is None:
                return None
        cur.execute(
            "SELECT c.*, r.event_id IS NOT NULL AS artifact_retired FROM checkpoints c "
            + _RETIREMENT_JOIN
            + "WHERE c.checkpoint_id = %s",
            (checkpoint_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_checkpoints(
    conn: psycopg.Connection,
    *,
    attempt_id: str | None = None,
    job_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    conditions = ["r.event_id IS NULL"]
    params: list[Any] = []

    if attempt_id:
        conditions.append("c.created_by_attempt_id = %s")
        params.append(attempt_id)
    if job_id:
        # Join via attempts
        conditions.append(
            "c.created_by_attempt_id IN (SELECT attempt_id FROM attempts WHERE job_id = %s)"
        )
        params.append(job_id)
    if state:
        conditions.append("c.state = %s")
        params.append(state)

    if cursor:
        try:
            ts_str, cid = cursor.split("|", 1)
            conditions.append("(c.created_at, c.checkpoint_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, cid])
        except ValueError:
            pass

    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT c.*,
            a.job_id
        FROM checkpoints c
        JOIN attempts a ON c.created_by_attempt_id = a.attempt_id
        {_RETIREMENT_JOIN}
        {where}
        ORDER BY c.created_at DESC, c.checkpoint_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_latest_complete_for_attempt(conn: psycopg.Connection, attempt_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT c.* FROM checkpoints c
            {_RETIREMENT_JOIN}
            WHERE c.created_by_attempt_id = %s AND c.state = 'COMPLETE'
              AND r.event_id IS NULL
            ORDER BY c.model_version DESC
            LIMIT 1
            """,
            (attempt_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def reconcile_artifacts(conn: psycopg.Connection, items: tuple[dict, ...]) -> None:
    """One lookup per page; immutable COMPLETE rows need no repeated writes."""
    if not items:
        return
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT checkpoint_id, state, created_by_attempt_id, contract_hash, "
            "model_sha256, metadata_sha256 FROM checkpoints WHERE checkpoint_id = ANY(%s)",
            ([item["checkpoint_id"] for item in items],),
        )
        known = {row["checkpoint_id"]: row for row in cur.fetchall()}
    for item in items:
        row = known.get(item["checkpoint_id"])
        if row is not None and row["state"] == "COMPLETE":
            expected = {
                "created_by_attempt_id": item["metadata"]["created_by_attempt_id"],
                "contract_hash": item["metadata"]["contract_hash"],
                "model_sha256": item["model_sha256"],
                "metadata_sha256": item["metadata_sha256"],
            }
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError("Checkpoint inventory identity conflict")
            continue
        value = item["metadata"]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT job_id FROM attempts WHERE attempt_id = %s",
                (value["created_by_attempt_id"],),
            )
            owner = cur.fetchone()
        if owner is None or owner["job_id"] != value["job_id"]:
            continue
        model, cursor = value["model"], value["recovery_cursor"]
        row = create_checkpoint(
            conn,
            checkpoint_id=value["checkpoint_id"],
            created_by_attempt_id=value["created_by_attempt_id"],
            source_operation_id=value["source_operation_id"],
            source_step_id=value["source_step_id"],
            model_version=model["model_version"],
            recovery_cursor_jsonb=cursor,
            epoch=cursor["epoch"],
            next_batch_ordinal=cursor["next_batch_ordinal"],
            contract_hash=value["contract_hash"],
            dataset_build_id=value["dataset_build_id"],
            dataset_manifest_hash=value["dataset_manifest_hash"],
            parameter_manifest_hash=model["parameter_manifest_hash"],
            checkpoint_policy=value["checkpoint_policy"],
            checkpoint_policy_version=value["checkpoint_policy_version"],
            created_at=value["created_at"],
        )
        if row is None:
            continue
        if (
            row["created_by_attempt_id"] != value["created_by_attempt_id"]
            or row["contract_hash"] != value["contract_hash"]
        ):
            raise ValueError("Checkpoint inventory identity conflict")
        complete_checkpoint(
            conn,
            value["checkpoint_id"],
            model_path="model.bin",
            metadata_path="checkpoint.json",
            model_sha256=item["model_sha256"],
            metadata_sha256=item["metadata_sha256"],
            completed_at=value["created_at"],
        )


def retention_candidates(
    conn: psycopg.Connection, keep_latest: int, available_ids: list[str]
) -> list[dict]:
    if type(keep_latest) is not int or keep_latest <= 0:
        raise ValueError("keep_latest must be positive")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT c.*, a.job_id, row_number() OVER (
                    PARTITION BY a.job_id ORDER BY c.created_at DESC, c.checkpoint_id DESC
                ) AS position
                FROM checkpoints c JOIN attempts a ON a.attempt_id = c.created_by_attempt_id
                {_RETIREMENT_JOIN}
                WHERE c.state = 'COMPLETE' AND r.event_id IS NULL
                  AND c.checkpoint_id = ANY(%s)
            )
            SELECT ranked.* FROM ranked WHERE position > %s
            AND NOT EXISTS (
                SELECT 1 FROM attempts source
                WHERE source.resume_from_checkpoint_id = ranked.checkpoint_id
            )
            ORDER BY created_at, checkpoint_id LIMIT 100
            """,
            (available_ids, keep_latest),
        )
        return [dict(row) for row in cur.fetchall()]


def retire_artifact(
    conn: psycopg.Connection,
    checkpoint_id: str,
    keep_latest: int,
    available_ids: list[str],
) -> bool:
    """Caller owns transaction; resume takes the same row lock before referencing."""
    row = get_checkpoint(conn, checkpoint_id, for_update=True)
    if row is None or row["artifact_retired"]:
        return False
    # Serialize keep-set changes for this Job across Backend instances.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(job_id, 0)) "
            "FROM attempts WHERE attempt_id = %s",
            (row["created_by_attempt_id"],),
        )
    if checkpoint_id not in {
        r["checkpoint_id"] for r in retention_candidates(conn, keep_latest, available_ids)
    }:
        return False
    now = datetime.now(UTC)
    event_repository.insert_event(
        conn,
        event_type="checkpoint.artifact.retired",
        scope_type="CHECKPOINT",
        scope_id=checkpoint_id,
        attempt_id=row["created_by_attempt_id"],
        severity="INFO",
        occurred_at=now,
        persisted_at=now,
        payload={"checkpoint_id": checkpoint_id, "keep_latest": keep_latest},
    )
    return True


def pending_artifact_deletions(conn: psycopg.Connection) -> list[dict]:
    """The existing checkpoint row is the retry record until physical deletion succeeds."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT c.* FROM checkpoints c {_RETIREMENT_JOIN} "
            "WHERE r.event_id IS NOT NULL ORDER BY r.occurred_at, c.checkpoint_id LIMIT 100"
        )
        return [dict(row) for row in cur.fetchall()]


def confirm_artifact_deleted(conn: psycopg.Connection, checkpoint_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM checkpoints c USING events r
            WHERE c.checkpoint_id = %s AND r.scope_id = c.checkpoint_id
              AND r.attempt_id = c.created_by_attempt_id
              AND r.scope_type = 'CHECKPOINT' AND r.event_type = 'checkpoint.artifact.retired'
              AND NOT EXISTS (
                  SELECT 1 FROM attempts WHERE resume_from_checkpoint_id = c.checkpoint_id
              )
            """,
            (checkpoint_id,),
        )
