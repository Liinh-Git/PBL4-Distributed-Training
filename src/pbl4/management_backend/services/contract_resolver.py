"""Contract Resolver — resolves and freezes training contracts prior to attempt launch.

CANONICAL REFERENCES:
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- docs/IMPLEMENTATION_CONTRACT.md

V1 SPECIFICATION:
- RequestedContractV1 has exactly six operator-controlled fields:
  dataset_build_id, model_id, epochs, learning_rate, training_seed, training_strategy.
- ResolvedContract V1 has exact canonical shape:
  dataset (dataset_build_id, dataset_manifest_hash, task_type, input_shape, dtype,
           num_classes, batch_size, shard_count=3, preprocessing)
  model (model_id="resnet18_groupnorm", profile="RESNET18_GROUPNORM_V1", parameter_manifest_hash)
  training (epochs, learning_rate, training_seed)
  synchronization (training_strategy="strict_bsp", expected_workers=3)
  update_policy ({"type": "plain_sgd_without_momentum"})
  checkpoint_policy ({"type": "after_each_model_update_blocking", "schema_version": 1})
  protocols ({"dtp_version": 1, "mcp_version": 1})
- Parameter manifest hash is resolved via ModelMetadataProvider.
  If not authoritatively available, resolve fails closed.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import psycopg

from pbl4.common.hashing import canonical_json_hash
from pbl4.management_backend.repositories import dataset_build_repository
from pbl4.management_backend.services.model_catalog import get_model_metadata_provider

logger = logging.getLogger(__name__)


class ContractResolutionError(Exception):
    def __init__(self, msg: str, errors: list[str] | None = None) -> None:
        super().__init__(msg)
        self.errors = errors or [msg]


def resolve(conn: psycopg.Connection, requested_contract: dict) -> dict:
    """Resolve a requested_contract into an immutable resolved_contract.

    Validates the dataset build is READY and reads its manifest metadata.
    All fields in the resolved contract are immutable after this point.

    Raises ContractResolutionError if any field cannot be resolved or validated.
    """
    errors: list[str] = []

    dataset_manifest_hash: str | None = None
    dsb_id = requested_contract.get("dataset_build_id", "")
    if not dsb_id:
        errors.append("dataset_build_id is required.")
        build = None
    else:
        build = dataset_build_repository.get_build(conn, dsb_id)
        if build is None:
            errors.append(f"Dataset build '{dsb_id}' not found.")
        elif build["state"] != "READY":
            errors.append(
                f"Dataset build '{dsb_id}' is in state '{build['state']}'; must be READY."
            )
        else:
            dataset_manifest_hash = build.get("dataset_manifest_hash") or build.get("manifest_hash")
            if not dataset_manifest_hash:
                errors.append(f"Dataset build '{dsb_id}' has no verified dataset_manifest_hash.")

    model_id = requested_contract.get("model_id", "")
    model_meta = None
    if not model_id:
        errors.append("model_id is required.")
    else:
        provider = get_model_metadata_provider()
        model_meta = provider.get_model_metadata(model_id)
        if model_meta is None:
            errors.append(
                f"Unsupported model_id '{model_id}'. V1 only supports 'resnet18_groupnorm'."
            )
        elif not model_meta.get("parameter_manifest_hash"):
            errors.append(
                f"Authoritative parameter_manifest_hash not available for model '{model_id}'. "
                "Validation/freeze must fail closed per canonical architecture."
            )

    training_strategy = requested_contract.get("training_strategy", "strict_bsp")
    if training_strategy != "strict_bsp":
        errors.append(
            f"Unsupported training_strategy '{training_strategy}'. V1 only supports 'strict_bsp'."
        )

    epochs = requested_contract.get("epochs")
    if epochs is None:
        errors.append("epochs is required.")
    elif isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1:
        errors.append("epochs must be an integer >= 1 (boolean values are rejected).")

    lr = requested_contract.get("learning_rate")
    if lr is None:
        errors.append("learning_rate is required.")
    elif (
        isinstance(lr, bool) or not isinstance(lr, (int, float)) or not math.isfinite(lr) or lr <= 0
    ):
        errors.append("learning_rate must be a finite positive number.")

    training_seed = requested_contract.get("training_seed")
    if training_seed is None:
        errors.append("training_seed is required.")
    elif isinstance(training_seed, bool) or not isinstance(training_seed, int):
        errors.append("training_seed must be an integer (boolean values are rejected).")

    if errors or build is None or model_meta is None:
        raise ContractResolutionError("Contract resolution failed", errors)

    input_shape = build.get("input_shape_json") or []
    if isinstance(input_shape, str):
        input_shape = json.loads(input_shape)

    preprocessing = build.get("preprocessing_json") or {}
    if isinstance(preprocessing, str):
        preprocessing = json.loads(preprocessing)

    resolved: dict[str, Any] = {
        "dataset": {
            "dataset_build_id": build["dataset_build_id"],
            "dataset_manifest_hash": dataset_manifest_hash,
            "task_type": _get_task_type(conn, build["dataset_id"]),
            "input_shape": input_shape or model_meta.get("input_shape", [3, 32, 32]),
            "dtype": build.get("dtype", "float32"),
            "num_classes": build.get("num_classes", model_meta.get("num_classes", 10)),
            "batch_size": build["batch_size"],
            "shard_count": 3,
            "preprocessing": preprocessing,
        },
        "model": {
            "model_id": model_meta["model_id"],
            "profile": model_meta["profile"],
            "parameter_manifest_hash": model_meta["parameter_manifest_hash"],
        },
        "training": {
            "epochs": epochs,
            "learning_rate": float(lr),
            "training_seed": training_seed,
        },
        "synchronization": {
            "training_strategy": "strict_bsp",
            "expected_workers": 3,
        },
        "update_policy": {
            "type": "plain_sgd_without_momentum",
        },
        "checkpoint_policy": {
            "type": "after_each_model_update_blocking",
            "schema_version": 1,
        },
        "protocols": {
            "dtp_version": 1,
            "mcp_version": 1,
        },
    }
    return resolved


def hash_contract(resolved_contract: dict[str, Any]) -> str:
    """Return hex-encoded SHA-256 digest of canonical resolved contract."""
    return canonical_json_hash(resolved_contract)


def _get_task_type(conn: psycopg.Connection, dataset_id: str) -> str:
    from pbl4.management_backend.repositories import dataset_repository

    ds = dataset_repository.get_dataset(conn, dataset_id)
    return ds["task_type"] if ds else ""
