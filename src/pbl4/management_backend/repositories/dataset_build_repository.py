"""Dataset Build repository — PostgreSQL data access for dataset_builds table."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATASET_BUILD_STATES = {
    "CREATED",
    "QUEUED",
    "IMPORTING",
    "VALIDATING",
    "PREPROCESSING",
    "MATERIALIZING",
    "VERIFYING",
    "REGISTERING",
    "READY",
    "FAILED",
    "DEPRECATED",
    "DELETING",
    "DELETED",
}

# States from which a build is "selectable" for a new job
SELECTABLE_STATES = {"READY"}
# States from which we allow deprecation
DEPRECATABLE_STATES = {"READY"}
# States from which we allow delete
DELETABLE_STATES = {"READY", "DEPRECATED", "FAILED"}


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_build(
    conn: psycopg.Connection,
    *,
    dataset_build_id: str,
    dataset_id: str,
    profile: str,
    batch_size: int,
    shard_count: int,
    partition_seed: int,
    sample_count: int | None = None,
    input_shape_json: list,
    dtype: str,
    num_classes: int,
    preprocessing_json: dict,
    created_at: datetime,
    state: str = "CREATED",
) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO dataset_builds (
                dataset_build_id, dataset_id, state, profile,
                input_shape_json, dtype, num_classes, preprocessing_json,
                batch_size, shard_count, partition_seed, sample_count,
                manifest_uri, dataset_manifest_hash, manifest_snapshot_jsonb,
                artifact_base_url, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                NULL, NULL, NULL, NULL, %s
            )
            RETURNING *
            """,
            (
                dataset_build_id,
                dataset_id,
                state,
                profile,
                json.dumps(input_shape_json),
                dtype,
                num_classes,
                json.dumps(preprocessing_json),
                batch_size,
                shard_count,
                partition_seed,
                sample_count,
                created_at,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_build(conn: psycopg.Connection, dataset_build_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM dataset_builds WHERE dataset_build_id = %s",
            (dataset_build_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_builds(
    conn: psycopg.Connection,
    *,
    dataset_id: str | None = None,
    state: str | None = None,
    profile: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    conditions = []
    params: list[Any] = []

    if dataset_id:
        conditions.append("dataset_id = %s")
        params.append(dataset_id)
    if state:
        conditions.append("state = %s")
        params.append(state)
    if profile:
        conditions.append("profile = %s")
        params.append(profile)

    if cursor:
        try:
            ts_str, bid = cursor.split("|", 1)
            conditions.append("(created_at, dataset_build_id) < (%s::timestamptz, %s)")
            params.extend([ts_str, bid])
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    sql = f"""
        SELECT * FROM dataset_builds
        {where}
        ORDER BY created_at DESC, dataset_build_id DESC
        LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def update_build_state(
    conn: psycopg.Connection,
    dataset_build_id: str,
    new_state: str,
    *,
    ready_at: datetime | None = None,
    deprecated_at: datetime | None = None,
    manifest_uri: str | None = None,
    dataset_manifest_hash: str | None = None,
    manifest_snapshot_jsonb: dict | None = None,
    artifact_base_url: str | None = None,
    registration_id: str | None = None,
    registration_acknowledged_at: datetime | None = None,
    shard_count: int | None = None,
    sample_count: int | None = None,
) -> dict | None:
    sets = ["state = %s"]
    params: list[Any] = [new_state]

    if ready_at is not None:
        sets.append("ready_at = %s")
        params.append(ready_at)
    if deprecated_at is not None:
        sets.append("deprecated_at = %s")
        params.append(deprecated_at)
    if manifest_uri is not None:
        sets.append("manifest_uri = %s")
        params.append(manifest_uri)
    if dataset_manifest_hash is not None:
        sets.append("dataset_manifest_hash = %s")
        params.append(dataset_manifest_hash)
    if manifest_snapshot_jsonb is not None:
        sets.append("manifest_snapshot_jsonb = %s")
        params.append(json.dumps(manifest_snapshot_jsonb))
    if artifact_base_url is not None:
        sets.append("artifact_base_url = %s")
        params.append(artifact_base_url)
    if registration_id is not None:
        sets.append("registration_id = %s")
        params.append(registration_id)
    if registration_acknowledged_at is not None:
        sets.append("registration_acknowledged_at = %s")
        params.append(registration_acknowledged_at)
    if shard_count is not None:
        sets.append("shard_count = %s")
        params.append(shard_count)
    if sample_count is not None:
        sets.append("sample_count = %s")
        params.append(sample_count)

    params.append(dataset_build_id)
    sql = f"UPDATE dataset_builds SET {', '.join(sets)} WHERE dataset_build_id = %s RETURNING *"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_references(conn: psycopg.Connection, dataset_build_id: str) -> list[dict]:
    """Return job/checkpoint references for a given build (for delete gate)."""
    refs = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id FROM jobs
            WHERE requested_contract->>'dataset_build_id' = %s
               OR resolved_contract->'dataset'->>'dataset_build_id' = %s
            """,
            (dataset_build_id, dataset_build_id),
        )
        for (jid,) in cur.fetchall():
            refs.append({"type": "JOB", "id": jid})

        cur.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE dataset_build_id = %s",
            (dataset_build_id,),
        )
        for (cid,) in cur.fetchall():
            refs.append({"type": "CHECKPOINT", "id": cid})

    return refs
