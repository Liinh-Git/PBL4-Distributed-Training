"""Dataset Service — business logic for dataset and dataset build management.

Dataset build lifecycle (state machine):
  CREATED → QUEUED → IMPORTING → VALIDATING → PREPROCESSING
         → MATERIALIZING → VERIFYING → REGISTERING → READY
  Any state → FAILED
  READY → DEPRECATED
  READY/DEPRECATED/FAILED → DELETING → DELETED
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import psycopg

from management_backend.repositories import (
    dataset_repository,
    dataset_build_repository,
    command_repository,
)

logger = logging.getLogger(__name__)


class DatasetNotFoundError(Exception):
    pass


class DatasetBuildNotFoundError(Exception):
    pass


class DatasetBuildStateError(Exception):
    def __init__(self, msg: str, current_state: str = "") -> None:
        super().__init__(msg)
        self.current_state = current_state


class DatasetBuildReferenceError(Exception):
    """Build cannot be deleted because active references exist."""
    pass


def _new_dataset_id() -> str:
    return f"ds_{uuid.uuid4().hex[:12]}"


def _new_build_id() -> str:
    return f"dsb_{uuid.uuid4().hex[:12]}"


def _new_command_id() -> str:
    return str(uuid.uuid4())


# ─── Dataset ──────────────────────────────────────────────────────────────────

def create_dataset(
    conn: psycopg.Connection,
    *,
    name: str,
    task_type: str,
    source_type: str,
    source_reference: str,
) -> dict:
    dataset_id = _new_dataset_id()
    now = datetime.now(timezone.utc)
    row = dataset_repository.create_dataset(
        conn,
        dataset_id=dataset_id,
        name=name,
        task_type=task_type,
        source_type=source_type,
        source_reference=source_reference,
        created_at=now,
    )
    logger.info("Dataset created: %s", dataset_id)
    return row


def get_dataset(conn: psycopg.Connection, dataset_id: str) -> dict:
    row = dataset_repository.get_dataset(conn, dataset_id)
    if row is None:
        raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found.")
    counts = dataset_repository.get_build_counts_for_dataset(conn, dataset_id)
    return {**row, "build_counts": counts}


def list_datasets(
    conn: psycopg.Connection,
    *,
    task_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    return dataset_repository.list_datasets(
        conn, task_type=task_type, q=q, limit=limit, cursor=cursor
    )


# ─── Dataset Build ────────────────────────────────────────────────────────────

def create_build(
    conn: psycopg.Connection,
    *,
    dataset_id: str,
    profile: str,
    batch_size: int,
    partition_seed: int,
    preprocessing: dict,
) -> tuple[dict, dict]:
    """Create a new dataset build + a PENDING CREATE_DATASET_BUILD command.

    Returns (build_row, command_row).
    Per data-flow spec: command persisted in same transaction as build creation.
    """
    ds = dataset_repository.get_dataset(conn, dataset_id)
    if ds is None:
        raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found.")

    build_id = _new_build_id()
    command_id = _new_command_id()
    now = datetime.now(timezone.utc)

    # Reasonable defaults for build metadata
    input_shape = preprocessing.get("input_shape") or [3, 32, 32]
    normalization = preprocessing.get("normalization") or {}
    preprocessing_stored = {
        "input_shape": input_shape,
        "normalization": normalization,
    }

    build_row = dataset_build_repository.create_build(
        conn,
        dataset_build_id=build_id,
        dataset_id=dataset_id,
        profile=profile,
        batch_size=batch_size,
        shard_count=1,  # will be updated by dataset manager
        partition_seed=partition_seed,
        sample_count=0,  # will be updated by dataset manager
        input_shape_json=input_shape,
        dtype="float32",
        num_classes=0,  # will be updated by dataset manager
        preprocessing_json=preprocessing_stored,
        created_at=now,
    )

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="CREATE_DATASET_BUILD",
        target_type="DATASET_BUILD",
        target_id=build_id,
        request={"dataset_build_id": build_id, "dataset_id": dataset_id},
        requested_at=now,
    )

    logger.info("Dataset build created: %s (cmd=%s)", build_id, command_id)
    return build_row, cmd_row


def get_build(conn: psycopg.Connection, dataset_build_id: str) -> dict:
    row = dataset_build_repository.get_build(conn, dataset_build_id)
    if row is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    return row


def list_builds(
    conn: psycopg.Connection,
    *,
    dataset_id: str | None = None,
    state: str | None = None,
    profile: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    return dataset_build_repository.list_builds(
        conn,
        dataset_id=dataset_id,
        state=state,
        profile=profile,
        limit=limit,
        cursor=cursor,
    )


def rebuild_build(
    conn: psycopg.Connection,
    dataset_build_id: str,
    *,
    batch_size: int | None = None,
    partition_seed: int | None = None,
    preprocessing: dict | None = None,
) -> tuple[dict, dict]:
    """Trigger a rebuild of an existing build. Returns (new_build_row, command_row)."""
    source = dataset_build_repository.get_build(conn, dataset_build_id)
    if source is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    if source["state"] not in {"READY", "FAILED", "DEPRECATED"}:
        raise DatasetBuildStateError(
            f"Build '{dataset_build_id}' is in state '{source['state']}'; "
            "only READY, FAILED, or DEPRECATED builds can be rebuilt.",
            current_state=source["state"],
        )

    new_build_id = _new_build_id()
    command_id = _new_command_id()
    now = datetime.now(timezone.utc)

    src_preprocessing = source.get("preprocessing_json") or {}
    if isinstance(src_preprocessing, str):
        import json
        src_preprocessing = json.loads(src_preprocessing)
    src_input_shape = source.get("input_shape_json") or [3, 32, 32]
    if isinstance(src_input_shape, str):
        import json
        src_input_shape = json.loads(src_input_shape)

    merged_preprocessing = {**src_preprocessing, **(preprocessing or {})}
    new_batch_size = batch_size or source["batch_size"]
    new_seed = partition_seed if partition_seed is not None else source["partition_seed"]

    new_build = dataset_build_repository.create_build(
        conn,
        dataset_build_id=new_build_id,
        dataset_id=source["dataset_id"],
        profile=source["profile"],
        batch_size=new_batch_size,
        shard_count=1,
        partition_seed=new_seed,
        sample_count=0,
        input_shape_json=merged_preprocessing.get("input_shape", src_input_shape),
        dtype=source["dtype"],
        num_classes=source["num_classes"],
        preprocessing_json=merged_preprocessing,
        created_at=now,
    )

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="REBUILD_DATASET_BUILD",
        target_type="DATASET_BUILD",
        target_id=new_build_id,
        request={
            "new_dataset_build_id": new_build_id,
            "source_dataset_build_id": dataset_build_id,
        },
        requested_at=now,
    )

    logger.info("Dataset build rebuild requested: %s → %s (cmd=%s)", dataset_build_id, new_build_id, command_id)
    return new_build, cmd_row


def deprecate_build(
    conn: psycopg.Connection, dataset_build_id: str
) -> dict:
    build = dataset_build_repository.get_build(conn, dataset_build_id)
    if build is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    if build["state"] != "READY":
        raise DatasetBuildStateError(
            f"Build '{dataset_build_id}' is '{build['state']}'; only READY builds can be deprecated.",
            current_state=build["state"],
        )
    now = datetime.now(timezone.utc)
    row = dataset_build_repository.update_build_state(
        conn, dataset_build_id, "DEPRECATED", deprecated_at=now
    )
    logger.info("Dataset build deprecated: %s", dataset_build_id)
    return row


def delete_build(
    conn: psycopg.Connection, dataset_build_id: str
) -> tuple[dict, dict]:
    """Mark build as DELETING and issue a DELETE_DATASET_BUILD command."""
    build = dataset_build_repository.get_build(conn, dataset_build_id)
    if build is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    if build["state"] not in {"READY", "DEPRECATED", "FAILED"}:
        raise DatasetBuildStateError(
            f"Build '{dataset_build_id}' is '{build['state']}'; cannot delete.",
            current_state=build["state"],
        )

    refs = dataset_build_repository.get_references(conn, dataset_build_id)
    active_refs = [r for r in refs if r["type"] == "CHECKPOINT"]
    if active_refs:
        raise DatasetBuildReferenceError(
            f"Build '{dataset_build_id}' is referenced by {len(active_refs)} checkpoint(s)."
        )

    now = datetime.now(timezone.utc)
    command_id = _new_command_id()

    build_row = dataset_build_repository.update_build_state(
        conn, dataset_build_id, "DELETING"
    )
    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="DELETE_DATASET_BUILD",
        target_type="DATASET_BUILD",
        target_id=dataset_build_id,
        request={"dataset_build_id": dataset_build_id},
        requested_at=now,
    )

    logger.info("Dataset build delete requested: %s (cmd=%s)", dataset_build_id, command_id)
    return build_row, cmd_row
