"""Dataset Service — business logic for dataset source catalog and build lifecycle.

CANONICAL SPECIFICATION:
- 01. Dataset Manager
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. API Backend & Contracts

LIFECYCLE INVARIANTS:
- Dataset Build states:
  CREATED → QUEUED → IMPORTING → VALIDATING → PREPROCESSING → MATERIALIZING →
  VERIFYING → REGISTERING → READY
  READY → DEPRECATED → DELETING → DELETED
  any active state → FAILED
- Backend NEVER generates dataset_build_id on create or new_dataset_build_id on rebuild.
  Dataset Manager owns build identity generation.
- Short DB transactions: external HTTP calls to Dataset Manager MUST NOT occur inside open
  DB transactions.
- Idempotency: command is persisted PENDING in TX1 before HTTP dispatch; on downstream failure,
  command remains PENDING for retry with same command_id and Idempotency-Key.
- Delete gate: READY builds cannot be purged directly; only DEPRECATED or FAILED builds may be
  deleted. Rejects with 409 DATASET_BUILD_IN_USE if referenced by jobs or checkpoints.
- Registration gate: root manifest SHA-256 independently verified; catalog persisted in TX1;
  registration ACK sent outside TX; only after DM returns authoritative READY is READY mirrored
  in TX2.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from pbl4.common.hashing import sha256_bytes
from pbl4.management_backend.clients.dataset_manager import (
    DatasetManagerBusinessError,
    DatasetManagerUnavailableError,
    get_client,
)
from pbl4.management_backend.repositories import (
    command_repository,
    dataset_build_repository,
    dataset_repository,
)
from pbl4.management_backend.services import idempotency

logger = logging.getLogger(__name__)


def _require_idempotency_key(value: str | None) -> str:
    if not value:
        raise ValueError("Idempotency-Key is required for this mutation.")
    return value


def _require_dm_state(response: dict[str, Any], operation: str) -> str:
    state = response.get("state") or response.get("status")
    if state not in dataset_build_repository.DATASET_BUILD_STATES:
        raise DatasetManagerUnavailableError(
            f"Dataset Manager {operation} response has no valid authoritative state."
        )
    return state


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


def execute_create_build(
    db_module: Any,
    *,
    dataset_id: str,
    profile: str,
    batch_size: int,
    partition_seed: int,
    preprocessing: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Execute build creation following the canonical 2-phase transaction pattern.

    TX1: Validate dataset, acquire idempotency, persist CREATE_DATASET_BUILD command PENDING.
    Outside TX: HTTP POST to Dataset Manager (resolving public request into internal DM body,
    no build ID sent).
    TX2: Persist DatasetBuild using DM-owned ID, update command to ACCEPTED, complete idempotency.
    """
    preprocessing_dict = preprocessing or {}
    input_shape = preprocessing_dict.get("input_shape") or [3, 32, 32]
    normalization = preprocessing_dict.get("normalization") or {
        "mean": [0.4914, 0.4822, 0.4465],
        "std": [0.2470, 0.2435, 0.2616],
    }
    preprocessing_stored = {
        "input_shape": input_shape,
        "normalization": normalization,
    }

    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="CREATE_DATASET_BUILD",
        path="/api/v1/dataset-builds",
        body_obj={
            "dataset_id": dataset_id,
            "profile": profile,
            "batch_size": batch_size,
            "partition_seed": partition_seed,
            "preprocessing": preprocessing_stored,
        },
    )

    # ─── TX 1: Check idempotency, validate dataset, create PENDING command ───
    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_CREATE",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            # Recover build row and command row
            b_id = body.get("dataset_build_id")
            c_id = body.get("command_id")
            build_row = dataset_build_repository.get_build(conn, b_id) if b_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return build_row or body, cmd_row or body

        ds = dataset_repository.get_dataset(conn, dataset_id)
        if ds is None:
            raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found.")

        dm_source = resolve_dataset_manager_source(ds["source_type"], ds["source_reference"])

        # Reuse command_id if resuming an unconfirmed dispatch
        if action == "RESUME" and cached_record and cached_record.get("command_id"):
            command_id = str(cached_record["command_id"])
            cmd_row = command_repository.get_command(conn, command_id)
        else:
            command_id = _new_command_id()
            now = datetime.now(UTC)
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="CREATE_DATASET_BUILD",
                target_type="DATASET_BUILD",
                target_id=None,
                request={
                    "dataset_id": dataset_id,
                    "source": dm_source,
                    "batch_size": batch_size,
                    "partition_seed": partition_seed,
                    "profile": profile,
                    "input_shape": input_shape,
                    "normalization": normalization,
                },
                requested_at=now,
            )

    # ─── Outside TX: HTTP POST to Dataset Manager ────────────────────────────
    try:
        dm_resp = get_client().create_build(
            command_id=command_id,
            idempotency_key=effective_key,
            source=dm_source,
            profile=profile,
            input_shape=input_shape,
            normalization=normalization,
            batch_size=batch_size,
            partition_seed=partition_seed,
            shard_count=3,
        )
    except DatasetManagerBusinessError as exc:
        logger.warning(
            "Dataset Manager rejected create_build for command %s: %s [%s]",
            command_id,
            exc.message,
            exc.code,
        )
        with db_module.transaction() as conn:
            command_repository.update_command_state(
                conn,
                command_id=command_id,
                new_state="REJECTED",
                result={"code": exc.code, "message": exc.message, "status_code": exc.status_code},
            )
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_CREATE",
                idempotency_key=effective_key,
                response_status_code=exc.status_code,
                response_body={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "command_id": command_id,
                        "details": {
                            "downstream_code": exc.code,
                            "downstream_status": exc.status_code,
                        },
                    }
                },
                command_id=command_id,
            )
        raise
    except DatasetManagerUnavailableError:
        logger.warning(
            "Downstream dispatch to Dataset Manager failed for command %s (remains PENDING)",
            command_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_CREATE",
                idempotency_key=effective_key,
                command_id=command_id,
            )
        raise
    except Exception as exc:
        logger.warning(
            "Downstream dispatch to Dataset Manager failed for command %s (remains PENDING): %s",
            command_id,
            exc,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_CREATE",
                idempotency_key=effective_key,
                command_id=command_id,
            )
        raise DatasetManagerUnavailableError(str(exc)) from exc

    # DM returned authoritative dataset_build_id and state
    dm_build_id = dm_resp["dataset_build_id"]
    dm_state = _require_dm_state(dm_resp, "create")
    now = datetime.now(UTC)

    # ─── TX 2: Persist DatasetBuild projection, update command to ACCEPTED ───
    with db_module.transaction() as conn:
        # Check if build row was already persisted by earlier try
        existing_build = dataset_build_repository.get_build(conn, dm_build_id)
        if existing_build is None:
            build_row = dataset_build_repository.create_build(
                conn,
                dataset_build_id=dm_build_id,
                dataset_id=dataset_id,
                profile=profile,
                batch_size=batch_size,
                shard_count=3,
                partition_seed=partition_seed,
                sample_count=None,
                input_shape_json=input_shape,
                dtype="float32",
                num_classes=10,
                preprocessing_json=preprocessing_stored,
                created_at=now,
                state=dm_state,
            )
        else:
            build_row = existing_build

        cmd_row = command_repository.update_command_state(
            conn,
            command_id=command_id,
            new_state="ACCEPTED",
            target_id=dm_build_id,
            dispatched_at=now,
            result=dm_resp,
        )

        resp_payload = {
            "command_id": command_id,
            "command_type": "CREATE_DATASET_BUILD",
            "command_state": "ACCEPTED",
            "target_type": "DATASET_BUILD",
            "target_id": dm_build_id,
            "dataset_build_id": dm_build_id,
            "dataset_build_state": dm_state,
        }
        idempotency.complete_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_CREATE",
            idempotency_key=effective_key,
            response_status_code=202,
            response_body=resp_payload,
            command_id=command_id,
            resource_id=dm_build_id,
        )

    logger.info("Dataset build created: %s (cmd=%s)", dm_build_id, command_id)
    if cmd_row is None:
        raise RuntimeError(f"Command '{command_id}' disappeared during create persistence.")
    return build_row, cmd_row


def execute_rebuild_build(
    db_module: Any,
    dataset_build_id: str,
    *,
    batch_size: int | None = None,
    partition_seed: int | None = None,
    preprocessing: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Trigger rebuild following canonical 2-phase pattern. DM generates the new build ID."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="REBUILD_DATASET_BUILD",
        path=f"/api/v1/dataset-builds/{dataset_build_id}/rebuild",
        body_obj={
            "source_dataset_build_id": dataset_build_id,
            "batch_size": batch_size,
            "partition_seed": partition_seed,
            "preprocessing": preprocessing,
        },
    )

    # ─── TX 1: Validate source build, create PENDING command ─────────────────
    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_REBUILD",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            b_id = body.get("dataset_build_id") or body.get("new_dataset_build_id")
            c_id = body.get("command_id")
            build_row = dataset_build_repository.get_build(conn, b_id) if b_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return build_row or body, cmd_row or body

        source = dataset_build_repository.get_build(conn, dataset_build_id)
        if source is None:
            raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
        if source["state"] not in {"READY", "FAILED", "DEPRECATED"}:
            raise DatasetBuildStateError(
                f"Build '{dataset_build_id}' is in state '{source['state']}'; "
                "only READY, FAILED, or DEPRECATED builds can be rebuilt.",
                current_state=source["state"],
            )

        src_preprocessing = source.get("preprocessing_json") or {}
        if isinstance(src_preprocessing, str):
            src_preprocessing = json.loads(src_preprocessing)
        src_input_shape = source.get("input_shape_json") or [3, 32, 32]
        if isinstance(src_input_shape, str):
            src_input_shape = json.loads(src_input_shape)

        merged_preprocessing = {**src_preprocessing, **(preprocessing or {})}
        new_batch_size = batch_size or source["batch_size"]
        new_seed = partition_seed if partition_seed is not None else source["partition_seed"]
        input_shape = merged_preprocessing.get("input_shape", src_input_shape)
        normalization = merged_preprocessing.get("normalization", {})

        if action == "RESUME" and cached_record and cached_record.get("command_id"):
            command_id = str(cached_record["command_id"])
            cmd_row = command_repository.get_command(conn, command_id)
        else:
            command_id = _new_command_id()
            now = datetime.now(UTC)
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="REBUILD_DATASET_BUILD",
                target_type="DATASET_BUILD",
                target_id=None,
                request={
                    "source_dataset_build_id": dataset_build_id,
                    "batch_size": new_batch_size,
                    "partition_seed": new_seed,
                    "input_shape": input_shape,
                    "normalization": normalization,
                },
                requested_at=now,
            )

    # ─── Outside TX: HTTP POST to Dataset Manager rebuild ───────────────────
    try:
        dm_resp = get_client().rebuild(
            source_dataset_build_id=dataset_build_id,
            command_id=command_id,
            idempotency_key=effective_key,
            batch_size=new_batch_size,
            partition_seed=new_seed,
            input_shape=input_shape,
            normalization=normalization,
        )
    except DatasetManagerBusinessError as exc:
        logger.warning(
            "Dataset Manager rejected rebuild for %s: %s [%s]",
            dataset_build_id,
            exc.message,
            exc.code,
        )
        with db_module.transaction() as conn:
            command_repository.update_command_state(
                conn,
                command_id=command_id,
                new_state="REJECTED",
                result={"code": exc.code, "message": exc.message, "status_code": exc.status_code},
            )
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_REBUILD",
                idempotency_key=effective_key,
                response_status_code=exc.status_code,
                response_body={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "command_id": command_id,
                        "details": {
                            "downstream_code": exc.code,
                            "downstream_status": exc.status_code,
                        },
                    }
                },
                command_id=command_id,
            )
        raise
    except DatasetManagerUnavailableError:
        logger.warning(
            "Downstream rebuild dispatch to DM failed for %s (remains PENDING)",
            dataset_build_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_REBUILD",
                idempotency_key=effective_key,
                command_id=command_id,
            )
        raise
    except Exception as exc:
        logger.warning(
            "Downstream rebuild dispatch to DM failed for %s (remains PENDING): %s",
            dataset_build_id,
            exc,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_REBUILD",
                idempotency_key=effective_key,
                command_id=command_id,
            )
        raise DatasetManagerUnavailableError(str(exc)) from exc

    new_build_id = dm_resp.get("dataset_build_id") or dm_resp.get("new_dataset_build_id")
    if not new_build_id:
        raise DatasetManagerUnavailableError(
            "Dataset Manager rebuild did not return authoritative build ID."
        )

    dm_state = _require_dm_state(dm_resp, "rebuild")
    now = datetime.now(UTC)

    # ─── TX 2: Persist new DatasetBuild, update command ───────────────────────
    with db_module.transaction() as conn:
        existing = dataset_build_repository.get_build(conn, new_build_id)
        if existing is None:
            new_build = dataset_build_repository.create_build(
                conn,
                dataset_build_id=new_build_id,
                dataset_id=source["dataset_id"],
                profile=source["profile"],
                batch_size=new_batch_size,
                shard_count=3,
                partition_seed=new_seed,
                sample_count=None,
                input_shape_json=input_shape,
                dtype=source["dtype"],
                num_classes=source["num_classes"],
                preprocessing_json=merged_preprocessing,
                created_at=now,
                state=dm_state,
            )
        else:
            new_build = existing

        cmd_row = command_repository.update_command_state(
            conn,
            command_id=command_id,
            new_state="ACCEPTED",
            target_id=new_build_id,
            dispatched_at=now,
            result=dm_resp,
        )

        resp_payload = {
            "command_id": command_id,
            "command_type": "REBUILD_DATASET_BUILD",
            "command_state": "ACCEPTED",
            "target_type": "DATASET_BUILD",
            "target_id": new_build_id,
            "dataset_build_id": new_build_id,
            "dataset_build_state": dm_state,
            "source_dataset_build_id": dataset_build_id,
            "new_dataset_build_id": new_build_id,
        }
        idempotency.complete_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_REBUILD",
            idempotency_key=effective_key,
            response_status_code=202,
            response_body=resp_payload,
            command_id=command_id,
            resource_id=new_build_id,
        )

    logger.info(
        "Dataset build rebuilt: %s → %s (cmd=%s)", dataset_build_id, new_build_id, command_id
    )
    if cmd_row is None:
        raise RuntimeError(f"Command '{command_id}' disappeared during rebuild persistence.")
    return new_build, cmd_row


def execute_deprecate_build(
    db_module: Any,
    dataset_build_id: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Deprecate a READY dataset build with idempotency."""
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="DEPRECATE_DATASET_BUILD",
        path=f"/api/v1/dataset-builds/{dataset_build_id}/deprecate",
        body_obj={"dataset_build_id": dataset_build_id, "reason": reason},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_DEPRECATE",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )
        if action == "SUCCEEDED" and cached_record:
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            b_id = body.get("dataset_build_id")
            row = dataset_build_repository.get_build(conn, b_id) if b_id else {}
            return row or body

        build = dataset_build_repository.get_build(conn, dataset_build_id)
        if build is None:
            raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
        if build["state"] != "READY":
            raise DatasetBuildStateError(
                f"Build '{dataset_build_id}' is '{build['state']}'; "
                "only READY builds can be deprecated.",
                current_state=build["state"],
            )

    # Call DM outside DB transaction
    dm_resp = get_client().deprecate(dataset_build_id, reason=reason)
    dm_state = _require_dm_state(dm_resp, "deprecate")
    if dm_state != "DEPRECATED":
        raise DatasetBuildStateError(
            f"Dataset Manager returned '{dm_state}' after deprecate; expected DEPRECATED.",
            current_state=dm_state,
        )
    now = datetime.now(UTC)

    # Mirror authoritative DEPRECATED state in DB
    with db_module.transaction() as conn:
        row = dataset_build_repository.update_build_state(
            conn,
            dataset_build_id,
            dm_state,
            deprecated_at=now,
        )
        resp_payload = {
            "dataset_build_id": dataset_build_id,
            "state": dm_state,
            "deprecated_at": now.isoformat(),
        }
        idempotency.complete_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_DEPRECATE",
            idempotency_key=effective_key,
            response_status_code=200,
            response_body=resp_payload,
            resource_id=dataset_build_id,
        )

    logger.info("Dataset build deprecated: %s", dataset_build_id)
    return row or {
        "dataset_build_id": dataset_build_id,
        "state": dm_state,
        "deprecated_at": now,
    }


def execute_delete_build(
    db_module: Any,
    dataset_build_id: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, dict]:
    """Delete a dataset build with durable HTTP idempotency.

    Enforces:
    - Only DEPRECATED or FAILED builds can be deleted (READY must be deprecated first).
    - Reject if referenced by jobs or checkpoints (DATASET_BUILD_IN_USE).
    - TX1: Persist DELETE_DATASET_BUILD command PENDING -> COMMIT.
    - Outside TX: Call DM purge. On timeout/error, remains PENDING and reusable on retry.
    - TX2: Mirror DELETING state and update command -> COMMIT.
    """
    effective_key = _require_idempotency_key(idempotency_key)
    request_hash = idempotency.compute_request_hash(
        operation="DELETE_DATASET_BUILD",
        path=f"/api/v1/dataset-builds/{dataset_build_id}/delete",
        body_obj={"dataset_build_id": dataset_build_id, "reason": reason},
    )

    with db_module.transaction() as conn:
        cached_record, action = idempotency.acquire_or_get_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_DELETE",
            idempotency_key=effective_key,
            canonical_request_hash=request_hash,
        )

        if action == "SUCCEEDED" and cached_record:
            body = cached_record.get("response_body_jsonb") or {}
            if isinstance(body, str):
                body = json.loads(body)
            b_id = body.get("dataset_build_id")
            c_id = body.get("command_id")
            build_row = dataset_build_repository.get_build(conn, b_id) if b_id else {}
            cmd_row = command_repository.get_command(conn, c_id) if c_id else {}
            return build_row or body, cmd_row or body

        build = dataset_build_repository.get_build(conn, dataset_build_id)
        if build is None:
            raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
        if build["state"] not in {"DEPRECATED", "FAILED", "DELETING"}:
            raise DatasetBuildStateError(
                f"Build '{dataset_build_id}' is '{build['state']}'; "
                "only DEPRECATED or FAILED builds can be deleted.",
                current_state=build["state"],
            )

        refs = dataset_build_repository.get_references(conn, dataset_build_id)
        if refs:
            raise DatasetBuildReferenceError(
                f"Build '{dataset_build_id}' is referenced by {len(refs)} "
                f"resource(s) (jobs/checkpoints): {refs}."
            )

        if action == "RESUME" and cached_record and cached_record.get("command_id"):
            command_id = str(cached_record["command_id"])
            cmd_row = command_repository.get_command(conn, command_id)
        else:
            command_id = _new_command_id()
            now = datetime.now(UTC)
            cmd_row = command_repository.create_command(
                conn,
                command_id=command_id,
                command_type="DELETE_DATASET_BUILD",
                target_type="DATASET_BUILD",
                target_id=dataset_build_id,
                request={"dataset_build_id": dataset_build_id, "reason": reason},
                requested_at=now,
            )

    # Outside TX: Call DM purge
    try:
        dm_resp = get_client().purge(
            dataset_build_id,
            command_id=command_id,
            reason=reason,
            force=False,
        )
    except DatasetManagerBusinessError as exc:
        logger.warning(
            "Dataset Manager rejected purge for %s: %s [%s]",
            dataset_build_id,
            exc.message,
            exc.code,
        )
        with db_module.transaction() as conn:
            command_repository.update_command_state(
                conn,
                command_id=command_id,
                new_state="REJECTED",
                result={"code": exc.code, "message": exc.message, "status_code": exc.status_code},
            )
            idempotency.complete_record(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_DELETE",
                idempotency_key=effective_key,
                response_status_code=exc.status_code,
                response_body={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "command_id": command_id,
                        "details": {
                            "downstream_code": exc.code,
                            "downstream_status": exc.status_code,
                        },
                    }
                },
                command_id=command_id,
                resource_id=dataset_build_id,
            )
        raise
    except DatasetManagerUnavailableError:
        logger.warning(
            "Downstream purge dispatch to DM failed for %s (remains PENDING)",
            dataset_build_id,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_DELETE",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=dataset_build_id,
            )
        raise
    except Exception as exc:
        logger.warning(
            "Downstream purge dispatch to DM failed for %s (remains PENDING): %s",
            dataset_build_id,
            exc,
        )
        with db_module.transaction() as conn:
            idempotency.record_dispatch_failure(
                conn,
                endpoint_semantic_scope="DATASET_BUILD_DELETE",
                idempotency_key=effective_key,
                command_id=command_id,
                resource_id=dataset_build_id,
            )
        raise DatasetManagerUnavailableError(str(exc)) from exc

    dm_state = _require_dm_state(dm_resp, "purge")

    # TX 2: Mirror only the authoritative Dataset Manager state
    now = datetime.now(UTC)
    with db_module.transaction() as conn:
        build_row = dataset_build_repository.update_build_state(conn, dataset_build_id, dm_state)
        cmd_row = command_repository.update_command_state(
            conn,
            command_id=command_id,
            new_state="ACCEPTED",
            dispatched_at=now,
            result=dm_resp,
        )
        resp_payload = {
            "command_id": command_id,
            "command_type": "DELETE_DATASET_BUILD",
            "command_state": "ACCEPTED",
            "target_type": "DATASET_BUILD",
            "target_id": dataset_build_id,
            "dataset_build_id": dataset_build_id,
            "dataset_build_state": dm_state,
        }
        idempotency.complete_record(
            conn,
            endpoint_semantic_scope="DATASET_BUILD_DELETE",
            idempotency_key=effective_key,
            response_status_code=202,
            response_body=resp_payload,
            command_id=command_id,
            resource_id=dataset_build_id,
        )

    logger.info("Dataset build delete requested: %s (cmd=%s)", dataset_build_id, command_id)
    if build_row is None or cmd_row is None:
        raise RuntimeError(f"Delete result for build '{dataset_build_id}' was not persisted.")
    return build_row, cmd_row


def verify_and_register_build(
    db_module: Any,
    dataset_build_id: str,
    *,
    manifest_data: dict[str, Any] | None = None,
    manifest_raw_bytes: bytes | None = None,
    artifact_base_url: str | None = None,
    manifest_uri: str | None = None,
) -> dict:
    """Verify the DM-status manifest, persist the catalog, and acknowledge registration.

    Flow:
    1. GET DM build status -> require state == REGISTERING.
    2. Read authoritative: dataset_manifest_hash, manifest_uri, artifact_base_url, build metadata.
    3. GET manifest raw bytes from DM.
    4. Compute SHA-256 independently and compare against authoritative DM STATUS hash.
    5. Short DB TX: persist verified catalog data + registration_id (state REGISTERING) -> COMMIT.
    6. Outside TX: Send registration ACK to DM.
    7. Short DB TX: Mirror only authoritative state returned by DM -> COMMIT.
    """
    dm_client = get_client()

    # 1. GET DM build status & require REGISTERING
    dm_status = dm_client.get_build(dataset_build_id)
    if dm_status is None:
        raise DatasetBuildNotFoundError(
            f"Dataset build '{dataset_build_id}' not found on Dataset Manager."
        )

    current_state = dm_status.get("state") or dm_status.get("status")
    if current_state != "REGISTERING":
        raise DatasetBuildStateError(
            f"Dataset build '{dataset_build_id}' is in state '{current_state}'; "
            "must be REGISTERING to register.",
            current_state=current_state or "",
        )

    authoritative_hash = dm_status.get("dataset_manifest_hash")
    if not authoritative_hash:
        raise DatasetManifestVerificationError(
            f"Dataset build '{dataset_build_id}' status from DM has no authoritative "
            "dataset_manifest_hash."
        )

    authoritative_manifest_uri = dm_status.get("manifest_uri")
    authoritative_artifact_url = dm_status.get("artifact_base_url")
    if not authoritative_manifest_uri or not authoritative_artifact_url:
        raise DatasetManifestVerificationError(
            f"Dataset build '{dataset_build_id}' status is missing published artifact locations."
        )
    _ = (manifest_uri, artifact_base_url)

    # 2. GET manifest raw bytes
    if manifest_raw_bytes is None or manifest_data is None:
        fetched_data, fetched_bytes = dm_client.get_manifest(dataset_build_id)
        if manifest_raw_bytes is None:
            manifest_raw_bytes = fetched_bytes
        if manifest_data is None:
            manifest_data = fetched_data

    # 3. Compute SHA-256 independently and compare against authoritative DM STATUS hash
    calculated_hash = sha256_bytes(manifest_raw_bytes)
    if calculated_hash != authoritative_hash:
        raise DatasetManifestVerificationError(
            f"Independent SHA-256 mismatch for build '{dataset_build_id}': "
            f"authoritative DM status hash '{authoritative_hash}' != "
            f"computed hash '{calculated_hash}'."
        )

    # 4. Validate required published metadata and persist a stable registration identity.
    now = datetime.now(UTC)
    sample_count = dm_status.get("sample_count")
    shard_count = dm_status.get("shard_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 1:
        raise DatasetManifestVerificationError("DM status sample_count must be a positive integer.")
    if not isinstance(shard_count, int) or isinstance(shard_count, bool) or shard_count < 1:
        raise DatasetManifestVerificationError("DM status shard_count must be a positive integer.")
    manifest_shard_count = manifest_data.get("shard_count")
    manifest_sample_count = manifest_data.get("sample_count", manifest_data.get("total_samples"))
    if manifest_shard_count != shard_count or manifest_sample_count != sample_count:
        raise DatasetManifestVerificationError(
            "Root manifest metadata does not match authoritative Dataset Manager status."
        )

    with db_module.transaction() as conn:
        build = dataset_build_repository.get_build(conn, dataset_build_id)
        if build is None:
            raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
        persisted_hash = build.get("dataset_manifest_hash")
        if persisted_hash and persisted_hash != authoritative_hash:
            raise DatasetManifestVerificationError(
                "Dataset Manager changed dataset_manifest_hash during registration retry."
            )
        registration_id = build.get("registration_id") or f"reg_{uuid.uuid4().hex[:12]}"

        dataset_build_repository.update_build_state(
            conn,
            dataset_build_id,
            "REGISTERING",
            manifest_uri=authoritative_manifest_uri,
            dataset_manifest_hash=calculated_hash,
            manifest_snapshot_jsonb=manifest_data,
            artifact_base_url=authoritative_artifact_url,
            registration_id=registration_id,
            sample_count=sample_count,
            shard_count=shard_count,
        )

    # 5. Outside TX: Send registration-ack to Dataset Manager
    catalog_persisted_at = now.isoformat()
    ack_resp = dm_client.registration_ack(
        dataset_build_id,
        dataset_manifest_hash=calculated_hash,
        registration_id=registration_id,
        catalog_persisted_at=catalog_persisted_at,
    )

    authoritative_state = _require_dm_state(ack_resp, "registration ACK")
    ack_now = datetime.now(UTC)

    # 6. Short DB TX: Mirror authoritative state returned by DM
    with db_module.transaction() as conn:
        updated_row = dataset_build_repository.update_build_state(
            conn,
            dataset_build_id,
            authoritative_state,
            ready_at=ack_now if authoritative_state == "READY" else None,
            registration_acknowledged_at=ack_now,
        )

    logger.info(
        "Dataset build registered: %s (authoritative state=%s)",
        dataset_build_id,
        authoritative_state,
    )
    return updated_row or {}


def refresh_build_from_dataset_manager(db_module: Any, dataset_build_id: str) -> dict:
    """Refresh a build and complete the canonical registration gate when ready.

    This is invoked by the public status read path.  It never infers READY: the
    Dataset Manager must first report REGISTERING and must return READY from the
    explicit registration acknowledgement.
    """
    dm_status = get_client().get_build(dataset_build_id)
    if dm_status is None:
        raise DatasetBuildNotFoundError(
            f"Dataset build '{dataset_build_id}' not found on Dataset Manager."
        )
    state = _require_dm_state(dm_status, "status refresh")
    if state == "REGISTERING":
        return verify_and_register_build(db_module, dataset_build_id)
    with db_module.transaction() as conn:
        current = dataset_build_repository.get_build(conn, dataset_build_id)
        if current is None:
            raise DatasetBuildNotFoundError(f"Dataset build '{dataset_build_id}' not found.")
        if current["state"] in {"READY", "FAILED", "DEPRECATED", "DELETED"}:
            return current
        updated = dataset_build_repository.update_build_state(
            conn,
            dataset_build_id,
            state,
            sample_count=dm_status.get("sample_count"),
            shard_count=dm_status.get("shard_count"),
        )
    return updated or current


# ─── Backward compatibility wrappers for direct connection callers ───────────


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
    """Compatibility wrapper for tests passing an existing connection."""

    class ConnAdapter:
        @staticmethod
        def transaction():
            return conn.transaction() if hasattr(conn, "transaction") else conn

    return execute_create_build(
        ConnAdapter,
        dataset_id=dataset_id,
        profile=profile,
        batch_size=batch_size,
        partition_seed=partition_seed,
        preprocessing=preprocessing,
        idempotency_key=idempotency_key,
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
    class ConnAdapter:
        @staticmethod
        def transaction():
            return conn.transaction() if hasattr(conn, "transaction") else conn

    return execute_rebuild_build(
        ConnAdapter,
        dataset_build_id,
        batch_size=batch_size,
        partition_seed=partition_seed,
        preprocessing=preprocessing,
        idempotency_key=idempotency_key,
    )


def deprecate_build(
    conn: psycopg.Connection, dataset_build_id: str, reason: str | None = None
) -> dict:
    class ConnAdapter:
        @staticmethod
        def get_connection():
            from contextlib import nullcontext

            return nullcontext(conn)

        @staticmethod
        def transaction():
            return conn.transaction() if hasattr(conn, "transaction") else conn

    return execute_deprecate_build(ConnAdapter, dataset_build_id, reason=reason)


def delete_build(
    conn: psycopg.Connection, dataset_build_id: str, reason: str | None = None
) -> tuple[dict, dict]:
    class ConnAdapter:
        @staticmethod
        def get_connection():
            from contextlib import nullcontext

            return nullcontext(conn)

        @staticmethod
        def transaction():
            return conn.transaction() if hasattr(conn, "transaction") else conn

    return execute_delete_build(ConnAdapter, dataset_build_id, reason=reason)
