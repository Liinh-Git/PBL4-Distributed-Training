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

from pbl4.common.hashing import canonical_json_hash
from pbl4.management_backend.config import get_settings
from pbl4.management_backend.repositories import dataset_build_repository
from pbl4.management_backend.services.model_catalog import validate_model_id

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
    errors: list[str] = []

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

    # V1 expected_workers: resolved via strategy context configuration (defaults to 3)
    settings = get_settings()
    expected_workers = int(
        requested_contract.get("expected_workers") or settings.expected_workers
    )

    model_id = requested_contract.get("model_id", "")
    model_def = None
    if not model_id:
        errors.append("model_id is required.")
    else:
        try:
            model_def = validate_model_id(model_id)
        except ValueError as e:
            errors.append(str(e))

    training_strategy = requested_contract.get("training_strategy", "strict_bsp")
    if training_strategy != "strict_bsp":
        errors.append(
            f"Unsupported training_strategy '{training_strategy}'. V1 only supports 'strict_bsp'."
        )

    if errors:
        raise ContractResolutionError("Contract resolution failed", errors)

    assert model_def is not None

    resolved: dict[str, Any] = {
        "dataset": {
            "dataset_build_id": build["dataset_build_id"],
            "dataset_manifest_hash": build.get("dataset_manifest_hash", ""),
            "task_type": _get_task_type(conn, build["dataset_id"]),
            "input_shape": input_shape or model_def.get("input_shape", [3, 32, 32]),
            "dtype": build.get("dtype", "float32"),
            "num_classes": build.get("num_classes", model_def.get("num_classes", 10)),
            "batch_size": build["batch_size"],
            "shard_count": build["shard_count"],
            "preprocessing": preprocessing,
        },
        "model": {
            "model_id": model_id,
            "profile": model_def["profile"],
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
        "update_policy": {
            "type": model_def.get("default_optimizer", "plain_sgd_without_momentum"),
            "learning_rate": float(requested_contract.get("learning_rate", 0.01)),
        },
        "checkpoint_policy": {
            "cadence": model_def.get(
                "default_checkpoint_cadence", "after_each_model_update_blocking"
            ),
            "schema_version": 1,
        },
        "protocols": {"dtp_version": 1, "mcp_version": 1},
    }
    return resolved


def hash_contract(resolved_contract: dict[str, Any]) -> str:
    """Return hex-encoded SHA-256 digest of canonical resolved contract."""
    return canonical_json_hash(resolved_contract)


def _get_task_type(conn: psycopg.Connection, dataset_id: str) -> str:
    from pbl4.management_backend.repositories import dataset_repository

    ds = dataset_repository.get_dataset(conn, dataset_id)
    return ds["task_type"] if ds else ""
