"""Production Checkpoint V1 serializer using explicit canonical JSON + FP32 bytes."""

from __future__ import annotations

import json
import re
from typing import ClassVar

import numpy as np

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointSerializer
from pbl4.runtime.snapshot import CheckpointSnapshot


class CheckpointV1Serializer(CheckpointSerializer):
    """Serialize V1 without pickle or framework-owned object representations."""

    _FIELDS: ClassVar[set[str]] = {
        "checkpoint_schema_version",
        "checkpoint_id",
        "job_id",
        "created_by_attempt_id",
        "contract_hash",
        "checkpoint_policy",
        "checkpoint_policy_version",
        "training_strategy",
        "dataset_build_id",
        "dataset_manifest_hash",
        "model_id",
        "model_profile",
        "source_operation_id",
        "source_step_id",
        "optimizer",
        "created_at",
        "model",
        "recovery_cursor",
    }

    def serialize(self, snapshot: CheckpointSnapshot) -> tuple[bytes, bytes]:
        self._validate_snapshot(snapshot)
        payload = snapshot.model.parameters.astype("<f4", copy=False).tobytes()
        metadata = canonical_json_bytes(
            {
                "checkpoint_schema_version": snapshot.checkpoint_schema_version,
                "checkpoint_id": snapshot.checkpoint_id,
                "job_id": snapshot.job_id,
                "created_by_attempt_id": snapshot.created_by_attempt_id,
                "contract_hash": snapshot.contract_hash,
                "checkpoint_policy": snapshot.checkpoint_policy,
                "checkpoint_policy_version": snapshot.checkpoint_policy_version,
                "training_strategy": snapshot.training_strategy,
                "dataset_build_id": snapshot.dataset_build_id,
                "dataset_manifest_hash": snapshot.dataset_manifest_hash,
                "model_id": snapshot.model_id,
                "model_profile": snapshot.model_profile,
                "source_operation_id": snapshot.source_operation_id,
                "source_step_id": snapshot.source_step_id,
                "optimizer": snapshot.optimizer,
                "created_at": snapshot.created_at,
                "model": {
                    "encoding": "fp32_le_v1",
                    "model_version": snapshot.model.model_version,
                    "parameter_manifest_hash": snapshot.model.parameter_manifest_hash,
                    "total_numel": snapshot.model.parameters.size,
                    "payload_size_bytes": len(payload),
                    "payload_sha256": sha256_bytes(payload),
                },
                "recovery_cursor": {
                    "epoch": snapshot.recovery_cursor.epoch,
                    "next_batch_ordinal": snapshot.recovery_cursor.next_batch_ordinal,
                },
            }
        )
        return payload, metadata

    def deserialize(self, payload: bytes, metadata: bytes) -> CheckpointSnapshot:
        try:
            value = json.loads(metadata)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Checkpoint metadata is not valid JSON") from exc
        if not isinstance(value, dict) or set(value) != self._FIELDS:
            raise ValueError("Checkpoint metadata fields do not match V1")
        if canonical_json_bytes(value) != metadata:
            raise ValueError("Checkpoint metadata is not canonical JSON")
        model = value["model"]
        cursor = value["recovery_cursor"]
        if not isinstance(model, dict) or set(model) != {
            "encoding",
            "model_version",
            "parameter_manifest_hash",
            "total_numel",
            "payload_size_bytes",
            "payload_sha256",
        }:
            raise ValueError("Checkpoint model metadata is malformed")
        if not isinstance(cursor, dict) or set(cursor) != {"epoch", "next_batch_ordinal"}:
            raise ValueError("Checkpoint recovery cursor is malformed")
        if (
            model["encoding"] != "fp32_le_v1"
            or type(model["payload_size_bytes"]) is not int
            or model["payload_size_bytes"] != len(payload)
            or type(model["total_numel"]) is not int
            or model["total_numel"] <= 0
            or len(payload) != model["total_numel"] * 4
            or model["payload_sha256"] != sha256_bytes(payload)
        ):
            raise ValueError("Checkpoint model payload integrity mismatch")
        parameters = np.frombuffer(payload, dtype="<f4").astype(np.float32, copy=True)
        snapshot = CheckpointSnapshot(
            checkpoint_id=value["checkpoint_id"],
            checkpoint_schema_version=value["checkpoint_schema_version"],
            job_id=value["job_id"],
            created_by_attempt_id=value["created_by_attempt_id"],
            contract_hash=value["contract_hash"],
            checkpoint_policy=value["checkpoint_policy"],
            checkpoint_policy_version=value["checkpoint_policy_version"],
            training_strategy=value["training_strategy"],
            dataset_build_id=value["dataset_build_id"],
            dataset_manifest_hash=value["dataset_manifest_hash"],
            model_id=value["model_id"],
            model_profile=value["model_profile"],
            source_operation_id=value["source_operation_id"],
            source_step_id=value["source_step_id"],
            optimizer=value["optimizer"],
            created_at=value["created_at"],
            model=ModelSnapshot(
                model["model_version"], model["parameter_manifest_hash"], parameters.tobytes()
            ),
            recovery_cursor=RecoveryCursor(cursor["epoch"], cursor["next_batch_ordinal"]),
        )
        self._validate_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _validate_snapshot(snapshot: CheckpointSnapshot) -> None:
        if snapshot.checkpoint_schema_version != 1:
            raise ValueError("Unsupported checkpoint_schema_version")
        if snapshot.checkpoint_policy != "after_each_model_update_blocking":
            raise ValueError("Unsupported checkpoint policy")
        if snapshot.checkpoint_policy_version != 1:
            raise ValueError("Unsupported checkpoint policy version")
        if snapshot.training_strategy != "strict_bsp":
            raise ValueError("Unsupported training strategy")
        if snapshot.optimizer not in {"plain_sgd", "plain_sgd_without_momentum"}:
            raise ValueError("Checkpoint V1 supports plain SGD without momentum only")
        if any(
            not isinstance(value, str) or not value
            for value in (
                snapshot.checkpoint_id,
                snapshot.job_id,
                snapshot.created_by_attempt_id,
                snapshot.contract_hash,
                snapshot.dataset_build_id,
                snapshot.model_id,
                snapshot.model_profile,
                snapshot.created_at,
            )
        ):
            raise ValueError("Checkpoint identity metadata is incomplete")
        for digest in (
            snapshot.dataset_manifest_hash,
            snapshot.model.parameter_manifest_hash,
        ):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Checkpoint manifest hash is invalid")
        if (
            type(snapshot.source_operation_id) is not int
            or snapshot.source_operation_id < 0
            or (
                snapshot.source_step_id is not None
                and (type(snapshot.source_step_id) is not int or snapshot.source_step_id < 0)
            )
            or type(snapshot.recovery_cursor.epoch) is not int
            or snapshot.recovery_cursor.epoch < 0
            or type(snapshot.recovery_cursor.next_batch_ordinal) is not int
            or snapshot.recovery_cursor.next_batch_ordinal < 0
        ):
            raise ValueError("Checkpoint source/recovery metadata is invalid")
