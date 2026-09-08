"""Contract Resolver — resolves and freezes training contracts prior to attempt launch.

OWNS:
- Merging Job specification, verified dataset manifest, and cluster topology into a frozen contract.
- Freezing expected_workers, training_strategy, hyperparameters, and seed.

MUST NOT OWN:
- Runtime StrategyContext instantiation.
- Worker session assignment or registration.
- Modifying contract values after attempt initialization.

V1 INVARIANTS:
- expected_workers is resolved from configuration, never hard-coded outside this module.
- The resolved contract is completely immutable once attempt execution begins.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from management_backend.repositories import dataset_build_repository

logger = logging.getLogger(__name__)


class ContractResolutionError(Exception):
    def __init__(self, msg: str, errors: list[str] | None = None) -> None:
        super().__init__(msg)
        self.errors = errors or [msg]


def resolve(conn: psycopg.Connection, requested_contract: dict) -> dict:
    """Resolve a requested_contract into an immutable resolved_contract.

    Validates the dataset build is READY and reads its manifest metadata.
    All fields in the resolved contract are immutable after this point.

    Raises ContractResolutionError if any field cannot be resolved.
    """
    errors = []

    dsb_id = requested_contract.get("dataset_build_id", "")
    if not dsb_id:
        raise ContractResolutionError("dataset_build_id is required.")

    build = dataset_build_repository.get_build(conn, dsb_id)
    if build is None:
        raise ContractResolutionError(f"Dataset build '{dsb_id}' not found.")
    if build["state"] != "READY":
        raise ContractResolutionError(
            f"Dataset build '{dsb_id}' is in state '{build['state']}'; must be READY."
        )

    input_shape = build.get("input_shape_json") or []
    if isinstance(input_shape, str):
        input_shape = json.loads(input_shape)

    preprocessing = build.get("preprocessing_json") or {}
    if isinstance(preprocessing, str):
        preprocessing = json.loads(preprocessing)

    # V1 expected_workers: default to 1 (will be overridden by runtime on HELLO)
    # This can be wired to topology config when cluster management is available
    expected_workers = 1

    model_id = requested_contract.get("model_id", "")
    if not model_id:
        errors.append("model_id is required.")

    training_strategy = requested_contract.get("training_strategy", "strict_bsp")
    if training_strategy != "strict_bsp":
        errors.append(f"Unsupported training_strategy '{training_strategy}'. V1 only supports 'strict_bsp'.")

    if errors:
        raise ContractResolutionError("Contract resolution failed", errors)

    resolved: dict[str, Any] = {
        "dataset": {
            "dataset_build_id": build["dataset_build_id"],
            "dataset_manifest_hash": build.get("dataset_manifest_hash", ""),
            "task_type": _get_task_type(conn, build["dataset_id"]),
            "input_shape": input_shape,
            "dtype": build.get("dtype", "float32"),
            "num_classes": build.get("num_classes", 0),
            "batch_size": build["batch_size"],
            "shard_count": build["shard_count"],
            "preprocessing": preprocessing,
        },
        "model": {
            "model_id": model_id,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",  # V1: single supported profile
            "parameter_manifest_hash": "",  # populated by Runtime on HELLO
        },
        "training": {
            "epochs": requested_contract.get("epochs", 1),
            "learning_rate": float(requested_contract.get("learning_rate", 0.01)),
            "training_seed": requested_contract.get("training_seed", 42),
        },
        "synchronization": {
            "training_strategy": training_strategy,
            "expected_workers": expected_workers,
        },
        "update_policy": {"type": "SGD"},
        "checkpoint_policy": {"type": "BEST_LOSS", "schema_version": 1},
        "protocols": {"dtp_version": 1, "mcp_version": 1},
    }
    return resolved


def _get_task_type(conn: psycopg.Connection, dataset_id: str) -> str:
    from management_backend.repositories import dataset_repository
    ds = dataset_repository.get_dataset(conn, dataset_id)
    return ds["task_type"] if ds else ""
