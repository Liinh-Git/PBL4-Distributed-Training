"""Dataset Service — business logic for dataset source catalog and build lifecycle.

State machine for dataset builds:
  CREATED → QUEUED → IMPORTING → VALIDATING → PREPROCESSING → MATERIALIZING →
  VERIFYING → REGISTERING → READY
  READY → DEPRECATED → DELETING → PURGED / DELETED
  any active state → FAILED

V1 invariants:
  - Source schemas: Public Dataset provenance fields (source_type, source_reference) are kept
    separate from Dataset Manager internal source schema
    (resolved via resolve_dataset_manager_source).
  - For CIFAR-10 V1:
      logical: source_type=builtin, source_reference=cifar10
      resolved DM source: {"type": "cifar10_download", "dataset_name": "cifar10"}
  - Backend preserves both Idempotency-Key and command_id when dispatching downstream commands.
  - Delete rule: Backend NEVER calls purge directly on READY builds.
    READY builds must be DEPRECATED before deletion. Deletion only succeeds on DEPRECATED or FAILED.
  - Delete reference gate: rejects with 409 DATASET_BUILD_IN_USE if referenced by jobs
    or checkpoints.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from pbl4.common.hashing import sha256_bytes
from pbl4.management_backend.clients.dataset_manager import get_client
from pbl4.management_backend.repositories import (
    command_repository,
    dataset_build_repository,
    dataset_repository,
)

logger = logging.getLogger(__name__)


class DatasetNotFoundError(Exception):
    pass


class DatasetBuildNotFoundError(Exception):
    pass


class DatasetBuildStateError(Exception):
    code = "INVALID_STATE"

    def __init__(self, msg: str, current_state: str = "") -> None:
        super().__init__(msg)
        self.current_state = current_state


class DatasetBuildReferenceError(Exception):
    code = "DATASET_BUILD_IN_USE"


DatasetBuildInUseError = DatasetBuildReferenceError


class DatasetManifestVerificationError(Exception):
    pass


def _new_dataset_id() -> str:
    return f"ds_{uuid.uuid4().hex[:8]}"


def _new_build_id() -> str:
    return f"dsb_{uuid.uuid4().hex[:12]}"


def _new_command_id() -> str:
    return str(uuid.uuid4())


def resolve_dataset_manager_source(source_type: str, source_reference: str) -> dict[str, Any]:
    """Resolve internal Dataset Manager source spec from logical dataset provenance.

    Canonical V1 mapping:
      source_type="builtin", source_reference="cifar10" ->
        {"type": "cifar10_download", "dataset_name": "cifar10"}
    """
    if source_type == "builtin" and source_reference == "cifar10":
        return {
            "type": "cifar10_download",
            "dataset_name": "cifar10",
        }
    raise ValueError(
        f"Unsupported dataset source mapping: source_type='{source_type}', "
        f"source_reference='{source_reference}'. V1 only supports builtin/cifar10."
    )


# ─── Dataset Source ───────────────────────────────────────────────────────────


def create_dataset(
    conn: psycopg.Connection,
    *,
    name: str,
    task_type: str,
    source_type: str,
    source_reference: str,
) -> dict:
    dataset_id = _new_dataset_id()
    now = datetime.now(UTC)
    row = dataset_repository.create_dataset(
        conn,
        dataset_id=dataset_id,
        name=name,
        task_type=task_type,
        source_type=source_type,
        source_reference=source_reference,
        created_at=now,
    )
    logger.info("Dataset created: %s (%s)", dataset_id, name)
    return row


def get_dataset(conn: psycopg.Connection, dataset_id: str) -> dict:
    row = dataset_repository.get_dataset(conn, dataset_id)
    if row is None:
        raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found.")
    counts = dataset_repository.get_build_counts(conn, dataset_id)
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
    preprocessing: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Create a new dataset build + a PENDING CREATE_DATASET_BUILD command.

    Returns (build_row, command_row).
    """
    ds = dataset_repository.get_dataset(conn, dataset_id)
    if ds is None:
        raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found.")

    build_id = _new_build_id()
    command_id = _new_command_id()
    now = datetime.now(UTC)

    preprocessing_dict = preprocessing or {}
    input_shape = preprocessing_dict.get("input_shape") or [3, 32, 32]
    normalization = preprocessing_dict.get("normalization") or {}
    preprocessing_stored = {
        "input_shape": input_shape,
        "normalization": normalization,
    }

    dm_source = resolve_dataset_manager_source(ds["source_type"], ds["source_reference"])

    build_row = dataset_build_repository.create_build(
        conn,
        dataset_build_id=build_id,
        dataset_id=dataset_id,
        profile=profile,
        batch_size=batch_size,
        shard_count=1,
        partition_seed=partition_seed,
        sample_count=0,
        input_shape_json=input_shape,
        dtype="float32",
        num_classes=0,
        preprocessing_json=preprocessing_stored,
        created_at=now,
    )

    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="CREATE_DATASET_BUILD",
        target_type="DATASET_BUILD",
        target_id=build_id,
        request={
            "dataset_build_id": build_id,
            "dataset_id": dataset_id,
            "source": dm_source,
            "batch_size": batch_size,
            "partition_seed": partition_seed,
            "profile": profile,
            "preprocessing": preprocessing_stored,
        },
        requested_at=now,
    )

    # Dispatch downstream to Dataset Manager (best-effort fire-and-forget; durable command is saved)
    effective_idempotency_key = idempotency_key or f"cmd_{command_id}"
    try:
        get_client().create_build(
            dataset_build_id=build_id,
            command_id=command_id,
            idempotency_key=effective_idempotency_key,
            source=dm_source,
            batch_size=batch_size,
            partition_seed=partition_seed,
            profile=profile,
            preprocessing=preprocessing_stored,
        )
    except Exception as exc:
        logger.warning(
            "Initial downstream dispatch to Dataset Manager failed for %s (will be retried): %s",
            build_id,
            exc,
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
    preprocessing: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
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
    now = datetime.now(UTC)

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
            "batch_size": new_batch_size,
            "partition_seed": new_seed,
            "preprocessing": merged_preprocessing,
        },
        requested_at=now,
    )

    effective_idempotency_key = idempotency_key or f"cmd_{command_id}"
    try:
        get_client().rebuild(
            source_dataset_build_id=dataset_build_id,
            new_dataset_build_id=new_build_id,
            command_id=command_id,
            idempotency_key=effective_idempotency_key,
            batch_size=new_batch_size,
            partition_seed=new_seed,
            preprocessing=merged_preprocessing,
        )
    except Exception as exc:
        logger.warning(
            "Initial downstream dispatch to Dataset Manager rebuild failed for %s: %s",
            new_build_id,
            exc,
        )

    logger.info(
        "Dataset build rebuild requested: %s → %s (cmd=%s)",
        dataset_build_id,
        new_build_id,
        command_id,
    )
    return new_build, cmd_row


def deprecate_build(conn: psycopg.Connection, dataset_build_id: str) -> dict:
    build = dataset_build_repository.get_build(conn, dataset_build_id)
    if build is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    if build["state"] != "READY":
        raise DatasetBuildStateError(
            f"Build '{dataset_build_id}' is '{build['state']}'; "
            "only READY builds can be deprecated.",
            current_state=build["state"],
        )
    now = datetime.now(UTC)
    row = dataset_build_repository.update_build_state(
        conn, dataset_build_id, "DEPRECATED", deprecated_at=now
    )

    try:
        get_client().deprecate(dataset_build_id)
    except Exception as exc:
        logger.warning("Downstream deprecation dispatch failed for %s: %s", dataset_build_id, exc)

    logger.info("Dataset build deprecated: %s", dataset_build_id)
    return row


def delete_build(conn: psycopg.Connection, dataset_build_id: str) -> tuple[dict, dict]:
    """Mark build as DELETING and issue a DELETE_DATASET_BUILD command.

    Invariants:
      - Only DEPRECATED or FAILED builds may be deleted. READY builds cannot be purged directly.
      - Reject if referenced by any job or checkpoint (DATASET_BUILD_IN_USE).
    """
    build = dataset_build_repository.get_build(conn, dataset_build_id)
    if build is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
    if build["state"] not in {"DEPRECATED", "FAILED"}:
        raise DatasetBuildStateError(
            f"Build '{dataset_build_id}' is '{build['state']}'; "
            "only DEPRECATED or FAILED builds can be deleted.",
            current_state=build["state"],
        )

    refs = dataset_build_repository.get_references(conn, dataset_build_id)
    if refs:
        raise DatasetBuildReferenceError(
            f"Build '{dataset_build_id}' is referenced by {len(refs)} "
            "resource(s) (jobs/checkpoints)."
        )

    now = datetime.now(UTC)
    command_id = _new_command_id()

    build_row = dataset_build_repository.update_build_state(conn, dataset_build_id, "DELETING")
    cmd_row = command_repository.create_command(
        conn,
        command_id=command_id,
        command_type="DELETE_DATASET_BUILD",
        target_type="DATASET_BUILD",
        target_id=dataset_build_id,
        request={"dataset_build_id": dataset_build_id},
        requested_at=now,
    )

    try:
        get_client().purge(dataset_build_id)
    except Exception as exc:
        logger.warning(
            "Downstream purge dispatch to Dataset Manager failed for %s: %s", dataset_build_id, exc
        )

    logger.info("Dataset build delete requested: %s (cmd=%s)", dataset_build_id, command_id)
    return build_row, cmd_row


def verify_and_register_build(
    conn: psycopg.Connection,
    dataset_build_id: str,
    *,
    manifest_data: dict[str, Any],
    manifest_raw_bytes: bytes,
    artifact_base_url: str,
    manifest_uri: str,
) -> dict:
    """Verify manifest integrity, persist root manifest snapshot, and acknowledge registration."""
    build = dataset_build_repository.get_build(conn, dataset_build_id)
    if build is None:
        raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")

    calculated_hash = sha256_bytes(manifest_raw_bytes)
    declared_hash = manifest_data.get("dataset_manifest_hash")
    if declared_hash and calculated_hash != declared_hash:
        raise DatasetManifestVerificationError(
            f"Manifest hash mismatch for build '{dataset_build_id}': "
            f"declared '{declared_hash}', calculated '{calculated_hash}'."
        )

    now = datetime.now(UTC)
    registration_id = f"reg_{uuid.uuid4().hex[:12]}"
    sample_count = manifest_data.get("sample_count", 0)
    shard_count = manifest_data.get("shard_count", 1)

    updated_row = dataset_build_repository.update_build_state(
        conn,
        dataset_build_id,
        "READY",
        ready_at=now,
        manifest_uri=manifest_uri,
        dataset_manifest_hash=calculated_hash,
        manifest_snapshot_jsonb=manifest_data,
        artifact_base_url=artifact_base_url,
        registration_id=registration_id,
        registration_acknowledged_at=now,
        sample_count=sample_count,
        shard_count=shard_count,
    )

    try:
        get_client().registration_ack(
            dataset_build_id,
            {"registration_id": registration_id, "state": "READY"},
        )
    except Exception as exc:
        logger.warning("Downstream registration-ack failed for %s: %s", dataset_build_id, exc)

    logger.info("Dataset build registered as READY: %s", dataset_build_id)
    return updated_row or {}
